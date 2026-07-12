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
import time
from pathlib import Path
from typing import AsyncGenerator, Dict, Optional

from logger import logger
import config

CLAUDE_CWD = os.getenv("CLAUDE_CWD", str(Path.home()))
CLAUDE_BIN = shutil.which("claude") or shutil.which("claude.cmd") or "claude"
CLAUDE_EFFORT = os.getenv("CLAUDE_EFFORT", "high")
ANSI_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07')

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
        self._lock = asyncio.Lock()
        self._alive = False
        self._killed = False

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
        self.last_activity = time.time()

    async def close(self):
        """Kill the process and clean up resources."""
        if self._killed:
            return
        self._killed = True
        self._alive = False

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

    # ── send message (one at a time) ──────

    async def send_message(
        self, prompt: str, show_thinking: bool = True
    ) -> AsyncGenerator[dict, None]:
        """Inject a user message via stdin and yield stdout events until turn ends.

        The lock ensures only one send is in-flight per session.
        """
        async with self._lock:
            if not self._alive or not self.process or self.process.returncode is not None:
                rc = self.process.returncode if self.process else "?"
                raise RuntimeError(f"Session process dead (rc={rc})")

            self.last_activity = time.time()

            # Write NDJSON to stdin
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

            logger.info(f"[Session {self.conv_id[:8]}] Send: {prompt[:80]}")

            thinking_buf = ""
            text_buf = ""
            fallback = []

            try:
                while True:
                    line = await self.process.stdout.readline()
                    if not line:
                        logger.warning(f"[Session {self.conv_id[:8]}] stdout EOF — process likely crashed")
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
                        fallback.append(ANSI_RE.sub('', line_str))
                        continue

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

                    # ── user → tool_result
                    elif et == "user":
                        for b in event.get("message", {}).get("content", []):
                            if b.get("type") == "tool_result":
                                c = b.get("content", "")
                                if isinstance(c, list):
                                    c = c[0].get("text", "") if c else ""
                                yield {"type": "thinking", "content": f"> ✅ {str(c)[:200]}\n"}
                                yield {"type": "status", "tool": "", "state": "done"}

                    # ── result → turn boundary (BREAK)
                    elif et == "result":
                        u = event.get("usage", {})
                        logger.info(
                            f"[Session {self.conv_id[:8]}] result usage keys={list(u.keys()) if u else 'NONE'} "
                            f"raw={u}"
                        )
                        if u:
                            yield {"type": "usage", "input": u.get("input_tokens", 0),
                                   "output": u.get("output_tokens", 0)}
                        logger.debug(
                            f"[Session {self.conv_id[:8]}] Turn done "
                            f"subtype={event.get('subtype','?')} "
                            f"thinking:{len(thinking_buf)} text:{len(text_buf)}"
                        )
                        break  # ← exit loop, ready for next send_message()

                    # ── error
                    elif et == "error":
                        err_msg = event.get("error", {}).get("message", str(event.get("error", "?")))
                        logger.error(f"[Session {self.conv_id[:8]}] Claude error: {err_msg[:200]}")
                        yield {"type": "error", "content": err_msg}

            except asyncio.CancelledError:
                logger.warning(f"[Session {self.conv_id[:8]}] Turn cancelled by client")
                raise

            # Fallback: no structured text but have plain output
            if not text_buf and fallback:
                fb = "\n".join(fallback).strip()
                if fb:
                    yield {"type": "text", "content": fb}

            self.last_activity = time.time()

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
