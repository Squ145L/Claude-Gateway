# Claude Gateway — Bug 分析日志

## 2026-07-23 WinError 2 — 系统找不到指定文件

### 现象
开新对话时报错 `[WinError 2] 系统找不到指定的文件`，消息发不出去。

### 根因
`claude_client.py` 第 29 行 `CLAUDE_BIN = shutil.which("claude")`。`run.bat` 双击启动时继承 Windows Explorer 的 PATH，不含 `%APPDATA%\npm`。`shutil.which("claude")` 返回 None → 退化为裸字符串 `"claude"` → `create_subprocess_exec("claude")` 找不到文件。

### 修复
`run.bat` 中 `python` 前加 `set PATH=%PATH%;%APPDATA%\npm`。

---

## 2026-07-23 版本号显示 `v-`

### 现象
设置面板更新栏刚打开时版本号显示 `v-`。

### 根因
旧的 `get_config()` 没有 `version` 字段，`d.version` 为 `undefined` → `'v' + (undefined || '-')` = `'v-'`。

### 修复
- `get_config()` 加 `_read_version_json()` 读 `version.json` 返回版本字段
- 前端加守卫：`ver ? 'v' + ver : '-'`

---

## 2026-07-23 查看日志按钮无反应

### 现象
[系统] section 收起状态时点查看日志没反应，重新展开才显示。

### 根因
auto-expand 时 `body.style.maxHeight = body.scrollHeight + 'px'`，此时日志还没加载（`.hidden` + 空内容），高度锁死在极小值。日志加载完后溢出被 `overflow:hidden` 裁掉。

### 修复
展开时设 `maxHeight = 'none'` 让容器自然撑开。

---

## 2026-07-23 通知淡入动画不生效

### 现象
toast 通知只有退场动画，没有入场动画。

### 根因
`_flush()` 中 `createElement` → `insertBefore` 在同一帧完成，浏览器跳过 CSS animation。

### 修复
插入 DOM 时 `animation: none`，然后 `requestAnimationFrame` 恢复 → 强制浏览器在下一帧播放入场动画。

---

## 2026-07-23 GitHub Release prerelease 404

### 现象
自动更新 `check()` 调 `/releases/latest` 返回 404，即使有 Release。

### 根因
GitHub 的 `/releases/latest` 跳过 prerelease。用户的 Release 勾了 "Set as a pre-release"。

### 修复
改用 `/releases?per_page=1` — 返回最新一条（包含 prerelease）。

---

## 2026-07-22 系统信息重复显示

### 现象
设置面板系统 section 中端口、余额、运行时长出现在多处。

### 根因
旧 `_loadSysInfo()` 在 `#sys-info` 写入余额/端口/运行，新增的 `_tickStatus()` 又在 `#sys-live-text` 写入同样数据。

### 修复
`#sys-info` 改为只显示 DB 统计（对话数/消息数）；`#sys-live-text` 为实时状态唯一来源。

---

## 2026-07-19 卡消息根因分析

### 现象
偶尔"卡一条消息"——发了消息没回复，连发第二条才能看到第一条的回复。

### 根因
`send_message()` 读到第一个 `type: "result"` 就 `break`。但 Claude CLI 在派发后台 agent 后，会先发一个 `result`（agent 还在跑），等 agent 完成后 CLI 继续往 stdout 写 `user(tool_result) → assistant → result`。这第二段输出因为 `send_message()` 已经退出而残留在管道缓冲区，被下一次 `send_message()` 当作"新数据"先读出来。

### 修复方向
**Phase 1:** stdout reader 改为持久 Task + event queue；`send_message()` 从 queue 消费，读到 result + 后台工具全部完成才 break。
**Phase 2:** Agent 结果折叠 + 用户 streaming 期间可打断注入新消息。

---

## 2026-07-17 StreamingStore 重构 — 7 个断网丢回复 Bug

### 根因
状态散落在闭包变量/模块/DB 之间，`CancelledError` 在 asyncio 里穿透所有 `except Exception`。

| # | 现象 | 修复 |
|---|------|------|
| 1 | 刷新丢 thinking | StreamingStore 写内存即时，DB sync 后台跑 |
| 2 | 切换后 thinking 永远在转 | API `streaming` 字段驱动 + polling |
| 3 | 断网 toast "已恢复" 实际没恢复 | 退避重试 + polling 兜底 |
| 4 | 切后台 DOM 被重建 | `isLive()` 保护 |
| 5 | `CancelledError` 穿透 `except Exception` | 全链路 7 处 `except (CancelledError, Exception)` |
| 6 | drain 0 chunks | 独立 `asyncio.create_task(_drain_to_completion())` |
| 7 | 空消息残留 DB | finalize(empty) → cancel + conversations 兜底过滤 |
| 8 | 重启按钮 WinError 87 | `CREATE_NEW_CONSOLE|DETACHED_PROCESS` 互斥 → 只用后者 |
| 9 | PWA 按钮不工作 | 完整 SW 注册/更新/注销逻辑 |
| 10 | DB_PATH 环境变量污染 | `dotenv_values()` 直接读文件 |
