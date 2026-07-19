"""Slash-command handlers for /chat endpoint.

Extracted from chat.py to keep the SSE handler focused on streaming logic.
All commands are self-contained — they don't touch the streaming pipeline.
"""
import json
import os
from config import BASE_DIR, FILE_ROOT_DIR
from logger import logger


def sse_reply(text: str):
    """Generate SSE events for a plain text reply (used by commands)."""
    yield f"data: {json.dumps({'type':'text','content':text}, ensure_ascii=False)}\n\n"
    done = {"type": "done", "conversation_id": "cmd"}
    yield f"data: {json.dumps(done, ensure_ascii=False)}\n\n"


async def handle_command(cmd: str, conv_id: str = None) -> str:
    """Parse and execute a slash command. Returns the reply text."""
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
        from services.claude_client import get_session_manager
        mgr = get_session_manager()
        pool = mgr.stats()

        lines = [
            "**Claude Gateway 状态**\n",
            "| 项目 | 值 |",
            "|------|-----|",
            f"| 进程池 | 共 {pool['total']} 个 · 存活 {pool['alive']} 个 |",
            f"| 模型 | {os.environ.get('ANTHROPIC_DEFAULT_OPUS_MODEL','?')[:40]} |",
            f"| 文件目录 | {FILE_ROOT_DIR} |",
        ]
        for s in pool.get("sessions", []):
            lines.append(f"| 会话 {s['conv_id']} | sid={s['session_id']} · 闲置 {s['idle_sec']}s |")
        return "\n".join(lines)

    if name == "model":
        m = os.environ.get("ANTHROPIC_DEFAULT_OPUS_MODEL",
            os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL",
            os.environ.get("ANTHROPIC_DEFAULT_HAIKU_MODEL", "未知")))
        return f"**当前模型:** {m}\n\n可使用 CC Switch 或环境变量更改。"

    if name == "effort":
        levels = ["low", "medium", "high", "xhigh", "max"]
        if args in levels:
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
                logger.info("[Cmd] /compact — killing session %s", conv_id[:8])
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
        # /stop — actually cancel active streaming session
        if name == "stop" and conv_id:
            from services.streaming import StreamingStore
            from services.claude_client import get_session_manager
            try:
                await StreamingStore.cancel(conv_id)
            except Exception:
                pass
            try:
                mgr = get_session_manager()
                sp = mgr._sessions.get(conv_id)
                if sp:
                    await mgr.close_session(conv_id)
                    logger.info("[Cmd] /stop — killed session %s", conv_id[:8])
            except Exception:
                pass
            return "**`/stop` 已执行**\n\n当前生成已停止，Claude 进程已回收。"
        return f"**`/{name}` 是前端指令**，无需经过服务器。直接在聊天界面生效。"

    return f"**未知命令:** `/{name}`\n\n输入 `/help` 查看可用命令。"
