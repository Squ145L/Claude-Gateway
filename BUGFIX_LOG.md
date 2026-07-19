# Claude Gateway — 开发日志

## 2026-07-19 卡消息根因分析

### 现象
偶尔"卡一条消息"——发了消息没回复，连发第二条才能看到第一条的回复。

### 根因
`send_message()` 读到第一个 `type: "result"` 就 `break`。但 Claude CLI 在派发后台 agent 后，会先发一个 `result`（agent 还在跑），等 agent 完成后 CLI 继续往 stdout 写 `user(tool_result) → assistant → result`。这第二段输出因为 `send_message()` 已经退出而残留在管道缓冲区，被下一次 `send_message()` 当作"新数据"先读出来。

CLI 的 stdin/stdout 是独立双工通道——用户发消息和模型回复互不阻塞。Gateway 当前把 stdin 写入和 stdout 读取绑在 `send_message()` 一个方法里，人为截断了管道。

### 修复方向
**Phase 1:** stdout reader 改为持久 Task + event queue；`send_message()` 从 queue 消费，读到 result + 后台工具全部完成才 break。
**Phase 2:** Agent 结果折叠 + 用户 streaming 期间可打断注入新消息。

> 详细计划见 GATEWAY.md

### 新增中断处理
- `services/claude_client.py` — `_handle_interrupt()` 异步协程：发 SIGINT → drain stale events → 写入新 prompt
- 使用 `await`（非 `yield from`）在 async generator 中调用

---

## 2026-07-17 架构重构：StreamingStore + DrainTask

### 背景
旧架构有 7 个断网丢回复的 bug，根因是状态散落在闭包变量/模块/DB 之间，`CancelledError` 在 asyncio 里穿透所有 `except Exception`。

### 新建文件

| 文件 | 说明 |
|------|------|
| `services/streaming.py` | **StreamingSession 状态机** (276行)：THINKING→GENERATING→DRAINING→FINALIZED→CANCELLED。内存始终最新，API 读内存覆盖 DB |
| `static/js/state.js` | 全局状态 + 事件总线 (60行) |
| `static/js/api.js` | HTTP + SSE 封装 (80行) |
| `static/js/streaming.js` | **StreamSession 客户端状态机** (180行)：IDLE→CONNECTING→THINKING→GENERATING→WAITING→COMPLETED |
| `static/js/render.js` | 消息渲染/markdown/thinking fold (200行) |
| `static/js/ui.js` | 侧边栏/设置/输入/toast/文件 (500行) |

### 重构文件

| 文件 | 改动 |
|------|------|
| `api/chat.py` | 闭包变量 → StreamingStore；handle_chunk 删除 → 内联内存写入；DB sync 解耦为后台 Task；drain 抽出为独立 `_drain_to_completion()` Task |
| `api/conversations.py` | GET 响应加 `streaming` 字段，merge 内存覆盖 DB |
| `api/system.py` | 重启 `subprocess.Popen` 传 string 非 list；去 `CREATE_NEW_CONSOLE\|DETACHED_PROCESS` 互斥 |
| `main.py` | 新增 `cleanup_stale_streams()` 后台任务 |
| `static/app.js` | 从 895 行单文件拆为 6 模块 |
| `soft-restart.bat` | 优雅关闭 5s → /F 兜底 |

### 删除文件
- `static/app.js` (根目录) — 功能迁移至 `js/` 目录

### Bug 修复清单

| # | 现象 | 根因 | 修复 |
|---|------|------|------|
| 1 | 刷新丢 thinking | `flush_to_db` 节流 1s，刷新时 DB 还是空的 | StreamingStore 写内存即时，DB sync 后台跑 |
| 2 | 切换后 thinking 永远在转 | `renderMessages` 不检测 in-progress → `.streaming` class 永不设置 → polling 死循环 | API `streaming` 字段驱动 + renderMessages 启动 polling |
| 3 | 断网 toast "已恢复" 实际没恢复 | `.catch()` 里 `api.getMessages` 静默失败 | 退避重试 + polling 兜底 |
| 4 | 切后台 DOM 被重建 | `visibilitychange` 不查 `_sseActive` → 误删直播 DOM | `isLive()` 保护 + `no-collapse` 逻辑 |
| 5 | `CancelledError` 穿透 `except Exception` | asyncio 中 `CancelledError` 继承 `BaseException` ≠ `Exception` | 全链路 7 处改为 `except (CancelledError, Exception)` |
| 6 | drain 0 chunks | drain 在已 Cancel 的 generator 内 → `await` 立即被杀 | 独立 `asyncio.create_task(_drain_to_completion())` |
| 7 | reader_fn 的 sentinel 丢 | `finally: await put(None)` 被 Cancel → queue 永不关闭 | `except (CancelledError, Exception)` |
| 8 | 空消息残留 DB 显示时间戳 | finalize(empty) → cancel 失败 → content="" 没被过滤 | finalize(empty) 直接 cancel + conversations 兜底过滤 |
| 9 | 重启按钮 WinError 87 | `CREATE_NEW_CONSOLE\|DETACHED_PROCESS` 互斥 | 改为只 `DETACHED_PROCESS` |
| 10 | PWA 按钮不工作 | sw-update/sw-unreg 无 JS 事件 | 完整 SW 注册/更新/注销逻辑 |


## 2026-07-12 会话总结

> 从「能用的原型」推进到「可交付的产品」，修了 14 个 bug/功能，搭建了双端口开发环境。

---

## 🏗️ 架构变更

### 双端口开发环境（自举架构）

- 生产：`:8080` — 用户日常使用，稳定版本
- 开发：`:8081` — 我改代码 + 测试 + 验证后同步到生产
- Sakurafrp 隧道 `frp-put.com:38548` → `:8081`
- 独立数据库、独立 Claude session、互不影响
- 配置：`config.py` 改用 `dotenv_values()` 直接读文件，避免环境变量污染

**文件：** `claude-gateway-dev/`（完整副本）、`soft-restart.bat`

---

## 🎨 新功能

### 1. 图片内联显示

| 标记 | 效果 |
|------|------|
| `[FILE:photo.jpg]` | 缩略图内联 + 点击全屏 + 长按保存 |
| `[FILE:doc.pdf]` | 自动降级为下载卡片 |
| `[DOWNLOAD:xxx]` | 强制下载卡片（和原来一样） |

- 用户上传图片：消息气泡内显示缩略图 + 文件名
- 送图片切对话不丢：`file_ids` 存 `{id, name}` 对象 → API 返回 → 前端重建
- 用户打成 `[FILE:xxx]` 纯文本不会被错误渲染

**文件：** `api/files.py`、`api/chat.py`、`api/conversations.py`、`static/app.js`、`static/style.css`

### 2. 软重启

设置面板新增「软重启」按钮 — `taskkill` 不加 `/F`，让 uvicorn 优雅退出后再启动，不丢状态。

**文件：** `soft-restart.bat`、`api/system.py`、`static/index.html`、`static/app.js`

### 3. Gateway 智能提示词

Claude 子进程启动时被告知：
- 如何用 `[FILE:xxx]` / `[DOWNLOAD:xxx]` 发文件
- 如何截图、拍摄像头
- 斜杠命令列表
- 用户上传文件处理流程

**文件：** `services/claude_client.py`

---

## 🐛 Bug 修复

### 滚动问题（#1 关键 Bug）
**现象：** 流式消息结束后不可见，必须发下一条才出现
**根因：** `r.done` 里 `innerHTML` 替换 `textContent` 后高度变了，缺 `scrollTop`
**修复：** `requestAnimationFrame` + `scrollTop`

### 切后台消息丢失（#2 关键 Bug）
**现象：** 切后台断 SSE → 消息存了 DB 但前端不渲染
**根因：** SSE 断在 `r.done` 之前，DOM 没更新
**修复：** `visibilitychange` 事件 → 从 DB 重新加载 → 流式中则跳过保护

### 切后台 scroll 覆盖（#3）
**现象：** visibility 处理器重新 render 消息但没滚到底
**修复：** visibility 处理器末尾加 `requestAnimationFrame(scrollTop)`

### 消息 >100 条截断（#4 关键 Bug）
**现象：** 对话超过 100 条消息后，最新的消息加载不出来
**根因：** `ORDER BY id ASC LIMIT 100` 取最老 100 条
**修复：** `(SELECT ... ORDER BY id DESC LIMIT 100) ORDER BY id ASC`

### 闲置回收设置跳回 5 分钟（#5）
**现象：** 设置为「永不」(0)，刷新后变回 5
**根因：** JS `0 || 5 = 5`（0 是 falsy）
**修复：** `!= null ? val : 5`

### Token 显示异常（#6）
**现象：** Token 偶尔显示 0/0，之前又显示 30k+ 吓人
**根因：** 误以为 `result.usage` 是累计值，加了 delta 减法
**修复：** 回退到原始值（`result.usage` 本身就是每轮消耗）

### 数据库初始化崩溃（#7）
**现象：** 新 DB 启动时 `no such table: messages`
**根因：** `ALTER TABLE messages ADD COLUMN` 跑在 `CREATE TABLE messages` 之前
**修复：** 调换顺序，先 CREATE 再 ALTER

### run.bat 重启死循环（#8）
**现象：** 崩溃后旧进程占 8080 端口，无限重启循环
**修复：** 启动前 `netstat` + `taskkill` 清理端口

### DB_PATH 环境变量污染 dev（#9）
**现象：** dev 服务器用着生产的数据库，测试对话全乱了
**根因：** `load_dotenv(override=False)` 敌不过已存在的系统环境变量
**修复：** `config.py` 改用 `dotenv_values()` 直接读文件

### `file_ids` 未返回 API（#10）
**现象：** 图片上传后切换对话就消失
**根因：** `api/conversations.py` 漏加了 `file_ids` 到响应
**修复：** 加一行 `"file_ids": m.file_ids`

---

## 🔧 工程改进

- `db/store.py` — init_db CREATE TABLE 排序修正
- `db/store.py` — get_messages 取最新 100 条（子查询）
- `config.py` — `dotenv_values()` 替代 `load_dotenv`（仅 dev，生产保持原样）
- `services/claude_client.py` — stdout buffer 从 64KB 提升到 50MB
- SW 缓存版本迭代：v2 → v3 → v4 → v5 → v6 → v7

---

## 📁 修改文件总览

```
claude-gateway/
├── main.py                        (未改)
├── config.py                      (未改，生产保持 load_dotenv)
├── run.bat                        ✅ 端口清理
├── restart.bat                    (未改)
├── soft-restart.bat               🆕 新建
├── api/
│   ├── chat.py                    ✅ file_ids 兼容 {id,name}
│   ├── conversations.py           ✅ 响应加 file_ids
│   ├── files.py                   ✅ /files/view 图片内联
│   ├── system.py                  ✅ 软重启端点
│   └── ...
├── services/
│   ├── claude_client.py           ✅ Gateway 提示词 + stdout buffer
│   └── ...
├── db/
│   ├── store.py                   ✅ init_db 排序 + get_messages DESC
│   └── ...
├── static/
│   ├── app.js                     ✅ 全部前端改动
│   ├── style.css                  ✅ 图片/全屏/预览样式
│   ├── index.html                 ✅ 软重启按钮
│   ├── sw.js                      ✅ v→v7
│   └── manifest.json              (未改)
└── BUGFIX_LOG.md                  📝 本文件
```

---

## 🚀 下一步（计划）

1. 输入框自适应高度（最大 7 行）
2. 侧边栏消息预览
3. 代码块复制按钮 + 简易高亮
4. 消息操作菜单（复制/重新生成）
