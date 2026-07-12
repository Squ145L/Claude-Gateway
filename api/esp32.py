"""ESP32 watch endpoint — stub for future hardware."""
from fastapi import APIRouter, Depends, HTTPException
from api.auth import verify_token
from logger import logger

router = APIRouter(tags=["esp32"], dependencies=[Depends(verify_token)])


@router.post("/esp32/chat")
async def esp32_chat(body: dict):
    """
    POST /api/esp32/chat — simple text chat for ESP32.
    Non-streaming, plain JSON response. Designed for low-bandwidth MCU.
    """
    message = body.get("message", "").strip()
    if not message:
        raise HTTPException(status_code=400, detail={
            "error": "Empty message", "code": "BAD_REQUEST",
        })

    # Reserved: Wire up to claude_client for non-streaming responses
    logger.info(f"[ESP32] Message: {message[:50]}...")
    return {
        "reply": f"[ESP32 endpoint — stub] Received: {message[:100]}",
        "thinking": "",
    }
