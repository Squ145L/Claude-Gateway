# Claude Gateway 修改日志

## 2026-07-19 — 卡消息根因分析 + Phase 1/2 规划

### 卡消息根因

`send_message()` 读到第一个 `type: "result"` 就 `break`。但 Claude CLI 在派发后台 agent 后，会先发一个 `result`（agent 还在跑），等 agent 完成后 CLI 继续往 stdout 写 `user(tool_result) → assistant → result`。这第二段输出因为 `send_message()` 已经退出而残留在管道缓冲区，被下一次 `send_message()` 当作"新数据"先读出来，表现为主观感受"卡了一条消息，连发两条才恢复"。

### Phase 1 规划：持久 Reader + Event Queue

**目标：** 消除 stdout 残留。`send_message()` 不再直接读 stdout，改为从 event queue 消费。

```
CLI stdin  ←── _writer_lock ─── send_message()  (只写不读)
CLI stdout ──→ _reader_task (永久运行)
                   ├─ parse NDJSON
                   ├─ track tool_use / tool_result
                   ├─ detect bg tools
                   └─ asyncio.Queue(maxsize=500)
                            │
send_message() ──→ 从 queue 读事件 ──→ yield
   读到 result + 无 bg tools pending → break
```

**关键改动：**
- `SessionProcess` 新增 `_reader_task`、`_event_queue`、`_send_lock`、`_bg_tools`
- `send_message()` 退出条件改为：读到 `result` + `_bg_tools` 为空
- stdin/stdout 解耦，不再人为截断管道

### Phase 2 规划：Agent 结果折叠 + 消息打断

- 后台 agent 输出 → 可折叠消息块（复用 thinking-fold 模式）
- 用户 streaming 期间可打断并注入新消息（类似 CLI Ctrl-C）
- 前端 StreamSession 新增 `INTERRUPTING` / `WAITING` 状态

> 详细计划见 GATEWAY.md →「下一步」

---

## 2026-07-17 — StreamingStore 状态机 + 前端模块化

### 后端
- 🆕 `services/streaming.py` — StreamingSession 状态机 (THINKING/GENERATING/DRAINING/FINALIZED/CANCELLED)，StreamingStore 全局注册表
- 🔨 `api/chat.py` — 闭包变量消除；DB sync 解耦为后台 Task；drain 抽出为独立 `_drain_to_completion()` Task
- 🔨 `api/conversations.py` — GET 响应新增 `streaming` 字段；内存状态 merge 覆盖 DB
- 🔨 `api/system.py` — 修复重启 subprocess 参数；余额查询已有接口，前端新增展示
- 🔨 `main.py` — 新增 `cleanup_stale_streams()` 后台清理任务
- 🗑️ 删除 `static/app.js` (根目录)

### 前端
- 🆕 `static/js/state.js` — 全局状态 + 事件总线
- 🆕 `static/js/api.js` — HTTP + SSE 封装
- 🆕 `static/js/streaming.js` — StreamSession 客户端状态机 (IDLE/CONNECTING/THINKING/GENERATING/WAITING/COMPLETED)
- 🆕 `static/js/render.js` — 消息渲染/markdown/thinking fold
- 🆕 `static/js/ui.js` — 侧边栏/设置/输入/toast/文件/SSE
- 🔨 `static/js/app.js` — 精简为入口 + 事件绑定 + SW 注册
- 🔨 `static/js/style.css` — settings-section 折叠三角；thinking-header 旋转三角
- 🔨 `static/sw.js` — v56
- 🔨 `soft-restart.bat` — 优雅关闭 5s → /F 兜底

### 修复
- CancelledError 穿透 except Exception (7 处)
- drain 被 Cancel 秒杀 (独立 Task)
- 刷新丢回复 (StreamingStore 内存 + API streaming 字段)
- 前端 polling 不启动 (renderMessages 检测 streaming)
- 重启按钮 WinError 87
- PWA 更新/注销按钮无功能
- 空消息残留 DB

## 2026-07-10（下午 — 架构重构）

### 架构重构：常驻进程池（核心变更）
- `services/claude_client.py` — **完全重写**。从 `claude -p` 一次性模式改为常驻进程池：
  - `SessionProcess` 类：一个对话一个长活 claude 进程，`--input-format stream-json` stdin/stdout NDJSON 通信
  - `SessionManager` 类：进程池管理器，按 conversation_id 索引，闲置回收、崩溃自动恢复
  - 去掉了 `-p` 标志 → 进程不退出，上下文在内存 → 同对话第二条消息起秒回，不用重载 70k token
  - 参考：claude-inject (MIT)、Claude Agent SDK 官方文档
- `main.py` — lifespan 中启动进程池、注册 shutdown 清理
- `api/system.py` — `/system/info` 新增 `pool` 字段，可查看进程池状态

### 新增：闲置超时可配置 + 进程回收通知
- `.env` / `config.py` — 新增 `SESSION_IDLE_TIMEOUT_MINUTES`（默认 5，0=永不）
- `api/system.py` — `GET/POST /config` 加入 `session_idle_timeout_minutes`；新增 `GET /events` 系统事件端点
- `services/claude_client.py` — `SessionProcess.is_idle()` 读配置值；回收时 `_emit_event("session_killed", ...)`
- `static/index.html` — 设置面板新增「进程闲置回收」下拉框（5/10/30分钟/永不）
- `static/app.js` — 加载/保存闲置超时设置；每 30s 轮询 `/events`，进程被回收时弹 toast

### 新增：/ 命令系统
- `api/chat.py` — 消息以 `/` 开头时拦截，路由到命令处理器，不发送给 Claude
- 支持命令：`/help` `/status` `/model` `/effort` `/compact` `/clear` `/stop`
- `/effort` 读写 `.env` 中的 `CLAUDE_EFFORT`，新对话生效
- `/compact` 调用 `SessionManager.close_session()` 回收当前进程
- `services/claude_client.py` — spawn 时读取 `CLAUDE_EFFORT` 并传 `--effort`

---

## 2026-07-10（上午 — Bug 修复 + 功能新增）

### 修复：Token 和思考时长持久化
- `db/store.py` — `save_message` 补全 `token_usage`、`thinking_dur`、`thinking_wc` 三个字段的 INSERT
- `db/store.py` — `get_messages` 补全对应 SELECT，历史消息加载时不再丢失 token 和时长
- `api/chat.py` — `event_generator` 新增思考计时：记录 `thinking_start`，结束时计算 `thinking_dur`（1.2s / 1m 35s）和 `thinking_wc`（词数），一起存到 Message
- `api/conversations.py` — API 返回新增 `thinking_dur`、`thinking_wc` 字段
- `static/app.js` — `addThinkingFold` 接受 dur/wc 参数，历史消息显示 "已思考(1.2s) — 16 words"

### 修复：流式消息 footer（token + 时间戳）始终可见
- `static/app.js` — `pump()` 的 `r.done` 块重构：footer 无条件创建，token 有则显示无则跳过，时间戳永远附加

### 修复：Service Worker 缓存导致前端不更新
- `static/sw.js` — 缓存版本 v1→v2，策略从 cache-first 改为 network-first，新增 `skipWaiting` + 旧缓存自动清除

### 修复：`--resume` session 偶尔丢失
- `api/chat.py` — `save_claude_session_id` 调用包裹 try/except，DB 异常不断流
- `db/store.py` — `save_claude_session_id` 同步更新 `updated_at`

### 修复：启动时 JS 崩溃（空白屏 + 侧边栏打不开）
- `static/app.js` — `showChatScreen()` 自动调用从脚本中间移到末尾 `setTimeout(fn, 0)`，避免变量未初始化就访问导致 TypeError

### 修复：权限问题 → bypassPermissions
- `services/claude_client.py` — `--permission-mode` 从 `acceptEdits` 改为 `bypassPermissions`，等同交互模式全部权限

### 修复：文件下载被 SW 卡住
- `static/sw.js` — 所有 `/api/` 请求绕过 Service Worker，下载直通

### 修复：表格渲染错乱
- `static/app.js` — `renderMarkdown` 表格 regex 从 buggy `split('|')` 改为 `slice(1,-1)`，空单元格不再被吞
- `static/style.css` — 表格 `display:block; overflow-x:auto` 支持手机横向滑动

### 修复：Enter=发送 → Enter=换行
- `static/app.js` — 去掉 `msgInput` 和 `welcomeInput` 的 Enter 发送逻辑，只能通过按钮发送

### 修复：字体大小标签错误 + 默认过小
- `static/index.html` — 范围从 13-17 改为 15-22，step=1
- `static/app.js` — 标签逻辑改为 `s<=16?小 : s<=19?中 : 大`，默认 17px

### 修复：主题色设置刷新后重置
- `static/app.js` — 拆出 `setAccent(c, skipSave)` 函数，`applyTheme` 调用时 skipSave=true 避免触发 input event 覆盖 localStorage 中的自定义色

### 修复：Service Worker 缓存导致下载等半天
- `static/sw.js` — `/api/` 请求全部绕过 SW，直通网络

### 新增：空态欢迎页
- `static/index.html` — 新增 `#welcome-screen` 欢迎界面（欢迎回来 + 标题 + 输入框 + 加号按钮）
- `static/style.css` — 新增 `.welcome` 系列样式，`.compose-bar.hidden` 隐藏规则
- `static/app.js` — 新增 `updateWelcomeState()` 在空态时显示欢迎页隐藏底部栏，`welcomeSend()` 从欢迎页发消息

### 新增：对话重命名
- `static/app.js` — 顶部标题栏点击变输入框编辑，侧边栏每行 ✏️ 图标点击行内编辑，调用已有 `PUT /api/conversations/{id}/title`
- `static/style.css` — 新增 `.chat-title-input`、`.confirm-edit-btn`、`.rename-conv`、`.conv-title-input` 样式

### 新增：文件下载功能
- `api/files.py` — 新增 `GET /api/files/download/{name}?token=xxx` 下载端点，路径穿越保护
- `static/app.js` — `renderMarkdown` 识别 `[DOWNLOAD:xxx]` → 渲染成下载卡片 📄
- `static/style.css` — `.download-card` 样式
- `static/sw.js` — 下载端点绕过 SW 缓存

### 新增：文件上传保留原名 + Claude 自动感知
- `api/files.py` — 文件存盘用原始文件名，重名加 `(1)` 后缀
- `services/claude_client.py` — `build_messages_for_claude` 收到文件时拼 `[用户上传了: xxx]` 通知 Claude
- `static/app.js` — `streamChat` 传 `file_ids`，`doSendSSE` 发文件提示

### 新增：滚动条美化 + 滚底按钮
- `static/style.css` — 桌面 8px 自定义 `-webkit-scrollbar`；`.scroll-bottom-btn` 右下角 ↓ 按钮
- `static/app.js` — `initScrollBottom()` 离开底部 200px 浮现，点击 smooth 滚到底

### 修复：claude_client.py 稳定性
- `services/claude_client.py` — stderr task 加引用 + CancelledError 处理 + finally cancel
- `main.py` — 全局 `loop.set_exception_handler` 兜底
- `run.bat` — `:loop` 死循环守护，崩溃 2 秒后自动重启
- `services/claude_client.py` — `CLAUDE_PLUGIN_ROOT` 自动检测并补全

### 修复：断线提示
- `static/app.js` — SSE `.catch` 中加 toast "连接断开，请刷新页面"

### 修复：进对话不自动滚到底
- `static/app.js` — `switchConversation` 中 `requestAnimationFrame` 延迟滚动

### 优化：思考面板显示
- `static/app.js` — 流式思考时 `updateThinkingFold` header 显示 "Thinking..."（原 "···"），状态栏显示 "  Thinking"（放大 0.7→0.85rem）
- `static/style.css` — `.status-bar` 字号 0.7→0.85rem
