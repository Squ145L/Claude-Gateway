// ═══════════════════════════════════════════════════════════════
// render/markdown.js — Markdown → HTML (pure function)
// ═══════════════════════════════════════════════════════════════
//
// BUGFIX #4: onerror 属性中的 URL 现在用 data-* 属性存储，
// 避免文件名含特殊字符时破坏 HTML 引号结构。
//
// 依赖: escHtml (utils/html), api.fileDownloadUrl / fileViewUrl (services/api)
// 特点: 纯函数 — 输入 text + helpers, 输出 HTML 字符串, 无副作用
//
// 用法:
//   import { renderMarkdown } from './render/markdown.js';
//   const html = renderMarkdown(text, api);
// ═══════════════════════════════════════════════════════════════

import { escHtml } from '../utils/html.js';

/**
 * @param {string} text  — raw markdown-ish text
 * @param {object} api   — { fileDownloadUrl, fileViewUrl } 或其 mock
 * @returns {string} HTML
 */
export function renderMarkdown(text, api) {
    if (!text) return '';

    let h = escHtml(text);

    // [DOWNLOAD:filename] → download card
    h = h.replace(/\[DOWNLOAD:([^\]]+)\]/g, (_, name) => {
        const url = api.fileDownloadUrl(name);
        return '<a class="download-card" href="' + url + '" download="' + escHtml(name) + '">'
            + '<span class="file-icon">&#128196;</span>'
            + '<span class="file-name">' + escHtml(name) + '</span>'
            + '<span class="file-action">&#8595; 下载</span></a>';
    });

    // [FILE:filename] — images inline, others download card
    // BUGFIX #4: onerror 使用 data-url 属性 + 事件委托，避免字符串拼接破坏引号
    h = h.replace(/\[FILE:([^\]]+)\]/g, (_, name) => {
        const isImg = /\.(png|jpe?g|gif|webp|bmp)$/i.test(name);
        if (isImg) {
            const vurl = api.fileViewUrl(name);
            const durl = api.fileDownloadUrl(name);
            return '<img class="chat-image" src="' + vurl + '" alt="' + escHtml(name) + '"'
                + ' loading="lazy"'
                + ' data-download-url="' + durl + '"'
                + ' onclick="window._gwViewImage(this.src)"'
                + ' onerror="window._gwImgError(this)">';
        }
        const durl = api.fileDownloadUrl(name);
        return '<a class="download-card" href="' + durl + '" download="' + escHtml(name) + '">'
            + '<span class="file-icon">&#128196;</span>'
            + '<span class="file-name">' + escHtml(name) + '</span>'
            + '<span class="file-action">&#8595; 下载</span></a>';
    });

    // Code blocks
    h = h.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
        return '<pre><code>' + code.trim() + '</code></pre>';
    });

    // Tables
    h = h.replace(/((?:^\|.+\|$\n?)+)/gm, m => {
        const lines = m.trim().split('\n');
        if (lines.length < 2) return m;
        const sep = /^\|[\s\-:|]+\|$/;
        if (!lines.some(x => sep.test(x))) return m;
        const rows = [];
        for (let i = 0; i < lines.length; i++) {
            if (sep.test(lines[i])) continue;
            const cells = lines[i].split('|').slice(1, -1);
            const tag = i === 0 ? 'th' : 'td';
            rows.push('<tr>' + cells.map(x => '<' + tag + '>' + x.trim() + '</' + tag + '>').join('') + '</tr>');
        }
        return rows.length ? '<table>' + rows.join('') + '</table>' : m;
    });

    // Inline
    h = h.replace(/`([^`]+)`/g, '<code>$1</code>');
    h = h.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

    // Headings
    h = h.replace(/^### (.+)$/gm, '<h4>$1</h4>');
    h = h.replace(/^## (.+)$/gm, '<h3>$1</h3>');
    h = h.replace(/^# (.+)$/gm, '<h2>$1</h2>');

    // Lists
    h = h.replace(/^[*-] (.+)$/gm, '<li>$1</li>');
    h = h.replace(/((?:<li>.*<\/li>\n?)+)/g, '<ul>$1</ul>');

    // Paragraphs
    h = h.replace(/\n\n/g, '</p><p>');
    h = h.replace(/\n/g, '<br>');
    h = '<p>' + h + '</p>';
    h = h.replace(/<p>\s*<\/p>/g, '');

    return h;
}

console.log('[render/markdown] Initialized');
