// ═══════════════════════════════════════════════════════════════
// services/api.js — HTTP + SSE + file URL helpers
// ═══════════════════════════════════════════════════════════════
//
// 所有网络请求的单一入口。纯函数，不碰 DOM。
// 错误消息映射表集中管理。
//
// 依赖: store (读 serverUrl, secret)
// 被依赖: 所有组件
//
// 用法:
//   import { api } from './services/api.js';
//   const data = await api.get('/api/system/info');
//   const resp  = await api.streamChat('hello', []);
// ═══════════════════════════════════════════════════════════════

import { state } from '../core/store.js';

// ── 错误消息映射 ─────────────────────────────────────────────
const ERRORS = {
    400: '请求有误',
    401: '密钥错误',
    404: '未找到',
    413: '文件过大',
    429: '请求太频繁',
    500: '服务器内部错误',
    502: '服务器未开启',
    503: '服务器繁忙',
    504: '连接超时',
};

// ═══════════════════════════════════════════════════════════════
// 公共 API
// ═══════════════════════════════════════════════════════════════

export const api = {
    // ── 基础 HTTP ─────────────────────────────────────────

    /** GET → parsed JSON */
    get(path) {
        return fetch(_url(path), { headers: _headers() })
            .then(r => { if (!r.ok) throw new Error(_errMsg(r.status)); return r.json(); });
    },

    /** POST → parsed JSON */
    post(path, body) {
        return fetch(_url(path), {
            method: 'POST',
            headers: _headers(),
            body: JSON.stringify(body || {}),
        }).then(r => { if (!r.ok) throw new Error(_errMsg(r.status)); return r.json(); });
    },

    /** DELETE → parsed JSON (or {deleted: id}) */
    delete(path) {
        return fetch(_url(path), {
            method: 'DELETE',
            headers: _headers(),
        }).then(r => { if (!r.ok) throw new Error(_errMsg(r.status)); return r.json(); });
    },

    // ── SSE (返回原始 Response) ────────────────────────────

    /** POST /api/chat — returns fetch Response for SSE ReadableStream */
    streamChat(userText, fileIds) {
        return fetch(_url('/api/chat'), {
            method: 'POST',
            headers: _headers(),
            body: JSON.stringify({
                conversation_id: state.currentConvId,
                message: userText,
                file_ids: fileIds || [],
                show_thinking: true,
            }),
        });
    },

    // ── 专用端点 ──────────────────────────────────────────

    /** GET /api/conversations/{id} — messages + streaming state */
    getMessages(convId) {
        return api.get('/api/conversations/' + convId);
    },

    /** POST /api/auth/verify — 验证密钥 */
    verifySecret(secret) {
        return fetch(_url('/api/auth/verify'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ secret }),
        }).then(r => r.json());
    },

    /** POST /api/files/upload — 上传文件 (multipart) */
    uploadFile(file) {
        const fd = new FormData();
        fd.append('file', file);
        return fetch(_url('/api/files/upload'), {
            method: 'POST',
            headers: { 'Authorization': 'Bearer ' + state.secret },
            body: fd,
        }).then(r => r.json());
    },

    // ── 文件 URL 构造 (集中管理，消除渲染层重复拼 URL) ────

    /**
     * 文件下载 URL。
     * @param {string} filename
     * @returns {string}
     */
    fileDownloadUrl(filename) {
        return state.serverUrl + '/api/files/download/'
            + encodeURIComponent(filename)
            + '?token=' + encodeURIComponent(state.secret);
    },

    /**
     * 文件预览 URL (图片 inline)。
     * @param {string} filename
     * @returns {string}
     */
    fileViewUrl(filename) {
        return state.serverUrl + '/api/files/view/'
            + encodeURIComponent(filename)
            + '?token=' + encodeURIComponent(state.secret);
    },
};

console.log('[api] Initialized — base=%s', state.serverUrl);

// ═══════════════════════════════════════════════════════════════
// 内部 helpers
// ═══════════════════════════════════════════════════════════════

function _url(path) {
    return state.serverUrl + path;
}

function _headers() {
    return {
        'Authorization': 'Bearer ' + state.secret,
        'Content-Type': 'application/json',
    };
}

function _errMsg(status) {
    const m = ERRORS[status] || '网络错误';
    return '[错误] ' + status + ': ' + m;
}
