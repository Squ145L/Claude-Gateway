# Claude Gateway 修改日志

## 2026-07-23 — 自动更新 + 实时状态 + Bug 修复

### 🆕 自动更新系统
- 🆕 `version.json` — 版本号文件
- 🆕 `services/update.py` — GitHub Release 检查 + 下载 + 解压覆盖
- 🆕 `api/update.py` — `GET /api/system/update-check` + `POST /api/system/update-apply`
- 🆕 `update.bat` — 手动更新逃生舱
- 🔨 `main.py` — 注册 update_router
- 🔨 `config.py` / `.env` — 新增 `AUTO_CHECK_UPDATE` 开关
- 🔨 `api/system.py` — `get_config` / `update_config` 加 `auto_check_update` + `version` 字段
- 🔨 `static/js/core/store.js` — 新增 `updateInfo` / `autoCheckUpdate` 状态
- 🔨 `static/js/services/api.js` — 新增 `checkUpdate()` / `applyUpdate()`
- 🔨 `static/js/components/settings-panel.js` — 更新栏交互逻辑 + `_checkUpdate(silent)`
- 🔨 `static/js/app.js` — 启动 5s 后自动检查更新
- 🔨 `static/js/core/dom.js` — 新增 9 个 selector
- 🔨 `static/index.html` — 更新 section HTML
- 🔨 `static/controls.css` — `.update-badge` `.update-info` `.update-changelog`

### 🆕 实时系统状态
- 🆕 `GET /api/system/status` — 轻量轮询接口，余额 60s 缓存
- 🆕 `POST /api/system/refresh-balance` — 手动刷新余额
- 🔨 `static/index.html` — 双行实时状态 + 余额刷新按钮
- 🔨 `static/js/components/settings-panel.js` — 面板打开时 3s 轮询，关闭时停止

### 🔧 Bug 修复
- 🔨 `run.bat` — WinError 2：补全 `%APPDATA%\npm` 到 PATH
- 🔨 `services/update.py` — `/releases/latest` → `/releases?per_page=1` 支持 prerelease
- 🔨 `static/js/components/settings-panel.js` — 查看日志按钮：`maxHeight: none` 替代固定高度
- 🔨 `static/js/components/settings-panel.js` — 版本号显示：`ver ? 'v' + ver : '-'` 杜绝 `v-`
- 🔨 `static/js/utils/notify.js` — 通知淡入：`animation: none` + RAF 触发
- 🔨 `static/js/components/settings-panel.js` — 系统信息实时刷新（去掉 `_infoLoaded` 缓存门）
- 🔨 `static/js/components/settings-panel.js` — 系统信息去重（DB 统计与实时状态分离）

### 🎨 UI
- 🔨 放行权限标签精简：「绕过权限」→「放行权限」，「ON = 自动批准所有操作」→「批准所有操作」
- 🔨 消息长度限制小字删除
- 🔨 工具状态栏映射：Crawling → WebSearching + 新增 13 种工具
- 🆕 `static/overlay.css` — 通知淡入动画 `@keyframes notify-in`（左侧滑入 + 淡入）
- 🔨 所有 CSS 版本号升级至 v8

---

## 2026-07-22 — 安全审计 + 全面加固

> 详见 `docs/fix.md`（安全审查方案，15项已全部实施）和 `docs/permission-decouple.md`（权限解耦新方案）。

### 🔒 P0 — 权限系统
- 🔨 `config.py` — `CLAUDE_PERMISSION_MODE` 三模式字符串 → `BYPASS_PERMISSIONS` bool
- 🔨 `services/claude_client.py` — 启动参数读 `BYPASS_PERMISSIONS` 配置；OFF 时注入权限引导
- 🆕 `static/controls.css` — `.toggle-switch` iOS 风格滑动开关
- 🔨 `static/js/components/settings-panel.js` — bypass 开关加载/保存逻辑
- 🔨 `api/system.py` — `get_config`/`update_config` 读/写 `BYPASS_PERMISSIONS`

### 🔒 P0 — 认证安全
- 🔨 `api/auth.py` — `secrets.compare_digest()` 恒定时间比较；IP 级别登录爆破防护
- 🔨 `config.py` — 弱密钥启动告警

### 🔒 P0 — 文件下载安全
- 🔨 `api/files.py` — HMAC 签名短期 token 替代明文 `AUTH_SECRET`

### 🟠 P1 — CORS + 安全响应头 + SSRF
- 🔨 `main.py` — `allow_credentials=False`；安全响应头（CSP/X-Frame-Options 等）
- 🔨 `api/system.py` — DeepSeek 余额查询路径白名单

### 🟡 P2 — 日志 + 消息限制 + Magic Bytes
- 🔨 `.env.example` — 生产环境默认值
- 🔨 `services/claude_client.py` — console mirror 敏感词过滤
- 🔨 `config.py` — 新增 `MAX_MESSAGE_LENGTH_ENABLED` / `MAX_MESSAGE_LENGTH`
- 🆕 `static/index.html` — 消息长度限制 toggle + 数值输入框
- 🔨 `api/files.py` — `_verify_content_type()` magic bytes 文件类型校验

### 🟢 P3 — 移除危险标志 + 请求体限制
- 🔨 `api/system.py` — 两处 `shell=True` 移除
- 🔨 `main.py` — `request_max_size=10MB`

### 🎨 UI
- 🆕 `static/favicon.svg` — Claude 风格八芒星 SVG

---

## 2026-07-19 — 卡消息根因分析 + Phase 1/2 规划

### 卡消息根因
`send_message()` 读到第一个 `type: "result"` 就 `break`。但 Claude CLI 在派发后台 agent 后，会先发一个 `result`（agent 还在跑），等 agent 完成后 CLI 继续往 stdout 写 `user(tool_result) → assistant → result`。这第二段输出因为 `send_message()` 已经退出而残留在管道缓冲区。

### Phase 1 规划：持久 Reader + Event Queue
- `SessionProcess` 新增 `_reader_task`、`_event_queue`、`_send_lock`、`_bg_tools`
- `send_message()` 退出条件改为：读到 `result` + `_bg_tools` 为空

### Phase 2 规划：Agent 结果折叠 + 消息打断
- 后台 agent 输出 → 可折叠消息块
- 用户 streaming 期间可打断并注入新消息

---

## 2026-07-17 — StreamingStore 状态机 + 前端模块化

### 后端
- 🆕 `services/streaming.py` — StreamingSession 状态机，StreamingStore 全局注册表
- 🔨 `api/chat.py` — 闭包变量消除；DB sync 解耦；drain 独立 Task
- 🔨 `api/conversations.py` — GET 响应新增 `streaming` 字段
- 🔨 `main.py` — 新增 `cleanup_stale_streams()` 后台清理

### 前端
- 🆕 模块化重构：`core/` `utils/` `services/` `render/` `components/`
- 🆕 `static/js/services/stream.js` — StreamSession 客户端状态机
- 🔨 `static/js/app.js` — 精简为入口 + 事件绑定

### 修复
- CancelledError 穿透 except Exception (7 处)
- drain 被 Cancel 秒杀
- 刷新丢回复
- 重启按钮 WinError 87
- 空消息残留 DB

---

## 2026-07-10 — 常驻进程池 + / 命令系统

### 架构重构
- `services/claude_client.py` — 完全重写：常驻进程池，stdin/stdout NDJSON 通信
- `SessionProcess` / `SessionManager` — 按对话索引，闲置回收，崩溃恢复
- 去掉 `-p` 标志 → 上下文在内存 → 同对话第二条消息起秒回

### 新增功能
- `/` 命令系统：`/help` `/status` `/model` `/effort` `/compact` `/clear` `/stop`
- 闲置超时可配置（5/10/30 分钟/永不）
- 进程回收系统事件通知

### Bug 修复
- Token 和思考时长持久化
- 流式消息 footer 始终可见
- Service Worker 缓存导致前端不更新（v1→v2，network-first）
- 启动时 JS 崩溃
- 表格渲染错乱
- Enter=发送改为换行
- 字体大小标签修正
- 主题色重置修复

---

## 2026-07-10（上午）— 双端口开发环境 + 图片内联

### 新功能
- 双端口开发环境（`:8080` 生产 + `:8081` 开发）
- 图片内联显示（`[FILE:photo.jpg]` → 缩略图 + 点击全屏）
- 软重启（taskkill 不加 /F）
- Gateway 智能提示词
- 对话重命名
- 文件上传保留原名
- 空态欢迎页
- 文件下载功能
- 滚动条美化 + 滚底按钮

### Bug 修复
- 流式消息结束后不可见（缺 scrollTop）
- 切后台消息丢失（visibilitychange 恢复）
- 消息 >100 条截断（ORDER BY DESC 子查询）
- 闲置回收设置跳回 5 分钟（`0 || 5 = 5`）
- Token 偶尔显示 0/0
- 数据库初始化崩溃（ALTER 跑在 CREATE 前）
- run.bat 重启死循环（端口清理）
- Dev 环境变量污染（dotenv_values 替代 load_dotenv）
- file_ids 未返回 API
- 断线提示 toast
