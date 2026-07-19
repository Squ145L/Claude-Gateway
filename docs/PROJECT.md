# Claude Gateway — 项目结构与编码规范

## 目录结构

```
claude-gateway/
├── docs/                    # 项目文档
│   ├── PROJECT.md           # 本文件
│   └── UI-STANDARDS.md      # UI 规范
├── api/                     # HTTP 路由层
│   ├── chat.py              # POST /api/chat
│   ├── chat-commands.py     # /slash 命令处理
│   ├── chat-drain.py        # SSE 断连后排空任务
│   ├── auth.py              # 认证 + token 验证
│   ├── conversations.py     # 对话 CRUD
│   ├── files.py             # 文件上传/下载/预览
│   ├── health.py            # /api/health
│   ├── system.py            # 系统信息/配置/操作
│   ├── system-info.py       # 系统信息 + DeepSeek 余额
│   ├── system-config.py     # 运行时配置读写
│   └── system-actions.py    # 日志/缓存/重启操作
├── services/                # 业务逻辑层（有状态）
│   ├── claude-client.py     # Claude CLI 进程池管理
│   └── streaming.py         # 流式消息状态机
├── db/                      # 数据持久化层
│   ├── models.py            # 数据模型定义
│   └── store.py             # SQLite 操作
├── static/                  # 前端 PWA
│   ├── index.html           # 唯一入口
│   ├── sw.js                # Service Worker
│   ├── manifest.json        # PWA manifest
│   ├── base.css             # reset + :root 变量 + html/body
│   ├── layout.css           # 页面骨架: header / sidebar / compose / welcome
│   ├── controls.css         # 交互控件: btn / input / select / form
│   ├── chat.css             # 消息 / markdown / code / thinking / download-card
│   ├── overlay.css          # 临时浮层: dialog / toast / context-menu / action-sheet
│   ├── scrollbar.css        # webkit scrollbar
│   └── js/
│       ├── app.js           # 入口: import + init + SW + auto-login
│       ├── core/            # 零依赖基石
│       │   ├── store.js     #   响应式状态
│       │   ├── events.js    #   跨模块事件总线
│       │   └── dom.js       #   DOM 懒缓存
│       ├── utils/           # 纯工具函数
│       │   ├── html.js      #   escHtml / fmtNum
│       │   └── notify.js    #   左上角通知栈
│       ├── services/        # 前端服务层（纯逻辑，不碰 DOM）
│       │   ├── api.js       #   HTTP + SSE + 文件 URL 构造
│       │   ├── stream.js    #   StreamSession 状态机
│       │   └── theme.js     #   主题: 预设 / 强调色 / 字体
│       ├── render/          # 渲染层（不存状态）
│       │   ├── markdown.js  #   纯函数: text → HTML
│       │   ├── thinking.js  #   思考折叠操作
│       │   └── messages.js  #   消息渲染 / 状态栏 / 滚动
│       └── components/      # UI 组件（不直接请求网络）
│           ├── settings-screen.js
│           ├── settings-panel.js
│           ├── chat.js
│           ├── sidebar.js
│           ├── compose.js
│           ├── confirm.js
│           └── welcome.js
├── config.py                # 服务端配置
├── logger.py                # 日志
├── main.py                  # FastAPI 入口
└── README.md                # 项目说明
```

## 文件命名

全部 **kebab-case**，包括 Python 文件。

```
✅ settings-panel.js   ❌ settingsPanel.js
✅ chat-commands.py    ❌ chat_commands.py
✅ claude-client.py    ❌ claude_client.py
```

## 前端模块分层

```
app.js ── 唯一组装点，import + init 所有模块
  │
  ├─ core/    零依赖
  │   store  — 响应式状态。任何模块可读 state.x，可订阅 state.on('x', fn)
  │   events — pub/sub 事件总线。跨模块通信专用
  │   dom    — 懒缓存所有 DOM 元素。其他模块禁止直接 querySelector
  │
  ├─ utils/   只依赖 core
  │   纯函数，无副作用。可被任意层 import
  │
  ├─ services/   只依赖 core + utils
  │   前端服务。不操作 DOM。不 import 组件
  │
  ├─ render/   依赖 utils + services
  │   渲染函数。不存状态。输入 → 输出
  │
  └─ components/   依赖以上全部
      每个组件一个文件，一个职责
```

### 依赖规则

| 规则 | 说明 |
|------|------|
| 禁止反向 import | 下层不能 import 上层 |
| 跨模块通信走 events | 组件 A 通知组件 B → `events.emit()` / `events.on()` |
| 同层允许直接 import | compose 可以直接 import chat.sendMessage |
| 禁止直接 querySelector | 必须从 dom.js 取引用。动态节点用 dom.rebind() |
| 禁止复制粘贴 | 发现已有功能就复用 import，不写第二份 |

## 前端模块职责

| 层 | 能做的 | 禁止做的 |
|----|--------|----------|
| core | 状态管理、DOM 缓存、事件分发 | — |
| utils | 纯函数 | 操作 DOM、访问网络 |
| services | 网络请求、流管理、主题切换 | 操作 DOM |
| render | 生成 HTML、操作 DOM 属性 | 保存状态、发送网络请求 |
| components | 组装 render + services，绑定事件 | 直接 fetch/XHR（必须走 api.js） |

## 后端分层

```
Route (api/) → Service (services/) → Store (db/) / Client (services/)
```

### 规则

| 层 | 职责 | 禁止 |
|----|------|------|
| Route | 参数解析 → 调 Service → 返回 Response | 不放业务逻辑 |
| Service | 业务逻辑，可调多个 Store/Client | 不操作 HTTP |
| Store | 纯数据持久化 (SQLite) | 不知道 HTTP / Claude / Streaming |
| Client | 外部 API 调用 (Claude CLI) | 不访问数据库 |
| Streaming | 流式协议状态管理 | 不保存聊天、不处理业务 |

路由可以直接调 Store **仅当操作极短（≤2 行纯 CRUD，无分支）**。其他情况必须过 Service。

## Import 顺序（前端）

```javascript
// 1. core      (store, events, dom)
// 2. utils     (html, toast)
// 3. services  (api, stream, theme)
// 4. render    (markdown, thinking, messages)
// 5. components (同层兄弟)
```

每组之间空一行。缺了中间层也不报错，但一眼看出耦合异常。

## 文件大小

不设行数硬限制。以**单一职责**为准——一个文件做一件事，做到完整。职责膨胀了就拆。

## Event 命名

格式：`模块:动作`

```
✅ chat:opened
✅ sidebar:refresh
✅ render:scroll
✅ compose:toggleActionSheet
❌ openChat
❌ refresh_sidebar
```

## Console 日志

**统一格式：**
```
[module] action — key=value
[module] action → result
[module] ERROR: message
```

**级别：**
| 级别 | 用途 | 示例 |
|------|------|------|
| `console.log` | 模块 init、状态变更、用户操作、请求开始/结束 | `[chat] SSE started conv=%s` |
| `console.warn` | 可降级错误、静默失败 | `[api] Failed to load, degraded` |
| `console.error` | 用户可见错误、网络失败 | `[chat] SSE error: %s` |

**禁止：**
- 记滚动事件、每帧动画、每次渲染
- "代码执行到这里" 的探路日志
- `JSON.stringify(data)` → 用 `%o`
- `.catch(() => {})` 裸吞 → 必须至少 `console.warn`

## 错误处理

| 场景 | 方式 |
|------|------|
| 用户操作失败 | `console.error` + `toast.show()` |
| 后台轮询/请求失败 | `console.error`，不弹 toast |
| 可选数据加载失败 | `console.warn`，静默降级 |

## 注释

区块分隔用 `// ──`，文件头用 `// ═══`。关键逻辑 + BUGFIX 标注处必须注释。
