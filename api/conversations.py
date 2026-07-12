"""Conversations CRUD API."""
from fastapi import APIRouter, Depends, HTTPException
from api.auth import verify_token
from db.store import (
    list_conversations, get_conversation, get_messages,
    delete_conversation, create_conversation, update_conversation_title,
    pin_conversation,
)

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
async def get_conv(conv_id: str):
    conv = await get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail={
            "error": "Conversation not found", "code": "NOT_FOUND",
        })
    messages = await get_messages(conv_id)
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
