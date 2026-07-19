"""Chat API — SSE streaming backed by StreamingStore state machine.

Thin route handler (~90 lines).  Slash commands → chat_commands.py.
Drain task → chat_drain.py.
"""
import json
import asyncio
from fastapi import APIRouter, Request, Depends
from fastapi.responses import StreamingResponse
from api.auth import verify_token
from api.chat_commands import handle_command, sse_reply
from api.chat_drain import drain_to_completion, write_chunk_to_memory
from services.claude_client import stream_chat, build_messages_for_claude, get_session_manager
from services.streaming import StreamingStore
from db.store import (
    create_conversation, get_conversation, get_messages, save_message,
    touch_conversation, update_conversation_title, save_claude_session_id,
    get_file_record, init_streaming_msg,
)
from db.models import Message
from logger import logger

router = APIRouter(tags=["chat"], dependencies=[Depends(verify_token)])


# ── Helpers ────────────────────────────────────────────────────

async def _save_sid_safe(conv_id: str, claude_sid: str):
    """Fire-and-forget — save claude session ID without blocking SSE."""
    try:
        await save_claude_session_id(conv_id, claude_sid)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════
# POST /api/chat
# ═══════════════════════════════════════════════════════════════

@router.post("/chat")
async def chat(request: Request, body: dict):
    """POST /api/chat — SSE streaming via persistent Claude process pool."""
    user_message = body.get("message", "").strip()
    if not user_message:
        return StreamingResponse(
            iter(["data: {\"type\":\"error\",\"content\":\"Empty message\"}\n\n"]),
            media_type="text/event-stream",
        )

    # Command interception
    if user_message.startswith("/"):
        cmd_result = await handle_command(user_message, body.get("conversation_id"))
        return StreamingResponse(
            sse_reply(cmd_result), media_type="text/event-stream"
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

    # Resolve file_ids
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

    # Get stored Claude session ID for --resume
    conv_obj = await get_conversation(conv_id)
    claude_sid = conv_obj.claude_session_id if conv_obj else None

    # Create DB placeholder + memory session
    msg_id = await init_streaming_msg(conv_id)
    streaming = await StreamingStore.create(conv_id, msg_id)

    # ═══════════════════════════════════════════════════════════
    # SSE event generator
    # ═══════════════════════════════════════════════════════════

    async def event_generator():
        nonlocal claude_sid
        finalized = False

        # reader_fn: independent Task reading Claude stdout
        agen = stream_chat(claude_messages, show_thinking=show_thinking,
                          conv_id=conv_id, claude_session_id=claude_sid).__aiter__()
        chunk_queue: asyncio.Queue = asyncio.Queue()

        async def reader_fn():
            try:
                while True:
                    try:
                        chunk = await agen.__anext__()
                    except StopAsyncIteration:
                        break
                    if chunk.get("type") == "error":
                        await chunk_queue.put(chunk)
                        break
                    await chunk_queue.put(chunk)
            except (asyncio.CancelledError, Exception) as e:
                logger.error("[Chat] Reader error conv=%s: %s: %s",
                             conv_id[:8], type(e).__name__, e)
            finally:
                try:
                    await chunk_queue.put(None)  # sentinel
                except (asyncio.CancelledError, Exception):
                    logger.warning("[Chat] Reader sentinel blocked conv=%s", conv_id[:8])

        # Background DB sync (~1 Hz)
        db_sync_running = True

        async def db_sync_loop():
            while db_sync_running:
                await asyncio.sleep(1)
                try:
                    await StreamingStore.sync_to_db(conv_id)
                except (asyncio.CancelledError, Exception) as e:
                    logger.error("[Chat] DB sync error conv=%s: %s", conv_id[:8], e)

        db_sync_task = asyncio.create_task(db_sync_loop())
        reader_handle = asyncio.create_task(reader_fn())

        # ═══════════════════════════════════════════════════════
        # SSE main loop
        # ═══════════════════════════════════════════════════════
        disconnected = False
        drained = False

        try:
            try:
                while True:
                    chunk = await chunk_queue.get()
                    if chunk is None:          # reader sentinel — normal end
                        drained = True
                        break
                    if chunk.get("type") == "error":
                        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                        drained = True
                        break

                    # Write memory (sync, always first)
                    claude_sid = write_chunk_to_memory(chunk, streaming, claude_sid)
                    if chunk.get("type") == "session_id":
                        asyncio.create_task(_save_sid_safe(conv_id, claude_sid))

                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

            except (asyncio.CancelledError, GeneratorExit):
                logger.warning("[Chat] SSE DISCONNECTED conv=%s msg=%s status=%s",
                               conv_id[:8], msg_id, streaming.status.value)
                disconnected = True
                streaming.mark_draining()

            except Exception as e:
                logger.error("[Chat] SSE ERROR conv=%s: %s", conv_id[:8], e)
                yield f"data: {json.dumps({'type':'error','content':str(e)}, ensure_ascii=False)}\n\n"

            # ═══════════════════════════════════════════════════
            # Post-loop: drain (disconnect) or normal completion
            # ═══════════════════════════════════════════════════

            if disconnected and not drained:
                logger.info("[Chat] SPAWNING DrainTask conv=%s msg=%s",
                            conv_id[:8], msg_id)
                asyncio.create_task(
                    drain_to_completion(conv_id, msg_id, streaming,
                                        chunk_queue, reader_handle)
                )
                finalized = True
                return

            # Normal completion
            if not reader_handle.done():
                try:
                    await reader_handle
                except (asyncio.CancelledError, Exception) as e:
                    logger.warning("[Chat] await reader_handle failed conv=%s: %s",
                                   conv_id[:8], e)

            await StreamingStore.finalize(conv_id, msg_id)
            finalized = True
            logger.info("[Chat] FINALIZED (normal) conv=%s msg=%s",
                        conv_id[:8], msg_id)
            await touch_conversation(conv_id)
            try:
                done = {"type": "done", "conversation_id": conv_id}
                if streaming.usage:
                    done["usage"] = streaming.usage
                yield f"data: {json.dumps(done, ensure_ascii=False)}\n\n"
            except Exception:
                pass

        finally:
            # Sync-only cleanup (no await — avoids CancelledError in finally)
            db_sync_running = False
            if db_sync_task and not db_sync_task.done():
                db_sync_task.cancel()

            if not finalized:
                logger.warning("[Chat] FINALIZE IN FINALLY conv=%s msg=%s — force-pop",
                               conv_id[:8], msg_id)
                if reader_handle and not reader_handle.done():
                    try:
                        reader_handle.cancel()
                    except Exception:
                        pass
                StreamingStore._sessions.pop(conv_id, None)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ═══════════════════════════════════════════════════════════════
# POST /api/chat/interrupt — 打断当前生成，注入新 prompt
# ═══════════════════════════════════════════════════════════════

@router.post("/chat/interrupt")
async def chat_interrupt(request: Request, body: dict):
    """Send SIGINT to the CLI process for this conversation, drain stale
    output, and inject a new user prompt.  The existing SSE connection
    picks up the new response automatically."""
    user_message = body.get("message", "").strip()
    conv_id = body.get("conversation_id", "")
    if not user_message or not conv_id:
        return {"status": "error", "message": "message and conversation_id required"}

    mgr = get_session_manager()
    sp = mgr._sessions.get(conv_id)
    if not sp or not sp.alive:
        logger.warning("[Chat] interrupt conv=%s — no active session", conv_id[:8])
        return {"status": "error", "message": "No active session for this conversation"}

    # Save user message to DB
    try:
        from db.store import save_message, touch_conversation
        from db.models import Message
        user_msg = Message(conversation_id=conv_id, role="user",
                          content=user_message)
        await save_message(user_msg)
        await touch_conversation(conv_id)
    except Exception as e:
        logger.error("[Chat] interrupt — failed to save user msg: %s", e)

    sp.interrupt(user_message)
    logger.info("[Chat] interrupt conv=%s — SIGINT sent, new prompt injected", conv_id[:8])
    return {"status": "ok", "message": "Interrupt sent"}
