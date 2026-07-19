// ═══════════════════════════════════════════════════════════════
// components/welcome.js — Welcome / empty-state screen
// ═══════════════════════════════════════════════════════════════
//
// 管理欢迎页的全部逻辑:
//   - 可见性控制 (有无消息、有无当前对话)
//   - 输入框事件 + 发送 → 委托 chat.sendMessage
//   - + 按钮 → 委托 compose.toggleActionSheet
//
// 依赖: dom, state, events
// 被依赖: app.js (初始化)
// ═══════════════════════════════════════════════════════════════

import { dom } from '../core/dom.js';
import { state } from '../core/store.js';
import { events } from '../core/events.js';
import { api } from '../services/api.js';
import { notify } from '../utils/notify.js';

export const welcome = {
    /**
     * 绑定事件 + 监听。app.js 在初始化时调用。
     */
    init() {
        // ── 发送按钮 ──────────────────────────────────────
        if (dom.welcomeSendBtn) {
            dom.welcomeSendBtn.addEventListener('click', () => this._send());
        }

        // ── + 按钮 → 委托 compose ────────────────────────
        if (dom.welcomePlusBtn) {
            dom.welcomePlusBtn.addEventListener('click', e => {
                e.stopPropagation();
                // 通过事件通知 compose 打开 action sheet (解耦)
                events.emit('compose:toggleActionSheet');
            });
        }

        // ── 键盘 Enter 发送 ──────────────────────────────
        if (dom.welcomeInput && !state.isMobile) {
            dom.welcomeInput.addEventListener('keydown', e => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    this._send();
                }
            });
        }

        // ── 监听可见性变更 ───────────────────────────────
        events.on('chat:opened',       () => this.update());
        events.on('chat:updateWelcome',() => this.update());
        events.on('render:refresh',    () => this.update());

        this._loadStatus();

        console.log('[welcome] Events bound');
    },

    // ── 可见性 ──────────────────────────────────────────

    /**
     * 规则: 无 currentConvId 且消息区无 .msg 元素 → 显示 welcome。
     * 否则显示消息区 + compose bar。
     */
    update() {
        const hasMsgs = document.querySelector('#messages-container .msg');

        if (!dom.messagesContainer) return;

        if (!hasMsgs) {
            // Show welcome, hide messages + compose
            dom.messagesContainer.style.display = 'none';
            if (dom.welcomeScreen)  dom.welcomeScreen.classList.add('active');
            if (dom.composeBar)     dom.composeBar.classList.add('hidden');
        } else {
            // Show messages + compose, hide welcome
            dom.messagesContainer.style.display = '';
            if (dom.welcomeScreen)  dom.welcomeScreen.classList.remove('active');
            if (dom.composeBar)     dom.composeBar.classList.remove('hidden');
        }
    },

    // ── 状态栏 ────────────────────────────────────────

    _loadStatus() {
        api.get('/api/system/info').then(d => {
            const el = dom.welcomeStatus;
            const online = d.status === 'ok';
            const pool = d.pool || {};
            const sessions = pool.alive || 0;
            const total = pool.total || 0;
            if (el) {
                const dot = '<span class="dot ' + (online ? 'online' : 'offline') + '"></span>';
                el.innerHTML = dot + (online ? '已连接' : '未连接')
                    + ' · ' + sessions + ' 个活跃会话';
            }
            // notify.push('模型: ' + (d.claude_cli || 'Claude'));
            notify.push('进程池: ' + sessions + '/' + total + ' 个活跃');
            notify.push('运行: ' + (d.uptime || '-'));
            // notify.push('就绪');
            console.log('[welcome] Status — online=%s sessions=%s/%s', online, sessions, total);
        }).catch(() => {
            const el = dom.welcomeStatus;
            if (el) el.innerHTML = '<span class="dot offline"></span>未连接';
            notify.push('连接服务器失败', 'error');
        });
    },

    // ── 发送 ────────────────────────────────────────────

    _send() {
        const inp = dom.welcomeInput;
        if (!inp) return;

        const text = inp.value.trim();
        const files = state.pendingFiles;

        if (!text && files.length === 0) return;
        inp.value = '';

        console.log('[welcome] Send — text=%s files=%s',
            text.slice(0, 40), files.length);

        // 显示聊天 UI
        dom.messagesContainer.style.display = '';
        if (dom.welcomeScreen)  dom.welcomeScreen.classList.remove('active');
        if (dom.composeBar)     dom.composeBar.classList.remove('hidden');

        // 把文本设到主输入框，委托 chat 发送
        if (dom.msgInput) dom.msgInput.value = text;

        // 动态 import chat 发送 (避免循环依赖)
        import('./chat.js').then(m => {
            const fileObjs = files.map(f => ({
                name: f.name, file_id: f.file_id, preview: f.preview,
            }));
            m.chat.sendMessage(text, fileObjs);
        });

        // 清空 compose
        import('./compose.js').then(m => m.compose.clear());
    },
};

console.log('[components/welcome] Initialized');
