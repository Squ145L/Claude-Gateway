# Claude Gateway

手机浏览器远程使用 Claude Code
通过 frp 隧道远程操控 Claude Code，支持 DeepSeek。

前提： 本机需已配置 [CC Switch] 并设置 DeepSeek 为当前模型。Gateway 本身不管理 API Key，由 CC Switch 负责模型路由。
```
浏览器 ──→ frp 隧道 ──→ 家里 Windows 电脑 :8080 ──→ Claude Code 常驻进程池 → 秒回
```
直接让Claude读这个文件https://github.com/Squ145L/Claude-Gateway/blob/main/README.md 即可开始

## 给 AI Agent：部署指南

> 以下步骤可被 AI Agent 直接执行，每步带验证命令。

### 1. 检查环境并安装依赖

```bash
python --version          # 需要 3.9+
claude --version          # Claude Code CLI 需已安装

# 安装 Python 依赖
pip install fastapi uvicorn aiosqlite python-dotenv aiohttp
```

验证：`python -c "import fastapi, uvicorn, aiosqlite, aiohttp; print('ok')"` → 输出 `ok`

### 2. 配置

```bash
copy .env.example .env      # Windows

询问用户 然后编辑 `.env`，必改项：

| 配置项 | 说明 | 示例 |
|--------|------|------|
| `AUTH_SECRET` | 随机字符串，手机端登录密钥（至少8位） | 12345678 |
| `CLAUDE_CWD` | Claude 的工作目录（项目根目录） | `E:\MyProjects` |

可选配置：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `PORT` | `8080` | 服务端口 |
| `SESSION_IDLE_TIMEOUT_MINUTES` | `30` | 进程闲置回收时间（0=永不） |
| `CLAUDE_EFFORT` | `high` | 推理深度（low/medium/high/xhigh/max） |
| `MAX_FILE_SIZE_MB` | `20` | 上传文件大小上限 |
| `FILE_TTL_HOURS` | `24` | 上传文件保存时长 |

验证：`python -c "from config import *; print(f'Port={PORT}, SecretSet={len(AUTH_SECRET)>5}')"` → 输出 `Port=8080, SecretSet=True`

### 3. 配置内网穿透（frp）

内网穿透需要用户在 frp 服务商网页操作，Agent 无法直接完成。引导用户：

1. 让用户去 **Sakurafrp**（或其他 frp 服务）注册账号，下载启动器
2. 引导用户创建 **TCP 隧道**：

| 配置项 | 值 |
|--------|-----|
| 本地 IP | `127.0.0.1` |
| 本地端口 | `8080` |
| 自动 HTTPS | 自动 |

3. 开启隧道后，让用户把隧道地址发给你
4. 浏览器打开隧道地址，看到登录页即成功

### 4. 完成上一步骤可启动

```bash
run.bat                     # Windows（自带崩溃重启守护）
# 或
python -m uvicorn main:app --host 0.0.0.0 --port 8080
```

验证：`curl http://localhost:8080/api/health` → `{"status":"ok","claude_cli":"found:...","db":"ok"}`

---

## 给用户：部署步骤

1. 让Claude读README.md
2. 确认密钥和路径是否配置（由Claude引导用户配置）
3. **自行注册 frp 服务 或 打开首次启动（sakurafrp）.bat进行引导**
   - 下载启动器，创建 TCP 隧道
   - 本地 IP：`127.0.0.1`，本地端口：`8080`，HTTPS模式：`自动`
4. **双击 `run.bat`** 启动服务（崩溃后 2 秒自动重启）
5. **手机浏览器**打开隧道地址，输入密钥，开始使用

---

## 架构

```
手机 PWA → FastAPI (:8080) ──→ Claude 子进程池
    │            │                    │
    │     StreamingStore          常驻 stdin/stdout
    │     (内存状态机)            --resume 断点恢复
    │            │
    └── SSE ────┴── SQLite (WAL)
         │              │
    后台 DB sync    conversations API
    (解耦, ~1Hz)    merge 内存覆盖 DB
```

### 核心组件

| 组件 | 文件 | 职责 |
|------|------|------|
| **StreamingStore** | `services/streaming.py` | 内存状态机，API 读内存不读 DB |
| **DrainTask** | `api/chat.py` | SSE 断开后继续读 Claude 输出，不被 Cancel 传染 |
| **SessionManager** | `services/claude_client.py` | 进程池，按对话索引，闲置回收 |
| **StreamSession** | `static/js/services/stream.js` | 客户端状态机 |

每个对话一个常驻 `claude` 进程，第一条消息创建，后续 stdin 注入，上下文在内存不重载。闲置超时自动回收，下次通过 `--resume` 恢复。

---

## 项目结构

```
claude-gateway/
├── main.py                     # FastAPI 入口 + cleanup 任务
├── config.py                   # 配置加载
├── logger.py                   # 日志滚动
├── api/
│   ├── chat.py                 # SSE 流式 + DrainTask
│   ├── chat_commands.py        # / 命令处理
│   ├── chat_drain.py           # 断连后排空
│   ├── conversations.py        # CRUD + streaming merge
│   ├── files.py                # 上传/下载/内联查看
│   ├── health.py               # 健康检查
│   ├── system.py               # 系统管理/重启/日志/余额
│   └── ratelimit.py            # 频率限制
├── services/
│   ├── claude_client.py        # Claude 进程池
│   └── streaming.py            # StreamingSession 状态机
├── db/
│   ├── models.py
│   └── store.py                # SQLite (WAL 模式)
├── static/
│   ├── index.html              # PWA 入口
│   ├── sw.js / manifest.json
│   ├── base.css / layout.css / controls.css / chat.css / overlay.css / scrollbar.css
│   └── js/
│       ├── app.js              # 入口/组装
│       ├── core/               # store / events / dom
│       ├── utils/              # html / notify
│       ├── services/           # api / stream / theme
│       ├── render/             # markdown / thinking / messages / agent
│       └── components/         # chat / sidebar / compose / settings / welcome / confirm
├── docs/
│   ├── PROJECT.md              # 编码规范
│   └── UI-STANDARDS.md         # UI 规范
├── run.bat                     # 启动（进程守护）
├── restart.bat                 # 硬重启
├── soft-restart.bat            # 优雅重启
└── clean.bat                   # 清理端口 + 缓存
```

---

## API 端点

所有 `/api/*` 需 `Authorization: Bearer <secret>` 头（下载端点支持 `?token=` 查询参数）。

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat` | SSE 流式对话 |
| GET/POST/DELETE | `/api/conversations` | 会话管理 |
| PUT | `/api/conversations/{id}/title` | 重命名 |
| POST | `/api/files/upload` | 文件上传 |
| GET | `/api/files/download/{name}?token=xxx` | 文件下载 |
| GET | `/api/files/{id}/content` | 文件内容 |
| POST | `/api/auth/verify` | 密钥验证 |
| GET | `/api/health` | 健康检查 |
| GET | `/api/system/info` | 系统信息（含进程池状态） |
| POST | `/api/system/restart` | 重启服务 |
| GET/POST | `/api/system/config` | 查看/修改配置 |
| POST | `/api/system/clear-conversations` | 清空所有对话 |
| POST | `/api/system/clean-cache` | 清理 Python 缓存 |
| GET | `/api/system/logs` | 查看日志 |
| POST | `/api/system/clear-logs` | 清除日志 |
| GET | `/api/system/events` | 系统事件（进程回收通知等） |

---

## 命令

消息以 `/` 开头拦截为命令，不发送给 Claude：

| 命令 | 说明 |
|------|------|
| `/help` | 可用命令列表 |
| `/status` | 服务器状态、进程池 |
| `/model` | 查看当前模型 |
| `/effort [等级]` | 查看/设置推理深度 |
| `/compact` | 回收当前对话进程 |
| `/clear` | 清屏 |
| `/stop` | 停止生成 |

---

## 排查

### 常见问题

| 问题 | 解决 |
|------|------|
| 500 错误 | 运行 `clean.bat` → `run.bat` |
| 消息发不出去 | 检查 frp 隧道是否在线 |
| Claude 不回复 | `claude -p "hi"` 检查 CLI 是否正常 |
| 响应慢 | `/compact` 压缩上下文，或新建对话 |
| 端口占用 | `clean.bat` 自动杀 8080 端口进程 |
| 页面空白 | 清除浏览器站点数据，重新打开 |

### 关键日志搜索

| 关键词 | 含义 |
|--------|------|
| `[StreamStore]` | StreamingSession 生命周期 |
| `[DrainTask]` | drain 任务状态 |
| `[Chat] FINALIZED` | 消息完成路径 |
| `[Chat] SSE DISCONNECTED` | 客户端断开 |
| `[StreamStore] Cleanup` | 后台清理过期会话 |
| `[Conv GET]` | API 返回的消息数和 streaming 状态 |
