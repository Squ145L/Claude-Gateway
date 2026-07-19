// ═══════════════════════════════════════════════════════════════
// components/chat.js — Message sending + SSE consumption + welcome
// ═══════════════════════════════════════════════════════════════
//
// 核心消息流: sendMessage → doSendSSE → SSE 解析 → DOM 更新
//
// 依赖: dom, state, events, api, stream, toast
//        render/messages, render/thinking, utils/html
// 被依赖: app.js (事件绑定), compose (sendMessage), sidebar (switch)
// ═══════════════════════════════════════════════════════════════

import { dom } from '../core/dom.js';
import { state } from '../core/store.js';
import { events } from '../core/events.js';
import { api } from '../services/api.js';
import { getStream, resetStream } from '../services/stream.js';
import { notify } from '../utils/notify.js';
import { escHtml, fmtNum } from '../utils/html.js';
import {
    appendMessage, renderMessages, updateStatus, scrollMessages,
} from '../render/messages.js';
import {
    addThinkingFold, updateThinkingFold, updateThinkingLabel, removeThinkingFold,
} from '../render/thinking.js';
import { addAgentFold, updateAgentFold } from '../render/agent.js';
import { renderMarkdown } from '../render/markdown.js';

export const chat = {
    /**
     * 绑定事件。app.js 在初始化时调用。
     */
    init() {
        // Title inline edit — only when a conversation is active
        if (dom.currentTitle) {
            dom.currentTitle.addEventListener('click', () => this._startTitleEdit());
        }
        // Toggle editability based on current conversation
        state.on('currentConvId', (id) => {
            if (dom.currentTitle) {
                dom.currentTitle.classList.toggle('editable', !!id);
            }
        });

        // Listen for render events (from stream polling)
        events.on('render:refresh', ({ messages, streaming }) => {
            renderMessages(messages, streaming);
        });
        events.on('render:scroll', () => scrollMessages());

        // Stream state listener (for side effects)
        events.on('stream:state', st => {
            console.log('[chat] Stream state → %s', st);
        });

        console.log('[chat] Events bound');
    },

    // ── 发送消息 ──────────────────────────────────────────

    /**
     * 由 compose 模块调用。
     * @param {string} text
     * @param {Array}  files — [{ name, file_id, preview }]
     */
    sendMessage(text, files) {
        const stream = getStream();

        // ── Interrupt: stream is live → send interrupt instead ──
        if (stream.isLive() && state.currentConvId) {
            const userText = text || '[文件]';
            stream.onInterrupt();
            if (dom.sendBtn) dom.sendBtn.disabled = true;
            api.post('/api/chat/interrupt', {
                conversation_id: state.currentConvId,
                message: userText,
            }).then(() => {
                console.log('[chat] Interrupt sent — waiting for new response');
            }).catch(() => {
                stream.reset();
                notify.push('打断失败', 'error');
                if (dom.sendBtn) dom.sendBtn.disabled = false;
            });
            return;
        }

        // ── Normal send: no active stream ──
        resetStream();

        const userText = text || '[文件]';
        const fileIds = files.map(f => ({ id: f.file_id, name: f.name }));

        if (!state.currentConvId) {
            api.post('/api/conversations').then(d => {
                state.set('currentConvId', d.id);
                this._doSendSSE(userText, files, fileIds);
            }).catch(() => notify.push('创建对话失败', 'error'));
            return;
        }
        this._doSendSSE(userText, files, fileIds);
    },

    // ── SSE 发送 ──────────────────────────────────────────

    _doSendSSE(userText, files, fileIds) {
        // Disable send button during streaming
        if (dom.sendBtn) dom.sendBtn.disabled = true;

        const uploadFiles = files.map(f => ({
            name: f.name, file_id: f.file_id, preview: f.preview,
        }));
        const displayText = userText.replace(/\[(FILE|DOWNLOAD):/gi, '\\[$1]:');

        // Append user message
        appendMessage({ role: 'user', content: displayText }, uploadFiles);
        events.emit('chat:updateWelcome');

        // Start stream
        const stream = getStream();
        stream.start(state.currentConvId);

        // Append assistant placeholder
        const aiEl = appendMessage({ role: 'assistant', content: '' }, [], true);

        // Handle case where appendMessage returns null (container missing)
        if (!aiEl) {
            console.error('[chat] Cannot append message — container missing');
            if (dom.sendBtn) dom.sendBtn.disabled = false;
            return;
        }

        let statusEl = aiEl.querySelector('.status-bar');
        if (statusEl) updateStatus(statusEl, 'thinking');

        // ── State accumulators ─────────────────────────────
        let thinkingP = [], textP = [], tokens = null;
        let thinkingStart = null, thinkingEnd = false;
        let _rejected = false;

        // ── Kick off SSE ───────────────────────────────────
        api.streamChat(userText, fileIds).then(resp => {
            if (!resp.ok) throw new Error('[错误] ' + resp.status);

            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let buf = '';

            function pump() {
                return reader.read().then(r => {
                    if (r.done) {
                        // ── Stream complete ─────────────────
                        aiEl.classList.remove('streaming');
                        if (statusEl) { statusEl.remove(); statusEl = null; }

                        if (!thinkingP.length) removeThinkingFold(aiEl);
                        if (thinkingP.length && !textP.length) {
                            const ce = aiEl.querySelector('.msg-content');
                            if (ce) ce.innerHTML = renderMarkdown(thinkingP.join(''), api);
                            removeThinkingFold(aiEl);
                        }

                        const contentEl = aiEl.querySelector('.msg-content');
                        if (contentEl) {
                            let final = textP.join('');
                            if (!final && thinkingP.length) final = thinkingP.join('');
                            if (final) contentEl.innerHTML = renderMarkdown(final, api);
                        }

                        // Footer
                        let footer = aiEl._footer;
                        if (!footer) {
                            footer = document.createElement('div');
                            footer.className = 'msg-footer';
                            aiEl.appendChild(footer);
                            aiEl._footer = footer;
                        }
                        const now = new Date().toLocaleTimeString();
                        let tokenHtml = '';
                        if (tokens) tokenHtml = '<span class="token-info">↑ ' + fmtNum(tokens.i) + '   ↓ ' + fmtNum(tokens.o) + '</span>';
                        footer.innerHTML = tokenHtml + '<span class="timestamp">' + now + '</span>';

                        events.emit('chat:updateWelcome');
                        events.emit('sidebar:refresh');
                        scrollMessages();
                        stream.onComplete();
                        console.log('[chat] SSE complete — thinking=%schars text=%schars',
                            thinkingP.join('').length, textP.join('').length);
                        return;
                    }

                    buf += decoder.decode(r.value, { stream: true });
                    const lines = buf.split('\n');
                    buf = lines.pop() || '';

                    for (const line of lines) {
                        if (line.indexOf('data: ') !== 0) continue;
                        let c;
                        try { c = JSON.parse(line.slice(6)); }
                        catch (e) { continue; }

                        switch (c.type) {
                        case 'text':
                            if (!thinkingEnd && thinkingP.length) {
                                thinkingEnd = true;
                                const ms = Date.now() - thinkingStart;
                                const dur = ms >= 60000
                                    ? Math.floor(ms / 60000) + 'm ' + Math.floor((ms % 60000) / 1000) + 's'
                                    : (ms / 1000).toFixed(1) + 's';
                                const wc = thinkingP.join('').split(/\s+/).filter(Boolean).length;
                                updateThinkingLabel(aiEl, dur, wc);
                            }
                            textP.push(c.content);
                            stream.onText();
                            if (statusEl) updateStatus(statusEl, 'text');
                            aiEl.querySelector('.msg-content').textContent = textP.join('');
                            scrollMessages();
                            break;

                        case 'thinking':
                            if (!thinkingStart) thinkingStart = Date.now();
                            thinkingP.push(c.content);
                            stream.onThinking();
                            if (statusEl) updateStatus(statusEl, 'thinking');
                            updateThinkingFold(aiEl, thinkingP.join(''));
                            break;

                        case 'agent_result':
                            // Background agent completed — fold into current message
                            updateAgentFold(aiEl, c.content || '');
                            scrollMessages();
                            break;

                        case 'status':
                            if (c.state === 'done') {
                                if (statusEl) updateStatus(statusEl, 'done');
                            } else {
                                if (statusEl) updateStatus(statusEl, 'tool', c.tool);
                            }
                            break;

                        case 'done':
                            if (c.usage) tokens = { i: fmtNum(c.usage.i), o: fmtNum(c.usage.o) };
                            if (!state.currentConvId && c.conversation_id) {
                                state.set('currentConvId', c.conversation_id);
                                events.emit('sidebar:refresh');
                            }
                            break;

                        case 'error':
                            if (statusEl) { statusEl.remove(); statusEl = null; }
                            // Rejection from concurrent-message guard
                            if (c.content && c.content.indexOf('already being generated') !== -1) {
                                _rejected = true;
                                stream.reset();
                                if (aiEl && aiEl.parentNode) aiEl.parentNode.removeChild(aiEl);
                                notify.push('Waiting for current response to finish...', 'info');
                                // Poll until streaming finishes
                                const _pollConvId = state.currentConvId;
                                let _pollCount = 0;
                                const _poll = setInterval(() => {
                                    _pollCount++;
                                    if (_pollCount > 60) { clearInterval(_poll); return; }
                                    api.getMessages(_pollConvId).then(d => {
                                        if (!d.streaming || d.streaming.status === 'finalized') {
                                            clearInterval(_poll);
                                            notify.push('Ready', '');
                                            if (dom.sendBtn) dom.sendBtn.disabled = false;
                                            if (dom.msgInput) dom.msgInput.focus();
                                        }
                                    }).catch(() => {});
                                }, 2000);
                                return;
                            }
                            // Normal error — render inline
                            aiEl.querySelector('.msg-content').textContent = c.content;
                            break;
                        }
                    }
                    return pump();
                });
            }
            return pump();

        }).catch(e => {
            // SSE disconnected — start polling fallback
            if (statusEl) { statusEl.remove(); statusEl = null; }
            aiEl.classList.remove('streaming');
            notify.push('连接断开，重连中...', 'error');
            stream.onDisconnect();
            scrollMessages();
            console.warn('[chat] SSE disconnected:', e.message);
        }).finally(() => {
            if (!_rejected) {
                if (dom.sendBtn) dom.sendBtn.disabled = false;
                if (dom.msgInput) dom.msgInput.focus();
            }
        });
    },

    // ── 标题行内编辑 ──────────────────────────────────────

    _startTitleEdit() {
        const el = dom.currentTitle;
        if (!el || !state.currentConvId || el._editing) return;

        const old = el.textContent.trim();
        el._editing = true;

        const inp = document.createElement('input');
        inp.className = 'chat-title-input';
        inp.value = old;

        const okBtn = document.createElement('button');
        okBtn.className = 'confirm-edit-btn';
        okBtn.textContent = '✓';

        el.replaceWith(inp);
        inp.focus();
        inp.select();
        inp.parentNode.insertBefore(okBtn, inp.nextSibling);

        function finish(save) {
            if (!inp.parentNode) return;
            const newTitle = save ? inp.value.trim() : '';
            if (save && newTitle && newTitle !== old) {
                import('./sidebar.js').then(m => m.sidebar.renameConversation(state.currentConvId, newTitle));
            } else {
                el.textContent = old;
            }
            inp.replaceWith(el);
            if (okBtn.parentNode) okBtn.remove();
            el._editing = false;
        }

        inp.addEventListener('keydown', e => {
            if (e.key === 'Enter') { e.preventDefault(); finish(true); }
            else if (e.key === 'Escape') { e.preventDefault(); finish(false); }
        });

        function onOutside(e) {
            if (!inp.parentNode) { document.removeEventListener('click', onOutside); return; }
            if (e.target !== inp && e.target !== okBtn) {
                document.removeEventListener('click', onOutside);
                finish(true);
            }
        }
        setTimeout(() => document.addEventListener('click', onOutside), 50);
        okBtn.addEventListener('click', e => { e.stopPropagation(); finish(true); });
    },
};

console.log('[components/chat] Initialized');
