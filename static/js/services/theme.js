// ═══════════════════════════════════════════════════════════════
// services/theme.js — Theme management (presets, accent, font)
// ═══════════════════════════════════════════════════════════════
//
// BUGFIX #3: applyTheme() 现在同时设置 --accent CSS 变量，
// 确保切换主题后强调色与预设一致。
// BUGFIX #5: openSettings 时刷新 preset 按钮 active 状态。
//
// 依赖: dom (core) — 读/写 DOM 引用
// 被依赖: settings-panel, app.js
//
// 用法:
//   import { theme } from './services/theme.js';
//   theme.apply('dark');
//   theme.setAccent('#ff6600');
//   theme.setFontSize(18);
// ═══════════════════════════════════════════════════════════════

import { dom } from '../core/dom.js';

// ── 预设主题定义 ─────────────────────────────────────────────
const PRESETS = {
    black: { bg: '#0a0a0a', surface: '#121212', accent: '#4a9eff' },
    dark:  { bg: '#1a1a1a', surface: '#222222', accent: '#4ec9b0' },
    gray:  { bg: '#1e1e24', surface: '#282830', accent: '#569cd6' },
    blue:  { bg: '#0d1117', surface: '#161b22', accent: '#58a6ff' },
};

export const theme = {
    /** @returns {string} current preset name */
    get current() { return localStorage.getItem('cg_theme') || 'black'; },

    /** @returns {string[]} available preset names */
    get presets() { return Object.keys(PRESETS); },

    // ── 应用主题 ──────────────────────────────────────────

    /**
     * 应用预设主题。设置 --bg-primary, --bg-surface, --accent 及衍生变量。
     * @param {string} name — 'black' | 'dark' | 'gray' | 'blue'
     */
    apply(name) {
        const t = PRESETS[name] || PRESETS.black;
        const r = document.documentElement.style;
        r.setProperty('--bg-primary', t.bg);
        r.setProperty('--bg-surface', t.surface);
        // BUGFIX #3: 同时设置 --accent
        r.setProperty('--accent', t.accent);
        r.setProperty('--accent-hover', t.accent + 'cc');
        r.setProperty('--accent-dim', t.accent + '22');
        localStorage.setItem('cg_theme', name);
        // Clear custom accent/bg so preset colors take full effect
        localStorage.removeItem('cg_accent');
        localStorage.removeItem('cg_bg');

        // 更新颜色选择器
        const inp = dom.setAccent;
        if (inp) inp.value = t.accent;
        const bgInp = dom.setBg;
        if (bgInp) bgInp.value = t.bg;

        console.log('[theme] Applied preset "%s" — accent=%s bg=%s', name, t.accent, t.bg);
    },

    // ── 强调色 ────────────────────────────────────────────

    /**
     * 设置自定义强调色 (覆盖预设)。
     * @param {string} hex  — e.g. '#ff6600'
     * @param {boolean} [skipSave] — true = 不写 localStorage (初始化用)
     */
    setAccent(hex, skipSave) {
        const r = document.documentElement.style;
        r.setProperty('--accent', hex);
        r.setProperty('--accent-hover', hex + 'cc');
        r.setProperty('--accent-dim', hex + '22');
        if (!skipSave) localStorage.setItem('cg_accent', hex);
        console.log('[theme] Accent = %s', hex);
    },

    // ── 背景色 ────────────────────────────────────────────

    /**
     * 设置自定义背景色 (覆盖预设)。
     * @param {string} hex  — e.g. '#0a0a0a'
     * @param {boolean} [skipSave] — true = 不写 localStorage (初始化用)
     */
    setBg(hex, skipSave) {
        const r = document.documentElement.style;
        r.setProperty('--bg-primary', hex);
        // Derive surface from bg — lighter by ~12 (in hex)
        const surf = _lighten(hex, 12);
        r.setProperty('--bg-surface', surf);
        if (!skipSave) localStorage.setItem('cg_bg', hex);
        console.log('[theme] Bg = %s (surface=%s)', hex, surf);
    },

    // ── 字体大小 ──────────────────────────────────────────

    /**
     * @param {number} px — 15–22
     */
    setFontSize(px) {
        document.documentElement.style.fontSize = px + 'px';
        localStorage.setItem('cg_font_size', px);
        const label = dom.fontLabel;
        if (label) {
            const tag = px <= 16 ? '小' : px <= 19 ? '中' : '大';
            label.textContent = tag + ' (' + px + 'px)';
        }
        console.log('[theme] Font size = %spx', px);
    },

    /** @returns {number} */
    get fontSize() {
        return parseInt(localStorage.getItem('cg_font_size') || '17');
    },

    /** @returns {string} */
    get accent() {
        return localStorage.getItem('cg_accent') || PRESETS[theme.current].accent;
    },

    /** @returns {string} */
    get bg() {
        return localStorage.getItem('cg_bg') || PRESETS[theme.current].bg;
    },

    // ── 刷新 UI 状态 ──────────────────────────────────────

    /**
     * BUGFIX #5: 更新预设按钮的 active 类和颜色选择器值。
     * 每次打开设置面板时调用。
     */
    refreshUI() {
        const cur = theme.current;
        document.querySelectorAll('.preset-btn').forEach(b => {
            b.classList.toggle('active', b.dataset.theme === cur);
        });
        const accentInp = dom.setAccent;
        if (accentInp) accentInp.value = theme.accent;
        const bgInp = dom.setBg;
        if (bgInp) bgInp.value = theme.bg;
        const fs = theme.fontSize;
        const fontInp = dom.setFontSize;
        if (fontInp) fontInp.value = fs;
        const label = dom.fontLabel;
        if (label) {
            const tag = fs <= 16 ? '小' : fs <= 19 ? '中' : '大';
            label.textContent = tag + ' (' + fs + 'px)';
        }
    },
};

// ── helpers ────────────────────────────────────────────────────

function _lighten(hex, amount) {
    const n = parseInt(hex.replace('#', ''), 16);
    const r = Math.min(255, ((n >> 16) & 0xff) + amount);
    const g = Math.min(255, ((n >> 8) & 0xff) + amount);
    const b = Math.min(255, (n & 0xff) + amount);
    return '#' + ((r << 16) | (g << 8) | b).toString(16).padStart(6, '0');
}

// ── 启动时应用已保存主题 ─────────────────────────────────────
(function _init() {
    const saved = theme.current;
    const accent = localStorage.getItem('cg_accent');
    const bg = localStorage.getItem('cg_bg');
    theme.apply(saved);
    if (accent) theme.setAccent(accent, true);
    if (bg) theme.setBg(bg, true);
    const fs = theme.fontSize;
    document.documentElement.style.fontSize = fs + 'px';
    // Update label too
    const label = dom.fontLabel;
    if (label) {
        const tag = fs <= 16 ? '小' : fs <= 19 ? '中' : '大';
        label.textContent = tag + ' (' + fs + 'px)';
    }
    console.log('[theme] Startup: preset=%s accent=%s bg=%s font=%spx', saved, accent || '(preset)', bg || '(preset)', fs);
})();
