// ═══════════════════════════════════════════════════════════════
// utils/html.js — Pure HTML utility functions
// ═══════════════════════════════════════════════════════════════
//
// 无副作用、无 DOM 访问的纯函数。可用于任何上下文。
//
// 依赖: 零
// ═══════════════════════════════════════════════════════════════

/**
 * HTML-escape user text to prevent XSS.
 * @param {string} t
 * @returns {string}
 */
export function escHtml(t) {
    const d = document.createElement('div');
    d.textContent = t;
    return d.innerHTML;
}

/**
 * Format a number: ≥1000 → "1.2k", else string.
 * @param {number} n
 * @returns {string}
 */
export function fmtNum(n) {
    return n >= 1000 ? (n / 1000).toFixed(1) + 'k' : String(n);
}

console.log('[utils/html] Initialized');
