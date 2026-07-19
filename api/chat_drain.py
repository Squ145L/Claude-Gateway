"""Drain task — continues reading Claude output after SSE client disconnects.

Runs as an independent asyncio Task so it survives the SSE generator's cancellation.
Also holds _write_chunk_to_memory which is shared with the main SSE loop in chat.py.
"""
import asyncio
from services.streaming import StreamingStore
from db.store import touch_conversation
from logger import logger


def write_chunk_to_memory(chunk: dict, streaming, claude_sid: str) -> str:
    """Write one chunk to the StreamingSession (memory only, no I/O).
    Returns the (possibly updated) claude_session_id."""
    cid = claude_sid
    t = chunk.get("type", "")
    if t == "session_id":
        cid = chunk["content"]
    elif t == "usage":
        streaming.set_usage(chunk["input"], chunk["output"])
    elif t == "thinking":
        streaming.append_thinking(chunk["content"])
    elif t == "text":
        streaming.append_text(chunk["content"])
    elif t == "agent_result":
        # Fold agent output into thinking so the frontend can render it inline
        content = chunk.get("content", "")
        streaming.append_thinking(f"\n> 🔧 Agent result:\n> {content}\n")
    return cid


async def drain_to_completion(
    conv_id: str,
    msg_id: int,
    streaming,
    chunk_queue: asyncio.Queue,
    reader_handle: asyncio.Task,
):
    """Independent task: drain the chunk queue, finalise, and clean up.

    This MUST run as a standalone asyncio.create_task() because the SSE
    generator that spawns it is already cancelled — any await inside that
    generator would be killed immediately.  An independent task has its
    own cancellation scope and can wait for Claude to produce output.
    """
    logger.info("[DrainTask] START conv=%s msg=%s status=%s",
                conv_id[:8], msg_id, streaming.status.value)
    chunk_count = 0

    try:
        while True:
            chunk = await asyncio.wait_for(chunk_queue.get(), timeout=300.0)
            if chunk is None:               # reader_fn sentinel
                logger.info("[DrainTask] COMPLETE conv=%s: %s chunks",
                            conv_id[:8], chunk_count)
                break
            if chunk.get("type") == "error":
                break
            write_chunk_to_memory(chunk, streaming, "")
            chunk_count += 1

    except asyncio.CancelledError:
        logger.warning("[DrainTask] CANCELLED conv=%s after %s chunks",
                       conv_id[:8], chunk_count)
    except asyncio.TimeoutError:
        logger.error("[DrainTask] TIMEOUT conv=%s (120s, got %s chunks)",
                     conv_id[:8], chunk_count)
    except Exception as e:
        logger.error("[DrainTask] ERROR conv=%s: %s: %s",
                     conv_id[:8], type(e).__name__, e)

    # Cancel reader if still alive
    if reader_handle and not reader_handle.done():
        reader_handle.cancel()

    # Flush + finalise (each step independent — one failure can't skip the next)
    try:
        await StreamingStore.sync_to_db_force(conv_id)
    except Exception as e:
        logger.error("[DrainTask] sync_to_db_force failed conv=%s: %s", conv_id[:8], e)

    try:
        await StreamingStore.finalize(conv_id, msg_id)
        logger.info("[DrainTask] FINALIZED conv=%s msg=%s chunks=%s",
                    conv_id[:8], msg_id, chunk_count)
    except Exception as e:
        logger.error("[DrainTask] finalize failed conv=%s: %s — force-popping",
                     conv_id[:8], e)
        StreamingStore._sessions.pop(conv_id, None)

    try:
        await touch_conversation(conv_id)
    except Exception:
        pass
