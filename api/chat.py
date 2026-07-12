"""Chat API — SSE streaming with claude -p + --continue."""
import json
import time
import asyncio
from fastapi import APIRouter, Request, Depends
from fastapi.responses import StreamingResponse
from api.auth import verify_token
from services.claude_client import stream_chat, build_messages_for_claude
from db.store import (
    create_conversation, get_conversation, get_messages, save_message,
    touch_conversation, update_conversation_title, save_claude_session_id,
    get_file_record,
)
from db.models import Message
from logger import logger

router = APIRouter(tags=["chat"], dependencies=[Depends(verify_token)])


@router.post("/chat")
async def chat(request: Request, body: dict):
    """POST /api/chat — SSE streaming via claude -p."""
    user_message = body.get("message", "").strip()
    if not user_message:
        return StreamingResponse(
            iter(["data: {\"type\":\"error\",\"content\":\"Empty message\"}\n\n"]),
            media_type="text/event-stream",
        )

    # ── Command interception ──
    if user_message.startswith("/"):
        cmd_result = await _handle_command(user_message, body.get("conversation_id"))
        return StreamingResponse(
            _sse_reply(cmd_result), media_type="text/event-stream"
        )

    conv_id = body.get("conversation_id")
    file_ids = body.get("file_ids", [])
    show_thinking = body.get("show_thinking", True)

    if not conv_id:
        conv = await create_conversation()
        conv_id = conv.id
    else:
        conv = await get_conversation(conv_id)
        if not conv:
            conv = await create_conversation()
            conv_id = conv.id

    # Save user message
    user_msg = Message(conversation_id=conv_id, role="user", content=user_message,
                       file_ids=json.dumps(file_ids) if file_ids else None)
    await save_message(user_msg)
    await touch_conversation(conv_id)

    # Auto-title
    conv_obj = await get_conversation(conv_id)
    if conv_obj and conv_obj.title == "New Chat":
        title = user_message[:30] + ("..." if len(user_message) > 30 else "")
        await update_conversation_title(conv_id, title)

    # Resolve file_ids — handle both plain UUIDs and {id, name} objects
    file_data = []
    for fid in file_ids:
        fid_str = fid if isinstance(fid, str) else fid.get("id", "")
        rec = await get_file_record(fid_str)
        if rec:
            file_data.append({"name": rec.original_name, "text": rec.stored_path})

    # Build message list
    history = await get_messages(conv_id)
    history_msgs = [{"role": m.role, "content": m.content} for m in history[:-1]]
    claude_messages = await build_messages_for_claude(
        history_msgs, user_message,
        files=file_data if file_data else None
    )

    # Get stored claude session ID for --resume
    conv_obj = await get_conversation(conv_id)
    claude_sid = conv_obj.claude_session_id if conv_obj else None

    async def event_generator():
        nonlocal claude_sid
        thinking_parts = []
        text_parts = []
        thinking_start = None
        usage = {}
        try:
            async for chunk in stream_chat(claude_messages, show_thinking=show_thinking,
                                           conv_id=conv_id, claude_session_id=claude_sid):
                if chunk.get("type") == "session_id":
                    claude_sid = chunk["content"]
                    try:
                        await save_claude_session_id(conv_id, claude_sid)
                    except Exception as e:
                        logger.error(f"[Chat] Failed to save claude session id: {e}")
                    continue
                if chunk["type"] == "usage":
                    usage = {"i": chunk["input"], "o": chunk["output"]}
                    continue
                if chunk["type"] == "error":
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                    break
                elif chunk["type"] == "thinking":
                    if thinking_start is None:
                        thinking_start = time.time()
                    thinking_parts.append(chunk["content"])
                elif chunk["type"] == "text":
                    text_parts.append(chunk["content"])
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

        except asyncio.CancelledError:
            # Client disconnected (backgrounded PWA) — save what we have
            logger.warning(f"[Chat] Client disconnected for {conv_id[:8]}, saving partial response")
        except Exception as e:
            logger.error(f"[Chat] Error: {e}")
            yield f"data: {json.dumps({'type':'error','content':str(e)}, ensure_ascii=False)}\n\n"

        # Save message — runs on both normal completion and cancellation
        thinking = "".join(thinking_parts).strip() or None
        thinking_dur = None
        thinking_wc = 0
        if thinking and thinking_start:
            dur_sec = time.time() - thinking_start
            if dur_sec >= 60:
                thinking_dur = f"{int(dur_sec // 60)}m {int(dur_sec % 60)}s"
            else:
                thinking_dur = f"{dur_sec:.1f}s"
            thinking_wc = len(thinking.split())

        full_text = "".join(text_parts).strip()

        if full_text:
            assistant_msg = Message(conversation_id=conv_id, role="assistant",
                                    content=full_text, thinking=thinking,
                                    thinking_dur=thinking_dur,
                                    thinking_wc=thinking_wc)
            if usage:
                assistant_msg.token_usage = json.dumps(usage)
            await save_message(assistant_msg)
            await touch_conversation(conv_id)

        done = {"type": "done", "conversation_id": conv_id}
        if usage:
            done["usage"] = usage
        yield f"data: {json.dumps(done, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ════════════════════════════════════════════
# Command handlers
# ════════════════════════════════════════════

def _sse_reply(text: str):
    """Yield SSE events for a plain text reply (for command responses)."""
    yield f"data: {json.dumps({'type':'text','content':text}, ensure_ascii=False)}\n\n"
    done = {"type": "done", "conversation_id": "cmd"}
    yield f"data: {json.dumps(done, ensure_ascii=False)}\n\n"


async def _handle_command(cmd: str, conv_id: str = None) -> str:
    """Route /command to handler. Returns response text."""
    parts = cmd[1:].strip().lower().split(maxsplit=1)
    name = parts[0]
    args = parts[1] if len(parts) > 1 else ""

    if name in ("help", "h", "?"):
        return (
            "**可用命令**\n\n"
            "| 命令 | 说明 |\n"
            "|------|------|\n"
            "| `/help` | 显示此帮助 |\n"
            "| `/status` | 服务器状态、进程池 |\n"
            "| `/model` | 查看当前模型 |\n"
            "| `/effort [等级]` | 查看/设置推理深度 (low/medium/high/xhigh/max) |\n"
            "| `/compact` | 压缩对话历史释放上下文 |\n"
            "| `/clear` | 清屏（前端生效） |\n"
            "| `/stop` | 停止当前生成（前端生效） |\n"
        )

    if name == "status":
        import os, time as _time
        from config import FILE_ROOT_DIR
        from services.claude_client import get_session_manager
        mgr = get_session_manager()
        pool = mgr.stats()

        lines = [
            f"**Claude Gateway 状态**\n",
            f"| 项目 | 值 |",
            f"|------|-----|",
            f"| 进程池 | 共 {pool['total']} 个 · 存活 {pool['alive']} 个 |",
            f"| 模型 | {os.environ.get('ANTHROPIC_DEFAULT_OPUS_MODEL','?')[:40]} |",
            f"| 文件目录 | {FILE_ROOT_DIR} |",
        ]
        for s in pool.get("sessions", []):
            lines.append(f"| 会话 {s['conv_id']} | sid={s['session_id']} · 闲置 {s['idle_sec']}s |")
        return "\n".join(lines)

    if name == "model":
        import os
        m = os.environ.get("ANTHROPIC_DEFAULT_OPUS_MODEL",
            os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL",
            os.environ.get("ANTHROPIC_DEFAULT_HAIKU_MODEL", "未知")))
        return f"**当前模型:** {m}\n\n可使用 CC Switch 或环境变量更改。"

    if name == "effort":
        levels = ["low", "medium", "high", "xhigh", "max"]
        if args in levels:
            # Save to .env
            from config import BASE_DIR
            env_path = BASE_DIR / ".env"
            lines = env_path.read_text(encoding="utf-8").splitlines()
            new_lines = []
            found = False
            for line in lines:
                if line.startswith("CLAUDE_EFFORT="):
                    new_lines.append(f"CLAUDE_EFFORT={args}")
                    found = True
                else:
                    new_lines.append(line)
            if not found:
                new_lines.append(f"CLAUDE_EFFORT={args}")
            env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            return (
                f"**推理深度已设为 `{args}`**\n\n"
                f"当前会话不受影响（上下文保持），下次新建对话时生效。\n"
                f"> 或输入 `/new` 开新对话立即使用 {args} 等级。"
            )
        import os
        cur = os.environ.get("CLAUDE_EFFORT", "未设置 (默认 high)")
        return (
            "**/effort — 推理深度控制**\n\n"
            f"用法: `/effort <{('|').join(levels)}>`\n"
            f"当前默认: **{cur}**\n\n"
            "设置后下次新建对话生效，不影响当前会话。"
        )

    if name == "compact":
        killed = False
        if conv_id:
            from services.claude_client import get_session_manager
            mgr = get_session_manager()
            sp = mgr._sessions.get(conv_id)
            if sp:
                logger.info(f"[Cmd] /compact — killing session {conv_id[:8]}")
                await mgr.close_session(conv_id)
                killed = True
        msg = "**`/compact` 已触发**\n\n"
        if killed:
            msg += "常驻进程已回收。下次发消息时自动 `--resume` 恢复压缩后的上下文。"
        else:
            msg += "当前无活跃进程（已回收或从未创建）。上下文已在磁盘，下次消息自动加载。"
        msg += "\n\n> 提示：恢复后首次响应会慢一些（需从磁盘加载），后续恢复秒回。"
        return msg

    if name in ("clear", "stop"):
        return f"**`/{name}` 是前端指令**，无需经过服务器。直接在聊天界面生效。"

    return f"**未知命令:** `/{name}`\n\n输入 `/help` 查看可用命令。"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
