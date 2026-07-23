"""Update API routes — check for updates, apply updates."""
from fastapi import APIRouter, Depends, HTTPException
from api.auth import verify_token
from services.update import check, apply
from logger import logger

router = APIRouter(tags=["update"], dependencies=[Depends(verify_token)])


@router.get("/system/update-check")
async def update_check():
    """Check GitHub Releases for a newer version."""
    try:
        info = check()
        if info.get("error"):
            return {"error": info["error"], "current": info.get("current", "")}
        return info
    except Exception as e:
        logger.error("[Update] check failed: %s", e)
        return {"error": "network", "current": ""}


@router.post("/system/update-apply")
async def update_apply():
    """Download and install the latest version, then restart."""
    try:
        result = apply()
        logger.info("[Update] Applied — version=%s overwritten=%s",
                    result.get("version"), result.get("overwritten"))
        return result
    except RuntimeError as e:
        logger.error("[Update] apply failed: %s", e)
        raise HTTPException(status_code=500, detail={"error": str(e), "code": "UPDATE_FAILED"})
    except Exception as e:
        logger.error("[Update] apply unexpected: %s", e)
        raise HTTPException(status_code=500, detail={"error": str(e), "code": "UPDATE_FAILED"})
