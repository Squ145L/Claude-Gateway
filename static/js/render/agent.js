// ═══════════════════════════════════════════════════════════════
// render/agent.js — Agent result fold helpers
// ═══════════════════════════════════════════════════════════════
//
// 在消息中创建/更新可折叠的 agent 结果区域，复用 thinking-fold 模式。
//
// 依赖: escHtml (utils/html)
// 被依赖: components/chat (SSE agent_result 消费)
//
// 用法:
//   import { addAgentFold, updateAgentFold } from './render/agent.js';
// ═══════════════════════════════════════════════════════════════

import { escHtml } from '../utils/html.js';

/**
 * 在消息元素中插入 agent 结果折叠。
 * @param {Element} el      — .msg 元素
 * @param {string}  content — agent 输出文本
 * @param {string}  [label] — 折叠标题，默认 "Agent result"
 */
export function addAgentFold(el, content, label) {
    const title = label || 'Agent result';

    const fold = document.createElement('div');
    fold.className = 'agent-fold';
    fold.innerHTML =
        '<div class="agent-fold-header" onclick="this.parentElement.classList.toggle(\'open\')">'
        + '<span>&#x1F527; ' + escHtml(title) + '</span></div>'
        + '<div class="agent-fold-content">' + escHtml(content) + '</div>';

    const contentEl = el.querySelector('.msg-content');
    if (contentEl) {
        el.insertBefore(fold, contentEl);
    } else {
        el.appendChild(fold);
    }
}

/**
 * 更新 agent 折叠内容（追加模式，用于流式场景）。
 * @param {Element} el
 * @param {string}  content — 新内容（追加到已有内容后）
 * @param {string}  [label]
 */
export function updateAgentFold(el, content, label) {
    let fold = el.querySelector('.agent-fold');
    if (!fold) {
        addAgentFold(el, content, label);
        return;
    }
    if (label) {
        const hdr = fold.querySelector('.agent-fold-header span');
        if (hdr) hdr.textContent = '\u{1F527} ' + label;
    }
    const body = fold.querySelector('.agent-fold-content');
    if (body) body.textContent += content;
}

console.log('[render/agent] Initialized');
