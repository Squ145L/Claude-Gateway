// ═══════════════════════════════════════════════════════════════
// app.js — Entry point
// ═══════════════════════════════════════════════════════════════
//
// 唯一组装点 — import 所有模块，调用 init()，绑定全局事件。
//
// 加载顺序: core → utils → services → render → components → 本文件
// ESM import 自动保证拓扑序。
// ═══════════════════════════════════════════════════════════════

import { state } from './core/store.js';
import { events } from './core/events.js';
import { dom } from './core/dom.js';
import { api } from './services/api.js';
import { getStream } from './services/stream.js';
import { theme } from './services/theme.js';
import { settingsScreen } from './components/settings-screen.js';
import { settingsPanel } from './components/settings-panel.js';
import { compose } from './components/compose.js';
import { sidebar } from './components/sidebar.js';
import { chat } from './components/chat.js';
import { confirm } from './components/confirm.js';
import { welcome } from './components/welcome.js';
import { notify } from './utils/notify.js';

console.log('╔══════════════════════════════════════════╗');
console.log('║  Claude Gateway — ESM refactored        ║');
console.log('╚══════════════════════════════════════════╝');

// ═══════════════════════════════════════════════════════════════
// 1. Init all components
// ═══════════════════════════════════════════════════════════════

notify.init();
settingsScreen.init();
settingsPanel.init();
compose.init();
sidebar.init();
chat.init();
welcome.init();

console.log('[app] All %s components initialized', 7);

// ═══════════════════════════════════════════════════════════════
// 2. Global event handlers (not specific to one component)
// ═══════════════════════════════════════════════════════════════

// ── Confirm dialog ────────────────────────────────────────────
if (dom.confirmCancel) {
    dom.confirmCancel.addEventListener('click', () => confirm.hide());
}
if (dom.confirmOk) {
    dom.confirmOk.addEventListener('click', () => confirm._handleOk());
}
if (dom.confirmOverlay) {
    dom.confirmOverlay.addEventListener('click', e => {
        if (e.target === dom.confirmOverlay) confirm.hide();
    });
}

// ── Visibility change (background → foreground recovery) ─────
document.addEventListener('visibilitychange', () => {
    if (document.hidden) return;
    if (!state.currentConvId) return;

    const stream = getStream();
    if (stream.isLive()) return;

    console.log('[app] Visibility change — recovering state for conv=%s',
        state.currentConvId.slice(0, 8));

    api.getMessages(state.currentConvId).then(d => {
        if (!d || !d.messages || !d.messages.length) return;
        events.emit('render:refresh', { messages: d.messages, streaming: d.streaming });
        notify.push('↻ 已恢复', '');
        const folds = document.querySelectorAll('.thinking-fold');
        if (folds.length) folds[folds.length - 1].classList.add('open');
        const mc = dom.messagesContainer;
        if (mc) mc.scrollTop = mc.scrollHeight;
    }).catch(() => {
        console.log('[app] Visibility recovery failed — starting polling');
        getStream().onDisconnect();
    });
});

// ── Network connectivity ──────────────────────────────────────
window.addEventListener('online', () => {
    if (!state.currentConvId) return;
    notify.push('网络已恢复', '');
    api.getMessages(state.currentConvId).then(d => {
        if (d && d.messages && d.messages.length) {
            events.emit('render:refresh', { messages: d.messages, streaming: d.streaming });
        }
    }).catch(() => {});
});

window.addEventListener('offline', () => {
    notify.push('网络已断开', 'error');
});

// ═══════════════════════════════════════════════════════════════
// 3. System event polling (30s)
// ═══════════════════════════════════════════════════════════════
// BUGFIX #1: 使用正斜杠 URL

(function _startEventPolling() {
    let _since = 0;

    setInterval(() => {
        api.get('/api/system/events?since=' + _since).then(d => {
            _since = d.next_since;
            (d.events || []).forEach(e => {
                notify.push(e.message, 'info');
            });
        }).catch(() => { /* silent */ });
    }, 30000);

    console.log('[app] System event polling started (30s interval)');
})();

// ═══════════════════════════════════════════════════════════════
// 4. Scroll-bottom button (lazy creation)
// ═══════════════════════════════════════════════════════════════

setTimeout(() => {
    const mc = dom.messagesContainer;
    if (!mc || mc.dataset.sbInit) return;
    mc.dataset.sbInit = '1';

    const btn = document.createElement('button');
    btn.className = 'scroll-bottom-btn';
    btn.textContent = '↓';
    btn.title = '回到底部';
    document.body.appendChild(btn);

    mc.addEventListener('scroll', () => {
        const dist = mc.scrollHeight - mc.scrollTop - mc.clientHeight;
        btn.classList.toggle('show', dist > 200);
    });
    btn.addEventListener('click', () => {
        mc.scrollTo({ top: mc.scrollHeight, behavior: 'smooth' });
    });

    console.log('[app] Scroll-bottom button created');
}, 1000);

// ═══════════════════════════════════════════════════════════════
// 5. Service Worker (PWA — registration only, no settings UI)
// ═══════════════════════════════════════════════════════════════

if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js', { scope: '/' })
        .then(() => console.log('[app] Service Worker registered'))
        .catch(err => console.warn('[app] SW registration failed:', err));
}

// ═══════════════════════════════════════════════════════════════
// 6. Auto-login
// ═══════════════════════════════════════════════════════════════

if (state.secret) {
    // notify.push('正在连接服务器...');
    console.log('[app] Auto-login — secret found, showing chat screen');
    setTimeout(() => settingsScreen.showChatScreen(), 0);
} else {
    console.log('[app] No saved secret — showing login screen');
}

console.log('[app] Ready — %s modules loaded', 14);
