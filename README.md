# Claude Gateway

通过 frp 隧道远程操控 Claude Code，支持 DeepSeek。

浏览器访问 → frp 隧道 → 家里 Windows 电脑 → Claude Code 常驻进程池 → 秒回。

## 功能

- **完整 Claude Code** — 读文件、写代码、执行命令、搜索，和你本地终端一模一样
- **SSE 流式对话** — 实时看到思考过程和回复，思考面板可展开
- **常驻进程池** — 每对话一个长活 Claude 进程，上下文在内存不重载
- **侧边栏管理** — 新建/切换/置顶/重命名/批量删除对话
- **文件上传下载** — 图片/PDF/Word/代码，Claude 自动感知
- **PWA 可安装** — 添加到手机桌面，像原生 App
- **DeepSeek 余额显示** — 设置页实时查看
- **密钥认证** — 单密钥，无需用户系统

## 给 Agent 看：如何部署

> 以下步骤一个 AI Agent 可以直接执行。每一步都能验证结果。

### 1. 环境检查

```bash
python --version         # 需要 3.9+
node --version           # 需要 Node.js
claude --version         # Claude Code CLI 必须已安装
```

### 2. 克隆并安装

```bash
git clone https://github.com/<user>/claude-gateway.git
cd claude-gateway
pip install -r requirements.txt
```

验证：`python -c "import fastapi, uvicorn, aiosqlite, aiohttp"` 无报错。

### 3. 配置

```bash
copy .env.example .env     # Windows
# cp .env.example .env     # Linux/Mac
```

编辑 `.env`，必改两项：
- `AUTH_SECRET=你的随机密钥`（手机端登录用）
- `CLAUDE_CWD=你的项目路径`（Claude 工作目录）

验证：`python -c "from config import *; print(PORT, AUTH_SECRET[:4])"` 输出端口和密钥前 4 位。

### 4. 启动

```bash
python -m uvicorn main:app --host 0.0.0.0 --port 8080
```

验证：`curl http://localhost:8080/api/health` 返回 `{"status":"ok",...}`。

### 5. 内网穿透

用 Sakurafrp 或其他 frp 服务创建 **TCP 隧道**，指向 `127.0.0.1:8080`。

验证：浏览器打开隧道地址，看到 Claude Gateway 登录页。

### 6. 验证完整链路

1. 浏览器打开隧道地址
2. 输入 `.env` 中设置的密钥
3. 发一条 `say hi in one word` → 应收到流式回复
4. 发 `/status` → 应返回服务器状态

## 用户部署步骤

1. **装 Python 3.9+ 和 Node.js**（Claude Code 需要）
2. **装 Claude Code CLI**：`npm install -g @anthropic-ai/claude-code`
3. **下载本项目**，解压到 Windows 电脑
4. **双击** `run.bat` 启动服务器
5. **配置 frp 隧道**，指向本机 `127.0.0.1:8080`
6. **手机浏览器**打开隧道地址，输入密钥，开始用

> `run.bat` 自带进程守护——崩溃后 2 秒自动重启。

## 架构

```
手机浏览器
  ↕ HTTPS (frp 隧道)
FastAPI :8080
  ├── SSE /api/chat          → Claude 进程池（stdin/stdout NDJSON）
  ├── REST /api/conversations → SQLite（对话/消息存储）
  ├── REST /api/files        → 文件上传下载
  ├── REST /api/system       → 系统管理/重启/配置
  └── /static/               → PWA 前端（vanilla JS，零框架）
```

每个对话一个常驻 `claude` 进程，上下文在内存不重载。闲置超时可配置。

## 命令

消息以 `/` 开头拦截为命令：

| 命令 | 说明 |
|------|------|
| `/help` | 显示可用命令 |
| `/status` | 服务器状态、进程池 |
| `/model` | 查看当前模型 |
| `/effort [等级]` | 查看/设置推理深度 |
| `/compact` | 回收进程，下次自动 resume |
| `/clear` | 清屏 |
| `/stop` | 停止生成 |
