// ═══════════════════════════════════════════════════════════════
// components/compose.js — Message input, file preview, action sheet
// ═══════════════════════════════════════════════════════════════
//
// 管理输入框、文件上传预览、+ 菜单 (拍照/相册/文件/状态)。
//
// 依赖: dom, state, api, toast
// 被依赖: chat (sendMessage 调用后清空), app.js (事件绑定)
// ═══════════════════════════════════════════════════════════════

import { dom } from '../core/dom.js';
import { state } from '../core/store.js';
import { events } from '../core/events.js';
import { api } from '../services/api.js';
import { notify } from '../utils/notify.js';
import { escHtml } from '../utils/html.js';

export const compose = {
    /**
     * 绑定事件。app.js 在初始化时调用。
     */
    init() {
        // Send button
        if (dom.sendBtn) {
            dom.sendBtn.addEventListener('click', () => this._onSend());
        }

        // Message input
        if (dom.msgInput) {
            dom.msgInput.addEventListener('input', () => {
                this.updateComposeButtons();
                this._autoResizeTextarea();
            });
            if (!state.isMobile) {
                dom.msgInput.addEventListener('keydown', e => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        this._onSend();
                    }
                });
            }
        }

        // Plus button
        if (dom.plusBtn) {
            dom.plusBtn.addEventListener('click', () => this.toggleActionSheet());
        }

        // Listen for welcome + button events
                events.on('compose:toggleActionSheet', () => this.toggleActionSheet());

        // ── File inputs ────────────────────────────────────
        if (dom.cameraInput) {
            dom.cameraInput.addEventListener('change', function () { compose.handleFileInput(this); });
        }
        if (dom.albumInput) {
            dom.albumInput.addEventListener('change', function () { compose.handleFileInput(this); });
        }
        if (dom.fileInput) {
            dom.fileInput.addEventListener('change', function () { compose.handleFileInput(this); });
        }

        // ── Action sheet ───────────────────────────────────
        if (dom.actionCancel) {
            dom.actionCancel.addEventListener('click', () => this.closeActionSheet());
        }
        if (dom.actionSheetOverlay) {
            dom.actionSheetOverlay.addEventListener('click', () => this.closeActionSheet());
        }
        if (dom.actionCamera) {
            dom.actionCamera.addEventListener('click', () => {
                this.closeActionSheet();
                if (dom.cameraInput) dom.cameraInput.click();
            });
        }
        if (dom.actionAlbum) {
            dom.actionAlbum.addEventListener('click', () => {
                this.closeActionSheet();
                if (dom.albumInput) dom.albumInput.click();
            });
        }
        if (dom.actionFile) {
            dom.actionFile.addEventListener('click', () => {
                this.closeActionSheet();
                if (dom.fileInput) dom.fileInput.click();
            });
        }
        if (dom.actionStatus) {
            dom.actionStatus.addEventListener('click', () => {
                this.closeActionSheet();
                api.get('/api/health')
                    .then(d => notify.push('OK: ' + d.status + ' | Claude: ' + d.claude_cli))
                    .catch(() => notify.push('无法连接', 'error'));
            });
        }

        console.log('[compose] Events bound');
    },

    // ── 发送消息 ──────────────────────────────────────────

    /** @returns {{ text: string, files: Array }} */
    getPending() {
        const inp = dom.msgInput;
        const text = inp ? inp.value.trim() : '';
        const files = state.pendingFiles.map(f => ({
            name: f.name,
            file_id: f.file_id,
            preview: f.preview,
        }));
        return { text, files };
    },

    /** 清空输入框和待发文件 */
    clear() {
        if (dom.msgInput) {
            dom.msgInput.value = '';
            dom.msgInput.style.height = 'auto';
        }
        state.pendingFiles.splice(0);
        state.set('pendingFiles', []);
        this.updateFilePreview();
        this.updateComposeButtons();
    },

    // ── 按钮状态 ──────────────────────────────────────────

    updateComposeButtons() {
        const inp = dom.msgInput;
        const hasContent = (inp && inp.value.trim().length > 0) || state.pendingFiles.length > 0;
        if (dom.sendBtn) {
            dom.sendBtn.classList.toggle('hidden', !hasContent);
        }
    },

    _onSend() {
        const { text, files } = this.getPending();
        if (!text && files.length === 0) return;

        console.log('[compose] Send triggered — text=%s files=%s',
            text.slice(0, 40), files.length);

        // Clear input immediately
        if (dom.msgInput) {
            dom.msgInput.value = '';
            dom.msgInput.style.height = 'auto';
        }
        state.set('pendingFiles', []);
        this.updateFilePreview();
        this.updateComposeButtons();

        // Send AFTER state is captured (blob URLs still alive)
        import('./chat.js').then(m => m.chat.sendMessage(text, files));
    },

    // ── 文件预览 ──────────────────────────────────────────

    updateFilePreview() {
        const bar = dom.filePreviewBar;
        if (!bar) return;

        if (state.pendingFiles.length === 0) {
            bar.classList.add('hidden');
            return;
        }
        bar.classList.remove('hidden');
        bar.innerHTML = state.pendingFiles.map((f, i) => {
            const thumb = f.preview
                ? '<img class="file-preview-thumb" src="' + f.preview + '" alt="">'
                : '';
            return '<span class="file-chip">' + thumb
                + '<span class="file-chip-name">' + escHtml(f.name) + '</span>'
                + '<span class="remove" onclick="window._gwRemoveFile(' + i + ')">✕</span></span>';
        }).join('');
    },

    handleFileInput(input) {
        const files = input.files;
        for (let i = 0; i < files.length; i++) {
            const f = files[i];
            const isImg = /\.(png|jpe?g|gif|webp|bmp)$/i.test(f.name);
            const previewUrl = isImg ? URL.createObjectURL(f) : null;

            notify.push('上传 ' + f.name + '...');
            api.uploadFile(f).then(r => {
                const pending = [...state.pendingFiles, {
                    name: f.name,
                    file_id: r.file_id,
                    preview: previewUrl,
                }];
                state.set('pendingFiles', pending);
                this.updateFilePreview();
                this.updateComposeButtons();
                console.log('[compose] File uploaded: %s → %s', f.name, r.file_id);
            }).catch(() => notify.push('上传失败', 'error'));
        }
        input.value = '';
    },

    // ── Action sheet ──────────────────────────────────────

    toggleActionSheet() {
        const sheet = dom.actionSheet;
        if (!sheet) return;
        if (!sheet.classList.contains('show')) {
            sheet.classList.remove('hidden');
            if (dom.actionSheetOverlay) dom.actionSheetOverlay.classList.remove('hidden');
            sheet.offsetHeight; // force reflow
            sheet.classList.add('show');
            if (dom.plusBtn) dom.plusBtn.classList.add('active');
        } else {
            this.closeActionSheet();
        }
    },

    closeActionSheet() {
        const sheet = dom.actionSheet;
        if (sheet) sheet.classList.remove('show');
        if (dom.plusBtn) dom.plusBtn.classList.remove('active');
        setTimeout(() => {
            if (sheet) sheet.classList.add('hidden');
            if (dom.actionSheetOverlay) dom.actionSheetOverlay.classList.add('hidden');
        }, 250);
    },

    // ── Textarea 自适应高度 ───────────────────────────────

    _autoResizeTextarea() {
        const ta = dom.msgInput;
        if (!ta) return;
        ta.style.height = 'auto';
        const maxH = 7 * 1.4 * parseFloat(getComputedStyle(ta).fontSize || '15');
        ta.style.height = Math.min(ta.scrollHeight, maxH) + 'px';
    },
};

// ── 全局回调 (HTML onclick) ──────────────────────────────────

window._gwRemoveFile = function (i) {
    const pending = state.pendingFiles;
    const f = pending[i];
    if (f && f.preview) URL.revokeObjectURL(f.preview);
    pending.splice(i, 1);
    state.set('pendingFiles', [...pending]);
    compose.updateFilePreview();
    compose.updateComposeButtons();
};

console.log('[components/compose] Initialized');
