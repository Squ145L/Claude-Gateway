# Claude Gateway

手机 / 电脑浏览器上远程使用 Claude Code，能力和你电脑终端上一模一样——读文件、写代码、执行命令、搜索项目，全部支持。

```
浏览器 ──→ Sakurafrp 隧道 ──→ 家里 Windows 电脑 :8080 ──→ Claude Code 常驻进程
                                    ↑
                              上下文在内存，秒回
```

## 功能

- **完整 Claude Code 能力** — 不是简单的文本对话，是真正的 Claude Code CLI 远程终端
- **常驻进程架构** — 每个对话一个长活 claude 进程，stdin/stdout NDJSON 通信，上下文在内存不重载
- **进程池管理** — 闲置超时可配置（5/10/30分钟/永不），崩溃自动恢复
- **多会话管理** — 新建/切换/重命名/批量删除对话，每个对话独立上下文
- **文件上传** — 支持图片/PDF/Word/代码，原始文件名保留，Claude 自动感知
- **文件下载** — Claude 用 `[DOWNLOAD:文件名]` 回复 → 前端渲染下载卡片 → 点一下保存
- **/ 命令系统** — `/help` `/status` `/model` `/effort` `/compact` `/clear` `/stop`
- **SSE 流式响应** — 实时看到 Claude 思考和回复
- **思考面板** — 可展开收起，显示思考时长和词数
- **密钥认证** — 单密钥保护，无需用户系统
- **PWA 支持** — 可添加到手机桌面，像原生 App
- **自定义主题** — 黑/暗/灰/蓝四套预设 + 自定义强调色 + 字号
- **设备自适应** — 桌面 Enter=发送，手机 Enter=换行

## 快速开始

### 1. 环境要求

- Windows 10/11
- Python 3.9+
- Node.js（Claude Code CLI 已安装）
- Sakurafrp 或其他内网穿透工具

### 2. 安装

```powershell
cd E:\Claudeproject\claude-gateway
pip install -r requirements.txt
```

### 3. 配置

复制并编辑配置文件：

```powershell
copy .env.example .env
notepad .env
```

**`.env` 所有配置项（`.env.example` 内容）：**

```env
# === 必填 ===
AUTH_SECRET=改成一个随机字符串          # 手机端登录密钥 (必改!)
CLAUDE_CWD=E:\Claudeproject            # Claude 工作目录 (改成你的项目路径)

# === 服务 ===
HOST=0.0.0.0
PORT=8080

# === 文件 ===
FILE_ROOT_DIR=E:\Claudeproject\ClaudeFiles
MAX_FILE_SIZE_MB=20
FILE_TTL_HOURS=24

# === 日志 ===
LOG_LEVEL=DEBUG
CONSOLE_MIRROR=true

# === 存储 ===
DB_PATH=./data/conversations.db

# === 会话 ===
SESSION_TIMEOUT_MINUTES=0              # 0=永不超时
SESSION_IDLE_TIMEOUT_MINUTES=5         # 进程闲置回收 (0=永不)

# === 推理 ===
CLAUDE_EFFORT=high                     # low|medium|high|xhigh|max

# === OCR (可选) ===
OCR_ENABLED=true
```

> **⚠️ 首次使用必须改的：** `AUTH_SECRET` 和 `CLAUDE_CWD`。其他用默认即可。

### 4. 启动

```powershell
run.bat
# 或者
python -m uvicorn main:app --host 0.0.0.0 --port 8080
```

`run.bat` 自带进程守护——崩溃后 2 秒自动重启。

### 5. 配置内网穿透

在 Sakurafrp 创建 **TCP 隧道**，指向 `127.0.0.1:8080`。

浏览器打开隧道地址，输入密钥即可使用。

## 架构

```
浏览器
  ↕ HTTPS (Sakurafrp)
FastAPI :8080
  ├── SSE /api/chat         → 常驻 claude 进程池（stdin/stdout NDJSON）
  ├── REST /api/conversations → SQLite
  ├── REST /api/files       → 文件存储 + 下载
  ├── REST /api/system      → 日志/重启/配置/事件
  └── Static                → PWA 前端
```

每个对话对应一个常驻 `claude --input-format stream-json` 进程。第一条消息创建进程，后续消息通过 stdin 注入、stdout 读取，上下文一直在内存里不重载。闲置超时后自动回收，下次消息通过 `--resume` 从磁盘恢复。

## 项目结构

```
claude-gateway/
├── .env                    # 配置文件
├── main.py                 # FastAPI 入口 + 进程池管理
├── config.py               # 配置加载
├── logger.py               # 日志系统
├── api/
│   ├── auth.py             # 密钥验证
│   ├── chat.py             # 对话 API (SSE + 命令拦截)
│   ├── conversations.py    # 会话 CRUD
│   ├── files.py            # 文件上传 + 下载
│   ├── health.py           # 健康检查
│   ├── esp32.py            # ESP32 预留
│   ├── system.py           # 系统管理（重启/日志/配置/事件）
│   └── ratelimit.py        # 速率限制
├── services/
│   ├── claude_client.py    # Claude 进程池（SessionProcess + SessionManager）
│   ├── ocr_pipeline.py     # OCR 管道
│   └── file_parser.py      # 文件解析
├── db/
│   ├── models.py           # 数据模型
│   └── store.py            # SQLite 操作
├── static/                 # PWA 前端
│   ├── index.html
│   ├── app.js
│   ├── style.css
│   ├── manifest.json / sw.js
├── data/                   # SQLite 数据库
├── logs/                   # 日志文件
├── run.bat                 # 启动脚本（带进程守护）
├── clean.bat               # 清理缓存
└── restart.bat             # 重启脚本
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat` | SSE 流式对话 |
| GET/POST/DELETE | `/api/conversations` | 会话管理 |
| PUT | `/api/conversations/{id}/title` | 重命名对话 |
| POST | `/api/files/upload` | 文件上传 |
| GET | `/api/files/download/{name}?token=xxx` | 文件下载 |
| GET | `/api/files/{id}/content` | 文件内容 |
| POST | `/api/auth/verify` | 密钥验证 |
| GET | `/api/health` | 健康检查 |
| GET | `/api/system/info` | 系统信息（含进程池状态） |
| POST | `/api/system/restart` | 重启服务器 |
| GET/POST | `/api/system/config` | 查看/修改配置 |
| POST | `/api/system/clear-conversations` | 清空所有对话 |
| POST | `/api/system/clean-cache` | 清理 Python 缓存 |
| GET | `/api/system/logs` | 查看日志 |
| POST | `/api/system/clear-logs` | 清除日志 |
| GET | `/api/system/events` | 系统事件（进程回收通知等） |

所有 `/api/*` 端点需要 `Authorization: Bearer <secret>` 头（下载端点支持 `?token=xxx` 查询参数）。

## 命令

消息以 `/` 开头时被拦截为命令，不发送给 Claude：

| 命令 | 说明 |
|------|------|
| `/help` | 显示可用命令 |
| `/status` | 服务器状态、进程池 |
| `/model` | 查看当前模型 |
| `/effort [等级]` | 查看/设置推理深度（low/medium/high/xhigh/max） |
| `/compact` | 回收当前对话进程，下次消息自动 resume |
| `/clear` | 清屏（前端） |
| `/stop` | 停止生成（前端） |

## 设置面板

浏览器端右上角 ⚙ 可调整：

- **连接** — 服务器地址 + 密钥
- **主题** — 黑/暗/灰/蓝四种预设 + 自定义强调色 + 字体大小
- **文件** — 存储路径 + 上传大小上限
- **系统** — 会话超时 / 进程闲置回收 / 终端镜像 / 清空对话 / 清理缓存 / 查看日志 / 重启

## 排查

| 问题 | 解决 |
|------|------|
| 500 错误 | 运行 `clean.bat` → `run.bat` |
| 消息发不出去 | 检查 Sakurafrp 隧道是否在线 |
| Claude 不回复 | 检查 Claude Code CLI 是否正常：`claude -p "hi"` |
| 响应慢 | 发 `/compact` 压缩上下文，或新建对话 |
| 图片上传卡住 | 检查 ollama 是否运行：`ollama ps` |
| 端口占用 | `clean.bat` 会自动杀 8080 端口进程 |
| 页面空白 | 清除浏览器站点数据，重新打开 |
