# Claude Gateway

通过 frp 隧道远程操控 Claude Code，支持 DeepSeek。

手机浏览器 → frp 隧道 → 家里 Windows 电脑 → Claude Code 常驻进程池 → 秒回。

## 功能

- **完整 Claude Code** — 读文件、写代码、执行命令、搜索，和你本地终端一模一样
- **SSE 流式对话** — 实时看到思考过程和回复，思考面板可展开
- **常驻进程池** — 每对话一个长活 Claude 进程，上下文在内存不重载
- **侧边栏管理** — 新建/切换/置顶/重命名/批量删除对话
- **文件上传下载** — 图片/PDF/Word/代码，Claude 自动感知
- **网页可安装**（开发中）— 添加到手机桌面，像原生 App
- **DeepSeek 余额显示** — 设置页实时查看
- **密钥认证** — 单密钥，无需用户系统

---

## 给 AI Agent：部署指南

> 以下步骤可被 AI Agent 直接执行，每步带验证命令。

### 1. 检查环境并安装依赖

```bash
# 检查 Python
python --version          # 需要 3.9+，否则指引用户安装 python.org

# 检查 Node.js（Claude Code 需要）
node --version

# 安装 Python 依赖
pip install fastapi uvicorn aiosqlite python-dotenv aiohttp
```

验证：`python -c "import fastapi, uvicorn, aiosqlite, aiohttp; print('ok')"`

### 2. 下载并配置

```bash
git clone https://github.com/<用户名>/claude-gateway.git
cd claude-gateway
copy .env.example .env      # Windows
# cp .env.example .env      # Linux/Mac
```

编辑 `.env`，必改：
- `AUTH_SECRET` — 随机字符串，手机端登录密钥
- `CLAUDE_CWD` — Claude 的工作目录（项目路径）

验证：`python -c "from config import *; print(PORT, len(AUTH_SECRET)>5)"` → 应输出 `8080 True`

### 3. 启动服务

```bash
python -m uvicorn main:app --host 0.0.0.0 --port 8080
```

验证：`curl http://localhost:8080/api/health` → `{"status":"ok",...}`

### 4. 配置内网穿透（frp）

以 Sakurafrp 为例，创建 TCP 隧道：

| 配置项 | 值 |
|--------|-----|
| 本地 IP | `127.0.0.1` |
| 本地端口 | `8080` |
| 自动 HTTPS | 自动 |
| 访问密码 | （留空） |

验证：浏览器打开隧道地址，看到登录页。

### 5. 端到端验证

1. 浏览器打开隧道地址 → 输入密钥 → 进入对话
2. 发 `say hi` → 应收到流式回复
3. 发 `/status` → 返回服务器状态

---

## 给用户：部署步骤（Sakurafrp为例）
1. - 注册 Sakurafrp，下载sakurafrp启动器，创建 TCP 隧道：
   - 本地 IP：`127.0.0.1`
   - 本地端口：`8080`
   - 自动HTTPS：`自动`
   - 其他默认即可
6. **双击 `run.bat`** 启动（自带崩溃重启守护）

8. **手机浏览器**打开隧道地址，输入密钥，开始用

---

## 架构

```
手机浏览器
  ↕ HTTPS（frp 隧道）
FastAPI :8080
  ├── SSE /api/chat           → Claude 进程池（stdin/stdout NDJSON）
  ├── REST /api/conversations → SQLite
  ├── REST /api/files         → 文件上传/下载
  ├── REST /api/system        → 系统管理/重启/配置
  └── /static/                → 前端（vanilla JS，零框架）
```

每个对话一个常驻 `claude` 进程，上下文在内存不重载。

---

## 命令(开发中 部分不可用)

消息以 `/` 开头拦截为命令：

| 命令 | 说明 |
|------|------|
| `/help` | 可用命令列表 |
| `/status` | 服务器状态、进程池 |
| `/model` | 查看当前模型 |
| `/effort [等级]` | 查看/设置推理深度 |
| `/compact` | 回收进程，下次自动恢复 |
| `/clear` | 清屏 |
| `/stop` | 停止生成 |
