// ═══════════════════════════════════════════════════════════════
// components/settings-screen.js — Initial login / connect screen
// ═══════════════════════════════════════════════════════════════
//
// 密钥输入 → 验证 → 切换到聊天界面。
// 切换后通过 events 通知其他模块 (解耦, 不 import 其他组件)。
//
// 依赖: dom, state, api, toast, events
// 被依赖: app.js (事件绑定)
// ═══════════════════════════════════════════════════════════════

import { dom } from '../core/dom.js';
import { state } from '../core/store.js';
import { events } from '../core/events.js';
import { api } from '../services/api.js';
import { notify } from '../utils/notify.js';

export const settingsScreen = {
    /**
     * 绑定事件。app.js 在初始化时调用。
     */
    init() {
        if (dom.authSecret) dom.authSecret.value = state.secret;

        if (dom.connectBtn) {
            dom.connectBtn.addEventListener('click', () => this.connect());
        }
        if (dom.authSecret) {
            dom.authSecret.addEventListener('keydown', e => {
                if (e.key === 'Enter') this.connect();
            });
        }
        console.log('[settings-screen] Events bound');
    },

    /**
     * 验证密钥并连接。
     */
    connect() {
        const inp = dom.authSecret;
        if (!inp) return;

        const s = inp.value.trim();
        if (!s) {
            inp.style.borderColor = 'var(--danger)';
            setTimeout(() => { inp.style.borderColor = ''; }, 1500);
            return;
        }

        inp.style.borderColor = '';
        if (dom.connectStatus) {
            dom.connectStatus.textContent = '验证中...';
            dom.connectStatus.className = 'status-text';
        }
        if (dom.connectBtn) dom.connectBtn.disabled = true;

        notify.push('正在验证密钥...');
        console.log('[settings-screen] Connecting to %s...', state.serverUrl);

        api.verifySecret(s).then(d => {
            if (d.valid) {
                state.set('secret', s);
                localStorage.setItem('cg_secret', s);
                notify.push('已连接');
                if (dom.connectStatus) {
                    dom.connectStatus.textContent = '已连接';
                    dom.connectStatus.className = 'status-text success';
                }
                console.log('[settings-screen] Secret valid → switching to chat');
                setTimeout(() => this.showChatScreen(), 300);
            } else {
                inp.value = '';
                inp.focus();
                if (dom.connectStatus) {
                    dom.connectStatus.textContent = '密钥错误，请重试';
                    dom.connectStatus.className = 'status-text error';
                }
                inp.style.borderColor = 'var(--danger)';
                setTimeout(() => { inp.style.borderColor = ''; }, 2000);
                console.warn('[settings-screen] Invalid secret');
            }
        }).catch(e => {
            if (dom.connectStatus) {
                dom.connectStatus.textContent = e.message || '连接失败';
                dom.connectStatus.className = 'status-text error';
            }
            console.error('[settings-screen] Connect error:', e);
        }).finally(() => {
            if (dom.connectBtn) dom.connectBtn.disabled = false;
        });
    },

    /**
     * 切换到聊天界面。通过 events 通知其他模块加载数据。
     */
    showChatScreen() {
        if (dom.settingsScreen) dom.settingsScreen.classList.remove('active');
        if (dom.chatScreen) dom.chatScreen.classList.add('active');
        console.log('[settings-screen] → Chat screen active, emitting chat:opened');
        events.emit('chat:opened');
    },
};

console.log('[components/settings-screen] Initialized');
