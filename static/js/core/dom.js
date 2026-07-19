// ═══════════════════════════════════════════════════════════════
// core/dom.js — Lazy DOM cache singleton
// ═══════════════════════════════════════════════════════════════
//
// 每个 DOM 元素只在第一次访问时查询一次，之后从缓存返回。
// 消除全局散落的 querySelector 调用，统一管理所有 DOM 引用。
//
// 依赖: 零
// 被依赖: toast, 所有 components, render/*
//
// 用法:
//   import { dom } from './core/dom.js';
//   dom.settingsPanel.classList.remove('hidden');
//   dom.msgInput.focus();
//
// 规则:
//   - 静态元素 (HTML 渲染后就存在的): 直接 getter
//   - 动态元素 (JS 创建的): 用 dom.rebind('key', element) 更新缓存
// ═══════════════════════════════════════════════════════════════

const _cache = {};   // { key: Element }

export const dom = new Proxy({}, {
    get(_, key) {
        // 方法调用
        if (key === 'rebind')  return _rebind;
        if (key === 'invalidate') return _invalidate;
        if (key === 'debug') return () => Object.keys(_cache);

        // 懒查询
        if (_cache[key] !== undefined) return _cache[key];

        const sel = SELECTORS[key];
        if (!sel) {
            console.warn('[dom] Unknown key: "%s" — add it to SELECTORS in dom.js', key);
            return undefined;
        }
        const el = document.querySelector(sel);
        _cache[key] = el;
        if (!el) {
            console.warn('[dom] Not found: "%s" → %s', key, sel);
        }
        return el;
    },
});

// ── 选择器注册表 ─────────────────────────────────────────────
// key → CSS selector
const SELECTORS = {
    // Screens
    settingsScreen:  '#settings-screen',
    chatScreen:      '#chat-screen',

    // Settings (login) screen
    authSecret:      '#auth-secret',
    connectBtn:      '#connect-btn',
    connectStatus:   '#connect-status',

    // Chat header
    menuBtn:         '#menu-btn',
    currentTitle:    '#current-title',
    settingsBtn:     '#settings-btn',

    // Messages
    messagesContainer: '#messages-container',
    welcomeScreen:   '#welcome-screen',
    composeBar:      '#compose-bar',

    // Compose
    msgInput:        '#msg-input',
    sendBtn:         '#send-btn',
    plusBtn:         '#plus-btn',

    // Welcome
    welcomeInput:    '#welcome-input',
    welcomeStatus:   '#welcome-status',
    welcomeSendBtn:  '#welcome-send-btn',
    welcomePlusBtn:  '#welcome-plus-btn',

    // File inputs
    cameraInput:     '#camera-input',
    albumInput:      '#album-input',
    fileInput:       '#file-input',

    // File preview
    filePreviewBar:  '#file-preview-bar',

    // Action sheet
    actionSheet:        '#action-sheet',
    actionSheetOverlay: '#action-sheet-overlay',
    actionCancel:       '#action-cancel',
    actionCamera:       '#action-camera',
    actionAlbum:        '#action-album',
    actionFile:         '#action-file',
    actionStatus:       '#action-status',

    // Sidebar
    sidebar:         '#sidebar',
    sidebarOverlay:  '#sidebar-overlay',
    conversationList: '#conversation-list',
    newChatBtn:      '#new-chat-btn',
    convSearch:      '#conv-search',

    // Batch
    batchBtn:        '#batch-btn',
    batchBar:        '#batch-bar',
    batchCount:      '#batch-count',
    batchDeleteBtn:  '#batch-delete-btn',
    batchCancelBtn:  '#batch-cancel-btn',

    // Context menu
    ctxMenu:         '#ctx-menu',
    ctxOverlay:      '#ctx-overlay',
    ctxRename:       '#ctx-rename',
    ctxDelete:       '#ctx-delete',
    ctxPin:          '#ctx-pin',

    // Settings panel
    settingsPanel:   '#settings-panel',
    settingsOverlay: '#settings-overlay',
    settingsCloseBtn:'#settings-close-btn',
    settingsBody:    '.settings-body',

    // Settings — connection
    setServerUrl:    '#set-server-url',
    setSecret:       '#set-secret',
    saveConnBtn:     '#save-conn-btn',

    // Settings — theme
    setAccent:       '#set-accent',
    setBg:           '#set-bg',
    setFontSize:     '#set-font-size',
    fontLabel:       '#font-label',

    // Settings — file
    fileInfo:        '#file-info',
    setFileDir:      '#set-file-dir',
    setMaxFsize:     '#set-max-fsize',

    // Settings — system
    sysInfo:         '#sys-info',
    sysInfoLine:     '#sys-info-line',
    sysPort:         '#sys-port',
    setTimeoutEl:    '#set-timeout',
    setMirrorEl:     '#set-mirror',
    setIdleEl:       '#set-idle-timeout',
    sysClearLogs:    '#sys-clear-logs',
    sysCleanCache:   '#sys-clean-cache',
    sysViewLogs:     '#sys-view-logs',
    sysSoftRestart:  '#sys-soft-restart',
    sysClearConvs:   '#sys-clear-convs',
    sysRestart:      '#sys-restart',
    sysLogViewer:    '#sys-log-viewer',

    // Settings — system actions
    sysMigrateImages:'#sys-migrate-images',
    sysForceRefresh: '#sys-force-refresh',

    // Confirm
    confirmOverlay:  '#confirm-overlay',
    confirmMsg:      '#confirm-msg',
    confirmOk:       '#confirm-ok',
    confirmCancel:   '#confirm-cancel',

    // Notify
    notifyStack:     '#notify-stack',
};

// ── 方法 ──────────────────────────────────────────────────────

/**
 * 手动绑定 / 更新缓存中的元素引用。
 * 用于 JS 动态创建的节点 (如滚动按钮)。
 */
function _rebind(key, el) {
    if (!SELECTORS[key]) {
        console.warn('[dom] rebind unknown key: "%s"', key);
    }
    _cache[key] = el;
    console.log('[dom] rebind("%s")', key);
}

/**
 * 清除指定 key 的缓存 (下次访问时重新查询 DOM)。
 * @param {string} [key] — 省略则清除全部
 */
function _invalidate(key) {
    if (key) {
        delete _cache[key];
        console.log('[dom] invalidate("%s")', key);
    } else {
        Object.keys(_cache).forEach(k => delete _cache[k]);
        console.log('[dom] invalidate(all) — %s keys cleared', Object.keys(_cache).length);
    }
}

console.log('[dom] Initialized — %s selectors registered', Object.keys(SELECTORS).length);
