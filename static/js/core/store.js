// ═══════════════════════════════════════════════════════════════
// core/store.js — Reactive state store
// ═══════════════════════════════════════════════════════════════
//
// 单一状态源。任何模块可通过 state.x 读取、state.on('x', fn) 订阅、
// state.set('x', val) 写入。写入时自动通知订阅者。
//
// 依赖: 零 (不 import 任何模块)
// 被依赖: api, stream, 所有 components
//
// 用法:
//   import { state } from './core/store.js';
//   const url = state.serverUrl;          // 读
//   state.on('serverUrl', (v) => {...});  // 订阅
//   state.set('serverUrl', 'http://...'); // 写 (触发通知)
// ═══════════════════════════════════════════════════════════════

const _listeners = {};  // { key: [callback, ...] }
const _data = {};        // { key: value }

/**
 * Reactive state proxy.
 * - Read:  state.foo  → returns _data.foo
 * - Write: state.foo = val  → calls state.set('foo', val)
 * - Subscribe: state.on('foo', callback)
 */
export const state = new Proxy(_data, {
    get(_, key) {
        if (key === 'on')  return _on;
        if (key === 'set') return _set;
        if (key === 'off') return _off;
        if (key === 'snapshot') return () => ({ ..._data });
        return _data[key];
    },
    set(_, key, value) {
        _set(key, value);
        return true;
    },
});

// ── 初始化默认值 ──────────────────────────────────────────────
_set('serverUrl', localStorage.getItem('cg_server_url') || window.location.origin);
_set('secret',    localStorage.getItem('cg_secret') || '');
_set('currentConvId', null);
_set('pendingFiles',  []);
_set('batchMode',     false);
_set('selectedConvs', {});
_set('confirmCallback', null);
_set('ctxTarget',       null);
_set('isMobile', /Mobi|Android/i.test(navigator.userAgent) || ('ontouchstart' in window && window.innerWidth < 768));
_set('isTouch',  ('ontouchstart' in window || navigator.maxTouchPoints > 0));

// 首次使用没有 URL 时，默认当前 origin
if (!localStorage.getItem('cg_server_url')) {
    localStorage.setItem('cg_server_url', state.serverUrl);
}

console.log('[store] Initialized — serverUrl=%s, hasSecret=%s',
    state.serverUrl, Boolean(state.secret));

// ── 订阅 / 取消 / 写入 ───────────────────────────────────────

function _on(key, fn) {
    (_listeners[key] = _listeners[key] || []).push(fn);
    console.log('[store] on("%s") — %s listener(s)', key, _listeners[key].length);
}

function _off(key, fn) {
    const arr = _listeners[key];
    if (!arr) return;
    _listeners[key] = arr.filter(f => f !== fn);
}

function _set(key, value) {
    const old = _data[key];
    if (old === value) return;          // 无变化, 不通知
    _data[key] = value;
    console.log('[store] set("%s") = %s', key,
        typeof value === 'string' ? value.slice(0, 60) : JSON.stringify(value).slice(0, 60));
    (_listeners[key] || []).forEach(fn => {
        try { fn(value, old); }
        catch (e) { console.error('[store] listener error for "%s":', key, e); }
    });
}
