"""
Claude Code CLI backend — persistent process pool with stdin/stdout NDJSON.

Architecture:
  Each conversation gets ONE long-lived claude process (--input-format stream-json).
  Prompts are injected via stdin, responses streamed from stdout.
  Context stays in memory across turns — no --resume token reload.
  Idle sessions are reaped after IDLE_TIMEOUT seconds.
  Crashed sessions can be revived via --resume (session file on disk).

Reference:
  - claude-inject (MIT): https://github.com/buzzie-ai/claude-inject
  - Agent SDK: https://code.claude.com/docs/en/agent-sdk/sessions
"""
import asyncio
import json
import os
import re
import shutil
import signal
import time
from pathlib import Path
from typing import AsyncGenerator, Dict, Optional

from logger import logger
import config

CLAUDE_CWD = os.getenv("CLAUDE_CWD", str(Path.home()))
CLAUDE_BIN = shutil.which("claude") or shutil.which("claude.cmd") or "claude"
CLAUDE_EFFORT = os.getenv("CLAUDE_EFFORT", "high")
ANSI_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07')

# Sentinel pushed to queue when reader task dies
class _ReaderError:
    def __init__(self, reason: str):
        self.reason = reason

# Background tool completion threshold — a bg tool_use (e.g. Agent)
# produces at least 2 tool_result messages: (1) ack/agent_id, (2) real output.
BG_TOOL_RESULT_THRESHOLD = 2

# Maximum events buffered before we drop oldest (safety valve)
EVENT_QUEUE_MAXSIZE = 500

# Timeout for send_message() waiting on the next event from the reader
# before force-breaking (prevents lock forever-hold on hung CLI).
BG_TOOL_TIMEOUT_SEC = 300

# System events — pushed to frontend via /api/system/events
_system_events: list[dict] = []


def _emit_event(event_type: str, message: str):
    """Record a system event. Keeps last 50."""
    _system_events.append({
        "type": event_type,
        "message": message,
        "time": time.strftime("%H:%M:%S"),
    })
    if len(_system_events) > 50:
        _system_events.pop(0)


def get_system_events() -> list[dict]:
    return list(_system_events)


def _track_tools(sp: "SessionProcess", event: dict, cid: str):
    """Inspect assistant/user events, update sp._bg_tools counters.
    Called from the persistent reader task (hot path — no I/O)."""
    et = event.get("type", "")
    if et == "assistant":
        for b in event.get("message", {}).get("content", []):
            if b.get("type") == "tool_use":
                inp = b.get("input", {})
                if isinstance(inp, dict) and inp.get("run_in_background"):
                    tid = b.get("id", "")
                    if tid:
                        sp._bg_tools[tid] = 0
                        logger.info("[Session %s] bg-tool detected — name=%s id=%s",
                                    cid, b.get("name", "?"), tid[:16])

    elif et == "user":
        for b in event.get("message", {}).get("content", []):
            if b.get("type") == "tool_result":
                tid = b.get("tool_use_id", "")
                if tid and tid in sp._bg_tools:
                    sp._bg_tools[tid] += 1
                    n = sp._bg_tools[tid]
                    logger.info("[Session %s] bg-tool result #%s — id=%s",
                                cid, n, tid[:16])
                    if n >= BG_TOOL_RESULT_THRESHOLD:
                        del sp._bg_tools[tid]
                        # Annotate event so send_message() can yield agent_result
                        event["_bg_completed"] = True
                        event["_bg_tool_id"] = tid
                        logger.info("[Session %s] bg-tool completed — id=%s",
                                    cid, tid[:16])

    # result(error): force-remove associated bg tools so send_message() can exit
    elif et == "result" and event.get("subtype") == "error":
        if sp._bg_tools:
            logger.warning("[Session %s] result(error) — force-clearing %s bg tools",
                           cid, len(sp._bg_tools))
            sp._bg_tools.clear()


def _idle_seconds() -> float:
    """Read idle timeout from config (0 = never reap)."""
    t = config.SESSION_IDLE_TIMEOUT_MINUTES
    return float(t * 60) if t > 0 else float("inf")


# ════════════════════════════════════════════
# Env helper
# ════════════════════════════════════════════

def _build_env() -> dict:
    """Clone os.environ and fix missing CLAUDE_PLUGIN_ROOT."""
    env = {**os.environ, "GATEWAY_MODE": "1"}
    if not env.get("CLAUDE_PLUGIN_ROOT"):
        for candidate in [os.path.expanduser("~/.claude"), os.path.expanduser("~/.claude-code")]:
            if Path(candidate).exists():
                env["CLAUDE_PLUGIN_ROOT"] = candidate
                break
        if not env.get("CLAUDE_PLUGIN_ROOT"):
            env["CLAUDE_PLUGIN_ROOT"] = str(Path.home() / ".claude")
    return env


# ════════════════════════════════════════════
# SessionProcess — one long-lived claude
# ════════════════════════════════════════════

class SessionProcess:
    """Wraps a persistent claude subprocess for one conversation."""

    def __init__(self, conv_id: str):
        self.conv_id = conv_id
        self.process = None       # asyncio.subprocess.Process
        self.session_id: Optional[str] = None
        self.last_activity = 0.0
        self._stderr_task = None
        self._send_lock = asyncio.Lock()   # serialises send_message() calls
        self._alive = False
        self._killed = False
        # ── Persistent reader ──────────────────
        self._reader_task: Optional[asyncio.Task] = None
        self._event_queue: asyncio.Queue = asyncio.Queue(maxsize=EVENT_QUEUE_MAXSIZE)
        self._bg_tools: dict[str, int] = {}  # {tool_use_id: result_count}
        # ── Interrupt support ──────────────────
        self._interrupt_flag = False
        self._interrupt_prompt: Optional[str] = None

    # ── lifecycle ──────────────────────────

    async def start(self, claude_session_id: Optional[str] = None):
        """Spawn claude. Resumes existing session if claude_session_id is set."""
        env = _build_env()
        args = [
            CLAUDE_BIN,
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--effort", CLAUDE_EFFORT,
            "--permission-mode", "bypassPermissions",
        ]
        if claude_session_id:
            args.extend(["--resume", claude_session_id])

        tag = f"resume {claude_session_id[:12]}" if claude_session_id else "fresh"
        logger.info(f"[Session {self.conv_id[:8]}] Starting ({tag})")

        try:
            self.process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=CLAUDE_CWD,
                env=env,
            )
            # Increase stdout buffer limit from default 64KB to 50MB.
            # Claude stream-json lines can be HUGE when tool_results contain
            # base64-encoded images or large file reads.
            if self.process.stdout:
                self.process.stdout._limit = 50 * 1024 * 1024  # 50 MB
        except Exception as e:
            logger.error(f"[Session {self.conv_id[:8]}] Spawn failed: {e}")
            raise

        self._alive = True
        self._killed = False
        self._start_stderr_reader()
        self._start_reader()
        self.last_activity = time.time()

    async def close(self):
        """Kill the process and clean up resources."""
        if self._killed:
            return
        self._killed = True
        self._alive = False

        # Cancel reader task first — stops consuming stdout
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass

        # Drain event queue (prevent GC warnings about unread items)
        while not self._event_queue.empty():
            try:
                self._event_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        if self._stderr_task and not self._stderr_task.done():
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except (asyncio.CancelledError, Exception):
                pass

        if self.process:
            try:
                if self.process.stdin:
                    self.process.stdin.close()
            except Exception:
                pass
            try:
                self.process.kill()
                await self.process.wait()
            except Exception:
                pass

        sid = str(self.session_id)[:12] if self.session_id else "none"
        logger.info(f"[Session {self.conv_id[:8]}] Closed (sid={sid})")

    # ── persistent stdout reader ─────────

    def _start_reader(self):
        """Launch a background task that reads every line from stdout,
        parses NDJSON events, tracks background tool_use/tool_result pairs,
        and pushes events into _event_queue.

        Runs until the process dies or close() cancels it.
        """
        cid = self.conv_id[:8]

        async def _read_stdout():
            logger.info("[Session %s] reader-started", cid)
            try:
                while self._alive and self.process and self.process.stdout:
                    line = await self.process.stdout.readline()
                    if not line:
                        rc = self.process.returncode
                        logger.info("[Session %s] reader-eof — process exit code=%s, queue had %s events",
                                    cid, rc, self._event_queue.qsize())
                        try:
                            self._event_queue.put_nowait(_ReaderError(
                                f"CLI process exited (rc={rc})"))
                        except asyncio.QueueFull:
                            pass
                        break

                    line_str = line.decode("utf-8", errors="replace").strip()
                    if not line_str:
                        continue

                    # Console mirror
                    if config.CONSOLE_MIRROR:
                        try:
                            print(f"\033[90m{ANSI_RE.sub('', line_str)[:200]}\033[0m", flush=True)
                        except Exception:
                            pass

                    # Parse JSON event
                    try:
                        event = json.loads(line_str)
                    except json.JSONDecodeError:
                        continue

                    # ── Track tool_use / tool_result ──────
                    _track_tools(self, event, cid)

                    # Push to queue (non-blocking — drop oldest on full)
                    try:
                        self._event_queue.put_nowait(event)
                    except asyncio.QueueFull:
                        # Safety valve — discard oldest, keep newest
                        try:
                            self._event_queue.get_nowait()
                            self._event_queue.put_nowait(event)
                        except (asyncio.QueueFull, asyncio.QueueEmpty):
                            pass  # best-effort; consumer is too slow
                        logger.warning("[Session %s] queue-full — dropped oldest event (%s/%s)",
                                       cid, self._event_queue.qsize(), EVENT_QUEUE_MAXSIZE)

            except asyncio.CancelledError:
                logger.info("[Session %s] reader-cancelled — %s events unread", cid, self._event_queue.qsize())
            except Exception as e:
                logger.error("[Session %s] reader-error: %s: %s", cid, type(e).__name__, e)
                try:
                    self._event_queue.put_nowait(_ReaderError(str(e)))
                except asyncio.QueueFull:
                    pass

        self._reader_task = asyncio.create_task(_read_stdout())

    # ── stderr drain ──────────────────────

    def _start_stderr_reader(self):
        async def _read():
            try:
                while self._alive and self.process and self.process.stderr:
                    line = await self.process.stderr.readline()
                    if not line:
                        break
                    txt = line.decode("utf-8", errors="replace").strip()
                    if txt:
                        logger.debug(f"[Session {self.conv_id[:8]}] stderr: {txt[:200]}")
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"[Session {self.conv_id[:8]}] stderr reader: {e}")
        self._stderr_task = asyncio.create_task(_read())

    # ── interrupt ──────────────────────────

    def interrupt(self, new_prompt: str):
        """Signal the current send_message() to interrupt Claude and inject a
        new prompt.  Callable from any async context — the flag is checked
        inside send_message()'s event loop."""
        self._interrupt_prompt = new_prompt
        self._interrupt_flag = True
        logger.info("[Session %s] interrupt-requested — prompt=%s",
                    self.conv_id[:8], new_prompt[:60])

    # ── send message (one at a time) ──────

    async def send_message(
        self, prompt: str, show_thinking: bool = True
    ) -> AsyncGenerator[dict, None]:
        """Inject a user message via stdin and consume events from the
        persistent _event_queue until ALL background tool calls resolve.

        The queue is fed by _reader_task (started in start()) — send_message
        no longer reads stdout directly.
        """
        async with self._send_lock:
            if not self._alive or not self.process or self.process.returncode is not None:
                rc = self.process.returncode if self.process else "?"
                raise RuntimeError(f"Session process dead (rc={rc})")

            self.last_activity = time.time()

            # ── Write prompt to stdin ─────────────────────
            payload = json.dumps({
                "type": "user",
                "message": {"role": "user", "content": prompt}
            }, ensure_ascii=False) + "\n"

            try:
                self.process.stdin.write(payload.encode("utf-8"))
                await self.process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError) as e:
                self._alive = False
                raise RuntimeError(f"stdin write failed: {e}")

            logger.info("[Session %s] Send: %s", self.conv_id[:8], prompt[:80])

            thinking_buf = ""
            text_buf = ""
            fallback = []
            turn_start = time.time()

            try:
                while True:
                    # ── Read next event from queue (with timeout) ──
                    try:
                        event = await asyncio.wait_for(
                            self._event_queue.get(), timeout=BG_TOOL_TIMEOUT_SEC)
                    except asyncio.TimeoutError:
                        elapsed = time.time() - turn_start
                        n_bg = len(self._bg_tools)
                        logger.error(
                            "[Session %s] bg-wait timeout — %s tools abandoned after %.0fs: %s",
                            self.conv_id[:8], n_bg, elapsed,
                            [tid[:16] for tid in self._bg_tools])
                        self._bg_tools.clear()
                        break

                    # ── Reader died → propagate error ──────
                    if isinstance(event, _ReaderError):
                        self._alive = False
                        raise RuntimeError(f"CLI reader died: {event.reason}")

                    et = event.get("type", "")

                    # ── system/init → capture session_id
                    if et == "system" and event.get("subtype") == "init":
                        sid = event.get("session_id", "")
                        if sid:
                            self.session_id = sid
                            self.last_activity = time.time()
                            yield {"type": "session_id", "content": sid}

                    # ── assistant → text / thinking / tool_use
                    elif et == "assistant":
                        for b in event.get("message", {}).get("content", []):
                            bt = b.get("type", "")
                            if bt == "text":
                                t = b.get("text", "")
                                text_buf += t
                                yield {"type": "text", "content": t}
                            elif bt == "thinking":
                                t = b.get("thinking", "")
                                thinking_buf += t
                                if show_thinking:
                                    yield {"type": "thinking", "content": t}
                            elif bt == "tool_use":
                                name = b.get("name", "?")
                                inp = json.dumps(b.get("input", {}), ensure_ascii=False)[:120]
                                yield {"type": "thinking", "content": f"\n> 🔧 {name}: {inp}\n"}
                                yield {"type": "status", "tool": name}

                    # ── user → tool_result / agent_result
                    elif et == "user":
                        if event.get("_bg_completed"):
                            # Background agent completed → agent_result fold
                            tid = event.get("_bg_tool_id", "")
                            agent_content = ""
                            for b in event.get("message", {}).get("content", []):
                                if b.get("type") == "tool_result":
                                    c = b.get("content", "")
                                    if isinstance(c, list):
                                        c = c[0].get("text", "") if c else ""
                                    agent_content = str(c)
                            logger.info("[Session %s] agent-result — agent=%s len=%s",
                                        self.conv_id[:8], tid[:16], len(agent_content))
                            yield {"type": "agent_result",
                                   "tool_id": tid,
                                   "content": agent_content}
                        else:
                            for b in event.get("message", {}).get("content", []):
                                if b.get("type") == "tool_result":
                                    c = b.get("content", "")
                                    if isinstance(c, list):
                                        c = c[0].get("text", "") if c else ""
                                    yield {"type": "thinking", "content": f"> ✅ {str(c)[:200]}\n"}
                                    yield {"type": "status", "tool": "", "state": "done"}

                    # ── result → check if turn is truly done ──
                    elif et == "result":
                        u = event.get("usage", {})
                        logger.info(
                            "[Session %s] result — subtype=%s usage_keys=%s",
                            self.conv_id[:8], event.get("subtype", "?"),
                            list(u.keys()) if u else "NONE")
                        if u:
                            yield {"type": "usage", "input": u.get("input_tokens", 0),
                                   "output": u.get("output_tokens", 0)}
                        # Only break when NO background tools are still pending
                        if not self._bg_tools:
                            logger.debug(
                                "[Session %s] turn complete — thinking:%s text:%s elapsed:%.0fs",
                                self.conv_id[:8], len(thinking_buf), len(text_buf),
                                time.time() - turn_start)
                            break
                        logger.info(
                            "[Session %s] turn-extended — %s bg tools pending, continuing",
                            self.conv_id[:8], len(self._bg_tools))
                        # continue reading — bg tools still outstanding

                    # ── error
                    elif et == "error":
                        err_msg = event.get("error", {}).get("message", str(event.get("error", "?")))
                        logger.error("[Session %s] Claude error: %s",
                                     self.conv_id[:8], err_msg[:200])
                        yield {"type": "error", "content": err_msg}

                    # ── Interrupt check (after each event) ──
                    if self._interrupt_flag and self._interrupt_prompt:
                        await self._handle_interrupt()
                        # After interrupt, continue loop — new events will
                        # arrive from the injected prompt via the queue.

            except asyncio.CancelledError:
                logger.warning("[Session %s] Turn cancelled by client", self.conv_id[:8])
                raise

            # Fallback: no structured text but have plain output
            if not text_buf and fallback:
                fb = "\n".join(fallback).strip()
                if fb:
                    yield {"type": "text", "content": fb}

            self.last_activity = time.time()

    # ── interrupt handler ─────────────────

    async def _handle_interrupt(self):
        """Called inside send_message()'s event loop when _interrupt_flag is set.
        Sends SIGINT to CLI, drains stale events, writes the new prompt,
        and resets the flag."""
        prompt = self._interrupt_prompt
        self._interrupt_flag = False
        self._interrupt_prompt = None

        if not prompt:
            return

        cid = self.conv_id[:8]
        logger.info("[Session %s] interrupt-sent — user interrupted generation", cid)

        # Send SIGINT to interrupt current generation
        try:
            if self.process and self.process.returncode is None:
                self.process.send_signal(signal.SIGINT)
        except Exception as e:
            logger.warning("[Session %s] SIGINT failed: %s", cid, e)

        # Drain stale events from queue until we hit a result (from the
        # cancelled generation).  Short timeout so we don't block forever.
        drained = 0
        while True:
            try:
                event = await asyncio.wait_for(self._event_queue.get(), timeout=3.0)
                drained += 1
                if isinstance(event, dict) and event.get("type") == "result":
                    break
            except asyncio.TimeoutError:
                logger.warning("[Session %s] interrupt drain timeout after %s events", cid, drained)
                break

        logger.info("[Session %s] interrupt drain — %s events flushed", cid, drained)

        # Write new prompt
        payload = json.dumps({
            "type": "user",
            "message": {"role": "user", "content": prompt}
        }, ensure_ascii=False) + "\n"

        try:
            self.process.stdin.write(payload.encode("utf-8"))
            await self.process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as e:
            self._alive = False
            raise RuntimeError(f"stdin write failed during interrupt: {e}")

        logger.info("[Session %s] interrupt — new prompt injected (%schars)", cid, len(prompt))

    # ── helpers ───────────────────────────

    @property
    def alive(self) -> bool:
        return self._alive and self.process is not None and self.process.returncode is None

    def is_idle(self) -> bool:
        limit = _idle_seconds()
        if limit == float("inf"):
            return False
        return time.time() - self.last_activity > limit


# ════════════════════════════════════════════
# SessionManager — process pool
# ════════════════════════════════════════════

class SessionManager:
    """Pool of persistent claude sessions keyed by conversation_id.

    Usage:
        mgr = get_session_manager()
        await mgr.start_cleanup()         # call once on startup
        sp = await mgr.get_or_create(conv_id, claude_sid)
        async for event in sp.send_message(prompt):
            ...
        # On shutdown:
        await mgr.close_all()
    """

    def __init__(self):
        self._sessions: Dict[str, SessionProcess] = {}
        self._cleanup_task = None

    async def start_cleanup(self):
        """Background loop that reaps idle sessions every 60s."""
        async def _loop():
            while True:
                await asyncio.sleep(60)
                try:
                    idle = [cid for cid, sp in self._sessions.items() if sp.is_idle()]
                    for cid in idle:
                        sp = self._sessions.pop(cid, None)
                        if sp:
                            logger.info(f"[Pool] Reaping idle session {cid[:8]}")
                            _emit_event("session_killed", f"闲置超时，进程 {cid[:8]} 已回收")
                            await sp.close()
                except Exception as e:
                    logger.error(f"[Pool] Cleanup error: {e}")

        self._cleanup_task = asyncio.create_task(_loop())
        logger.info(f"[Pool] Cleanup task started (idle timeout: {config.SESSION_IDLE_TIMEOUT_MINUTES}m)")

    async def get_or_create(
        self, conv_id: str, claude_session_id: Optional[str] = None
    ) -> SessionProcess:
        """Return existing live session or spawn a new one.

        Dead/crashed sessions are automatically purged and recreated.
        """
        # Purge dead entries first
        stale = []
        for cid, sp in self._sessions.items():
            if not sp.alive:
                stale.append(cid)
        for cid in stale:
            logger.warning(f"[Pool] Purging dead session {cid[:8]}")
            sp = self._sessions.pop(cid, None)
            if sp:
                try:
                    await sp.close()
                except Exception:
                    pass

        # Reuse or create
        if conv_id in self._sessions:
            sp = self._sessions[conv_id]
            logger.debug(f"[Pool] Reusing session {conv_id[:8]} (sid={str(sp.session_id)[:12]})")
            return sp

        sp = SessionProcess(conv_id)
        await sp.start(claude_session_id)
        # Wait briefly for init event (session_id)
        self._sessions[conv_id] = sp
        logger.info(
            f"[Pool] Created session {conv_id[:8]} "
            f"(total: {len(self._sessions)}, resume={'yes' if claude_session_id else 'no'})"
        )
        return sp

    async def close_session(self, conv_id: str):
        """Explicitly close and remove a session."""
        sp = self._sessions.pop(conv_id, None)
        if sp:
            await sp.close()

    async def close_all(self):
        """Kill all sessions. Called on server shutdown."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
        logger.info(f"[Pool] Shutting down {len(self._sessions)} sessions...")
        for sp in list(self._sessions.values()):
            await sp.close()
        self._sessions.clear()
        logger.info("[Pool] All sessions closed")

    def stats(self) -> dict:
        """Return pool stats for debugging / health endpoint."""
        return {
            "total": len(self._sessions),
            "alive": sum(1 for sp in self._sessions.values() if sp.alive),
            "sessions": [
                {
                    "conv_id": cid[:12],
                    "session_id": str(sp.session_id)[:12] if sp.session_id else "pending",
                    "idle_sec": round(time.time() - sp.last_activity, 1),
                }
                for cid, sp in self._sessions.items()
            ],
        }


# ════════════════════════════════════════════
# Global singleton
# ════════════════════════════════════════════

_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager


# ════════════════════════════════════════════
# Public API (used by chat.py)
# ════════════════════════════════════════════

async def stream_chat(
    messages: list[dict],
    show_thinking: bool = True,
    system_prompt: Optional[str] = None,
    conv_id: Optional[str] = None,
    claude_session_id: Optional[str] = None,
) -> AsyncGenerator[dict, None]:
    """Entry point for chat.py — delegates to the persistent session pool.

    Signature kept backward-compatible with the old one-shot stream_chat.
    """
    if not conv_id:
        conv_id = "default"

    prompt = _extract_message(messages)
    if system_prompt:
        prompt = f"{system_prompt}\n\n{prompt}"

    # Gateway context — injected once per conversation start
    if not messages or len(messages) <= 2:
        gateway_ctx = (
            "[System] You are running inside **Claude Gateway** — a web-based remote terminal for Claude Code. "
            "The user is on a phone/tablet via PWA. They type in Chinese. "
            "You have full tool access (Read, Write, Bash, etc). "
            "The user cannot see your terminal — be concise and helpful.\n\n"
            "## Gateway Features You Can Use\n\n"
            "### Sending files to the user\n"
            "- `[FILE:filename.ext]` — Smart file link. Images (.png/.jpg/.gif/.webp/.bmp) display as inline thumbnails. "
            "All other files show a download card.\n"
            "- `[DOWNLOAD:filename.ext]` — Always shows a download card (use when you want to force download).\n"
            "- **Before using these tags:** save the file to the FILE_ROOT_DIR first (use Bash: `cp`, `mv`, or write directly). "
            "The file must already exist there.\n\n"
            "### User file uploads\n"
            "- When the user uploads a file through the PWA, you'll see a system message: `[用户上传了: xxx, 路径: /path/to/file]`\n"
            "- For images: use the ollama-vision skill or Read the file\n"
            "- For code/text: Read the file directly\n\n"
            "### Screenshots & webcam\n"
            "- Take screenshots with PowerShell or ffmpeg, save to FILE_ROOT_DIR, then use [FILE:xxx] to show the user\n"
            "- Webcam: `ffmpeg -f dshow -i video=\"Integrated Camera\" -frames:v 1 FILE_ROOT_DIR/photo.jpg`\n\n"
            "### Slash commands (intercepted by server, NOT sent to you)\n"
            "- `/help` `/status` `/model` `/effort` `/compact` `/clear` `/stop` — handled by the Gateway server"
        )
        prompt = gateway_ctx + "\n\n" + prompt

    mgr = get_session_manager()

    try:
        sp = await mgr.get_or_create(conv_id, claude_session_id)
    except Exception as e:
        logger.error(f"[stream_chat] Failed to get session for {conv_id[:8]}: {e}")
        yield {"type": "error", "content": str(e)}
        return

    try:
        async for event in sp.send_message(prompt, show_thinking=show_thinking):
            yield event
    except (RuntimeError, OSError) as e:
        # Process crashed or stream overflowed (e.g. LimitOverrunError from
        # asyncio readline when a stream-json line exceeds buffer limit).
        # Kill the broken process and resume from the saved session-id.
        logger.error(
            f"[stream_chat] Session {conv_id[:8]} broken: {type(e).__name__}: {e}. "
            f"Attempting recovery..."
        )
        sid = sp.session_id  # save before close
        await mgr.close_session(conv_id)
        try:
            sp = await mgr.get_or_create(conv_id, sid)  # resume with saved sid
            async for event in sp.send_message(prompt, show_thinking=show_thinking):
                yield event
        except Exception as e2:
            logger.error(f"[stream_chat] Recovery failed for {conv_id[:8]}: {e2}")
            yield {"type": "error", "content": str(e2)}


def _extract_message(messages: list[dict]) -> str:
    if not messages:
        return ""
    last = messages[-1].get("content", "")
    if isinstance(last, list):
        last = " ".join(p.get("text", "") for p in last if p.get("type") == "text")
    return str(last)


async def build_messages_for_claude(history, msg, files=None):
    """Build message list. Prepend file upload notices with paths."""
    msgs = list(history)
    if files:
        ctx = [f"[用户上传了: {f.get('name','file')}，路径: {f.get('text','')}]" for f in files]
        has_image = any(
            f['name'].lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'))
            for f in files
        )
        if has_image:
            ctx.append("[提示] 图片文件请用 Bash: python .claude/skills/ollama-vision/ocr.py <路径> 读取")
        msg = "\n".join(ctx + [msg])
    msgs.append({"role": "user", "content": msg})
    return msgs
