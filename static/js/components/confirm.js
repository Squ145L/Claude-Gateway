// ═══════════════════════════════════════════════════════════════
// components/confirm.js — Confirmation dialog
// ═══════════════════════════════════════════════════════════════
//
// 依赖: dom
// 被依赖: sidebar (删除对话), settings-panel (系统操作), app
//
// 用法:
//   import { confirm } from './components/confirm.js';
//   confirm.show('确定删除？', () => { ... }, '删除');
// ═══════════════════════════════════════════════════════════════

import { dom } from '../core/dom.js';

let _callback = null;

export const confirm = {
    /**
     * @param {string}   msgHtml  — 提示 HTML
     * @param {function} cb       — 确定回调
     * @param {string}   [okText] — 确定按钮文字 (默认 "确定")
     */
    show(msgHtml, cb, okText) {
        _callback = cb;
        if (dom.confirmMsg) dom.confirmMsg.innerHTML = msgHtml;
        if (dom.confirmOk) dom.confirmOk.textContent = okText || '确定';
        if (dom.confirmOverlay) dom.confirmOverlay.classList.remove('hidden');
        console.log('[confirm] Shown — okText=%s', okText || '确定');
    },

    hide() {
        _callback = null;
        if (dom.confirmOverlay) dom.confirmOverlay.classList.add('hidden');
    },

    /** 触发确定回调 (由 app.js 中的事件调用) */
    _handleOk() {
        const cb = _callback;
        this.hide();
        if (cb) {
            console.log('[confirm] OK clicked — executing callback');
            cb();
        }
    },
};

console.log('[components/confirm] Initialized');
