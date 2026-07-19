// ═══════════════════════════════════════════════════════════════
// render/messages.js — Message rendering + status bar + scroll
// ═══════════════════════════════════════════════════════════════
//
// BUGFIX #4: img onerror handler 用 data-download-url 属性而非字符串拼接。
//
// 依赖: markdown, thinking, api, dom, escHtml, fmtNum
// 被依赖: chat, sidebar (switchConversation), stream (polling)
//
// 用法:
//   import { renderMessages, appendMessage, updateStatus, scrollMessages } from './render/messages.js';
// ═══════════════════════════════════════════════════════════════

import { api } from '../services/api.js';
import { dom } from '../core/dom.js';
import { events } from '../core/events.js';
import { escHtml, fmtNum } from '../utils/html.js';
import { renderMarkdown } from './markdown.js';
import {
    addThinkingFold, updateThinkingFold, updateThinkingLabel, removeThinkingFold,
} from './thinking.js';

// ── 工具动词映射 ─────────────────────────────────────────────
const TOOL_VERBS = {
    'Read':        'Reading',
    'Glob':        'Scanning',
    'Grep':        'Searching',
    'Bash':        'Bashing',
    'PowerShell':  'Executing',
    'Edit':        'Editing',
    'Write':       'Writing',
    'WebSearch':   'Crawling',
    'WebFetch':    'Fetching',
    'Task':        'Dispatching',
    'Agent':       'Dispatching',
    'TodoWrite':   'Planning',
    'TaskCreate':  'Planning',
};

// ═══════════════════════════════════════════════════════════════
// 全局 helper (onerror / onclick → 挂 window, 保持兼容)
// ═══════════════════════════════════════════════════════════════

/** BUGFIX #4: img onerror → 替换为下载链接 */
window._gwImgError = function (img) {
    const durl = img.getAttribute('data-download-url');
    if (!durl) {
        img.outerHTML = '<span class="download-card">📄 (无法加载)</span>';
        return;
    }
    const name = img.getAttribute('alt') || 'file';
    img.outerHTML = '<a class="download-card" href="' + durl + '">'
        + '📄 ' + escHtml(name) + ' ⬇ 下载</a>';
};

/** 图片全屏查看 */
window._gwViewImage = function (src) {
    const overlay = document.createElement('div');
    overlay.className = 'image-overlay';
    const img = document.createElement('img');
    img.className = 'image-full';
    img.src = src;
    overlay.appendChild(img);
    overlay.addEventListener('click', () => overlay.remove());
    document.body.appendChild(overlay);
};

console.log('[render/messages] Global helpers registered (_gwImgError, _gwViewImage)');

// ═══════════════════════════════════════════════════════════════
// 公共 API
// ═══════════════════════════════════════════════════════════════

/**
 * 全量渲染消息列表 (切换对话时使用)。
 * @param {Array}  msgs      — message objects
 * @param {Object} streaming — { msg_id, status, thinking, content } or null
 */
export function renderMessages(msgs, streaming) {
    const container = dom.messagesContainer;
    if (!container) return;
    container.innerHTML = '';

    const streamingMsgId = streaming ? streaming.msg_id : null;
    console.log('[render] renderMessages: %s msgs, streaming=%s',
        msgs.length, streamingMsgId || 'none');

    for (const msg of msgs) {
        const isStreaming = streamingMsgId != null && msg.id === streamingMsgId;
        const files = _parseFileIds(msg.file_ids);
        appendMessage(msg, files, isStreaming);
    }

    events.emit('chat:updateWelcome');

    // Multiple scroll attempts for paint timing
    [100, 300, 600].forEach(d => setTimeout(scrollMessages, d));
}

/**
 * 追加单条消息到容器。
 * @param {Object}  msg       — { role, content, thinking, thinking_dur, thinking_wc, token_usage, created_at, id }
 * @param {Array}   [files]   — [{ name, file_id, preview }]
 * @param {boolean} [streaming] — true = 流式进行中
 * @returns {Element|null}
 */
export function appendMessage(msg, files, streaming) {
    const container = dom.messagesContainer;
    if (!container) return null;

    const el = document.createElement('div');
    el.className = 'msg ' + msg.role + (streaming ? ' streaming' : '');

    // ── 文件 badges ───────────────────────────────────────
    if (files && files.length) {
        const b = document.createElement('div');
        b.className = 'file-badges';
        b.innerHTML = files.map(f => {
            let chip = '<span class="file-badge">📎 ' + escHtml(f.name) + '</span>';
            if (f.preview) {
                chip += '<img class="user-upload-preview" src="' + f.preview
                    + '" alt="' + escHtml(f.name) + '"'
                    + ' onclick="window._gwViewImage(this.src)">';
            }
            return chip;
        }).join('');
        el.appendChild(b);
    }

    // ── 状态栏 (streaming only) ───────────────────────────
    if (streaming && msg.role === 'assistant') {
        const sb = document.createElement('div');
        sb.className = 'status-bar';
        sb.innerHTML = '<span class="thinking-dots"><span></span><span></span><span></span></span>  Thinking...';
        el.appendChild(sb);
    }

    // ── 思考折叠 ──────────────────────────────────────────
    if (msg.role === 'assistant' && msg.thinking) {
        addThinkingFold(el, msg.thinking, msg.thinking_dur, msg.thinking_wc);
        if (streaming) {
            const fold = el.querySelector('.thinking-fold');
            if (fold) fold.classList.add('open');
        }
    }

    // ── 正文 ──────────────────────────────────────────────
    const cd = document.createElement('div');
    cd.className = 'msg-content';
    if (streaming) {
        cd.textContent = msg.content || '';
    } else {
        cd.innerHTML = renderMarkdown(msg.content || '', api);
    }
    el.appendChild(cd);

    // ── Footer (timestamp + token) ────────────────────────
    if (msg.created_at && !streaming) {
        const ft = document.createElement('div');
        ft.className = 'msg-footer';
        let tu = '';
        if (msg.token_usage) {
            try {
                const u = JSON.parse(msg.token_usage);
                tu = '<span class="token-info">↑ ' + fmtNum(u.i) + '   ↓ ' + fmtNum(u.o) + '</span>';
            } catch (e) { /* ignore parse error */ }
        }
        ft.innerHTML = tu + '<span class="timestamp">' + new Date(msg.created_at).toLocaleTimeString() + '</span>';
        el.appendChild(ft);
        el._footer = ft;
    }

    container.appendChild(el);
    requestAnimationFrame(() => el.classList.add('msg-enter'));
    scrollMessages();
    return el;
}

/**
 * 更新流式消息的状态栏。
 * @param {Element} el     — .status-bar 元素
 * @param {string}  type   — 'thinking' | 'text' | 'tool' | 'done'
 * @param {string}  [tool] — 工具名称 (type='tool' 时)
 */
export function updateStatus(el, type, tool) {
    if (!el) return;
    const dots = '<span class="thinking-dots"><span></span><span></span><span></span></span>';
    if (type === 'thinking')       el.innerHTML = dots + '  Thinking...';
    else if (type === 'text')      el.innerHTML = dots + '  Writing...';
    else if (type === 'tool')      el.innerHTML = dots + '  ' + (TOOL_VERBS[tool] || tool) + '...';
    else if (type === 'done')      el.innerHTML = dots + '  Done.';
}

/**
 * 滚动消息容器到底部。
 */
export function scrollMessages() {
    const container = dom.messagesContainer;
    if (container) container.scrollTop = container.scrollHeight;
}

// ═══════════════════════════════════════════════════════════════
// 内部 helpers
// ═══════════════════════════════════════════════════════════════

/**
 * 解析消息的 file_ids JSON 字段。
 * @param {string|null} fileIdsJson
 * @returns {Array|null}
 */
function _parseFileIds(fileIdsJson) {
    if (!fileIdsJson) return null;
    try {
        const ids = JSON.parse(fileIdsJson);
        if (!Array.isArray(ids) || !ids.length) return null;
        return ids.map(f => {
            const name = typeof f === 'string' ? f : (f.name || f.id || '');
            const isImg = /\.(png|jpe?g|gif|webp|bmp)$/i.test(name);
            return {
                name,
                file_id: typeof f === 'string' ? f : (f.id || ''),
                preview: isImg ? api.fileViewUrl(name) : null,
            };
        });
    } catch (e) {
        return null;
    }
}
