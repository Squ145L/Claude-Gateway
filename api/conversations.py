"""Conversations CRUD API."""
from fastapi import APIRouter, Depends, HTTPException
from api.auth import verify_token
from db.store import (
    list_conversations, get_conversation, get_messages,
    delete_conversation, create_conversation, update_conversation_title,
    pin_conversation, has_older_messages,
)
from services.streaming import StreamingStore
from logger import logger

router = APIRouter(tags=["conversations"], dependencies=[Depends(verify_token)])


@router.get("/conversations")
async def list_convs(limit: int = 50):
    convs = await list_conversations(limit)
    return {
        "conversations": [
            {
                "id": c.id, "title": c.title,
                "pinned": c.pinned,
                "created_at": c.created_at, "updated_at": c.updated_at,
            }
            for c in convs
        ],
    }


@router.get("/conversations/{conv_id}")
async def get_conv(conv_id: str, limit: int = 200, before: int = None):
    conv = await get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail={
            "error": "Conversation not found", "code": "NOT_FOUND",
        })
    messages = await get_messages(conv_id, limit=limit, before_id=before)
    # Filter out cancelled streaming messages
    messages = [m for m in messages if m.content != '__CANCELLED__']

    # ── Merge streaming state: in-memory is fresher than DB ──
    streaming_state = StreamingStore.get_api_state(conv_id)
    if streaming_state:
        logger.info("[Conv GET] %s: MERGING streaming state msg=%s status=%s thinking=%schars content=%schars",
                    conv_id[:8], streaming_state["msg_id"], streaming_state["status"],
                    len(streaming_state["thinking"]), len(streaming_state["content"]))
        for m in reversed(messages):
            if m.id == streaming_state["msg_id"]:
                # Override stale DB values with latest in-memory state
                if streaming_state["thinking"]:
                    m.thinking = streaming_state["thinking"]
                if streaming_state["content"]:
                    m.content = streaming_state["content"]
                break

    has_more = False
    if messages:
        has_more = await has_older_messages(conv_id, messages[0].id)
    # Diagnostic log
    last_role = messages[-1].role if messages else 'none'
    last_preview = (messages[-1].content[:60] + '...') if messages and messages[-1].content else '(empty)'
    logger.info("[Conv GET] %s: %s msgs, last=%s, preview=%s, streaming=%s",
                conv_id[:8], len(messages), last_role, last_preview,
                streaming_state["status"] if streaming_state else "none")
    return {
        "conversation": {
            "id": conv.id, "title": conv.title,
            "created_at": conv.created_at, "updated_at": conv.updated_at,
        },
        "messages": [
            {
                "id": m.id, "role": m.role, "content": m.content,
                "thinking": m.thinking,
                "thinking_dur": m.thinking_dur,
                "thinking_wc": m.thinking_wc,
                "token_usage": m.token_usage,
                "file_ids": m.file_ids,
                "created_at": m.created_at,
            }
            for m in messages
        ],
        "has_more": has_more,
        "streaming": streaming_state,  # null if no active stream
    }


@router.delete("/conversations/{conv_id}")
async def delete_conv(conv_id: str):
    conv = await get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail={
            "error": "Conversation not found", "code": "NOT_FOUND",
        })
    await delete_conversation(conv_id)
    return {"deleted": conv_id}


@router.post("/conversations")
async def new_conv(body: dict = None):
    title = body.get("title", "New Chat") if body else "New Chat"
    conv = await create_conversation(title)
    return {"id": conv.id, "title": conv.title, "created_at": conv.created_at}


@router.put("/conversations/{conv_id}/title")
async def set_title(conv_id: str, body: dict):
    title = body.get("title", "").strip()
    if not title:
        raise HTTPException(status_code=400, detail={
            "error": "Title required", "code": "BAD_REQUEST",
        })
    conv = await get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail={
            "error": "Conversation not found", "code": "NOT_FOUND",
        })
    await update_conversation_title(conv_id, title)
    return {"id": conv_id, "title": title}


@router.post("/conversations/{conv_id}/pin")
async def toggle_pin(conv_id: str):
    conv = await get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail={
            "error": "Conversation not found", "code": "NOT_FOUND",
        })
    new_pinned = 0 if conv.pinned else 1
    await pin_conversation(conv_id, bool(new_pinned))
    return {"id": conv_id, "pinned": new_pinned}
