// ═══════════════════════════════════════════════════════════════
// render/thinking.js — Thinking fold helpers
// ═══════════════════════════════════════════════════════════════
//
// 创建和控制消息中的"思考过程"可折叠区域。
//
// 依赖: escHtml (utils/html)
// 被依赖: render/messages, components/chat
//
// 用法:
//   import { addThinkingFold, updateThinkingFold, updateThinkingLabel, removeThinkingFold } from './render/thinking.js';
// ═══════════════════════════════════════════════════════════════

import { escHtml } from '../utils/html.js';

/**
 * 在消息元素中插入思考折叠。
 * @param {Element} el      — .msg 元素
 * @param {string}  text    — 思考文本
 * @param {string}  [dur]   — 思考时长 "1.2s" / "1m 30s"
 * @param {number}  [wc]    — 词数
 */
export function addThinkingFold(el, text, dur, wc) {
    if (!wc) wc = text.split(/\s+/).filter(Boolean).length;
    const label = dur ? '已思考(' + dur + ') — ' + wc + ' words' : wc + ' words';

    const fold = document.createElement('div');
    fold.className = 'thinking-fold';
    fold.innerHTML =
        '<div class="thinking-header" onclick="this.parentElement.classList.toggle(\'open\')">'
        + '<span>' + escHtml(label) + '</span></div>'
        + '<div class="thinking-content">' + escHtml(text) + '</div>';

    const contentEl = el.querySelector('.msg-content');
    el.insertBefore(fold, contentEl);
}

/**
 * 更新思考折叠内容 (流式生成中用)。
 * @param {Element} el
 * @param {string}  text
 */
export function updateThinkingFold(el, text) {
    let fold = el.querySelector('.thinking-fold');
    if (!fold) {
        addThinkingFold(el, text);
        return;
    }
    fold.querySelector('.thinking-content').textContent = text;
}

/**
 * 更新思考折叠标签 (从 "X words" → "已思考(1.2s) — X words")。
 * @param {Element} el
 * @param {string}  dur
 * @param {number}  wc
 */
export function updateThinkingLabel(el, dur, wc) {
    const hdr = el.querySelector('.thinking-header');
    if (hdr) {
        hdr.innerHTML = '<span>已思考(' + dur + ') — ' + wc + ' words</span>';
    }
}

/**
 * 从消息元素中移除思考折叠。
 * @param {Element} el
 */
export function removeThinkingFold(el) {
    const f = el.querySelector('.thinking-fold');
    if (f) f.remove();
}

console.log('[render/thinking] Initialized');
