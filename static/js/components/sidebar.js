// ═══════════════════════════════════════════════════════════════
// components/sidebar.js — Conversation list + batch + context menu
// ═══════════════════════════════════════════════════════════════
//
// BUGFIX #13: 删除按钮现在通过 api.delete() 而非裸 fetch()。
//
// 依赖: dom, state, events, api, toast, confirm
// 被依赖: app.js (事件绑定), chat (switchConversation)
// ═══════════════════════════════════════════════════════════════

import { dom } from '../core/dom.js';
import { state } from '../core/store.js';
import { events } from '../core/events.js';
import { api } from '../services/api.js';
import { escHtml } from '../utils/html.js';
import { notify } from '../utils/notify.js';
import { confirm } from './confirm.js';

export const sidebar = {
    /**
     * 绑定事件 + 监听 chat:opened。app.js 在初始化时调用。
     */
    init() {
        // Open / Close
        if (dom.menuBtn) {
            dom.menuBtn.addEventListener('click', () => this.open());
        }
        if (dom.sidebarOverlay) {
            dom.sidebarOverlay.addEventListener('click', () => this.close());
        }
        if (dom.newChatBtn) {
            dom.newChatBtn.addEventListener('click', () => this.newConversation());
        }

        // Batch mode
        if (dom.batchBtn) {
            dom.batchBtn.addEventListener('click', () => {
                state.batchMode ? this.exitBatchMode() : this.enterBatchMode();
            });
        }
        if (dom.batchDeleteBtn) {
            dom.batchDeleteBtn.addEventListener('click', () => this.batchDelete());
        }
        if (dom.batchCancelBtn) {
            dom.batchCancelBtn.addEventListener('click', () => this.exitBatchMode());
        }

        // Context menu
        if (dom.ctxOverlay) {
            dom.ctxOverlay.addEventListener('click', () => this.hideCtxMenu());
        }
        if (dom.ctxRename) {
            dom.ctxRename.addEventListener('click', () => this._ctxRename());
        }
        if (dom.ctxDelete) {
            dom.ctxDelete.addEventListener('click', () => this._ctxDelete());
        }
        if (dom.ctxPin) {
            dom.ctxPin.addEventListener('click', () => this._ctxPin());
        }

        // Search
        if (dom.convSearch) {
            dom.convSearch.addEventListener('input', function () {
                const q = this.value.toLowerCase().trim();
                document.querySelectorAll('.conv-item').forEach(item => {
                    const title = (item.querySelector('.conv-title') || {}).textContent || '';
                    item.style.display = (!q || title.toLowerCase().indexOf(q) !== -1) ? '' : 'none';
                });
            });
        }

        // Swipe to close
        this._initSwipe();

        // Listen for events
        events.on('chat:opened', () => this.loadConversations());
        events.on('sidebar:refresh', () => this.loadConversations());

        console.log('[sidebar] Events bound');
    },

    // ── 打开/关闭 ─────────────────────────────────────────

    open() {
        if (dom.sidebar) dom.sidebar.classList.remove('hidden');
        if (dom.sidebarOverlay) dom.sidebarOverlay.classList.remove('hidden');
        // Notify listeners (e.g. notify stack)
        events.emit('sidebar:opened');
        // Cache — only fetch on first open per session; sidebar:refresh event forces reload
        if (!this._convsLoaded) { this.loadConversations(); this._convsLoaded = true; }
        console.log('[sidebar] Opened (cached=%s)', !!this._convsLoaded);
    },

    close() {
        if (dom.sidebar) dom.sidebar.classList.add('hidden');
        if (dom.sidebarOverlay) dom.sidebarOverlay.classList.add('hidden');
        this.exitBatchMode();
        // Notify listeners (e.g. notify stack)
        events.emit('sidebar:closed');
        console.log('[sidebar] Closed');
    },

    // ── 对话列表 ──────────────────────────────────────────

    loadConversations() {
        api.get('/api/conversations').then(d => {
            this._renderList(d.conversations);
        }).catch(() => {});
    },

    _renderList(convs) {
        const list = dom.conversationList;
        if (!list) return;
        list.innerHTML = '';

        if (!convs || !convs.length) {
            list.innerHTML = '<div style="padding:24px;text-align:center;color:var(--text-dim);font-size:0.85rem">暂无对话</div>';
            return;
        }

        convs.forEach(c => {
            const item = document.createElement('div');
            item.className = 'conv-item' + (c.id === state.currentConvId ? ' active' : '');
            item.setAttribute('data-cid', c.id);

            if (state.batchMode) item.classList.add('batch-mode');
            if (state.selectedConvs[c.id]) item.classList.add('selected');

            const dateStr = c.updated_at ? _formatDate(c.updated_at) : '';
            const extraBtns = state.isTouch ? ''
                : '<span class="rename-conv" title="重命名">✏️</span>'
                + '<span class="delete-conv">✕</span>';

            item.innerHTML =
                '<span class="conv-check"></span>'
                + '<span class="conv-title">' + escHtml(c.title) + '</span>'
                + '<span class="conv-time">' + dateStr + '</span>'
                + extraBtns;

            // Click → switch
            item.addEventListener('click', e => {
                if (state.batchMode) {
                    this.toggleConvSelect(c.id, item);
                    return;
                }
                this.switchConversation(c.id);
                this.close();
            });

            // Delete button (desktop)
            const delBtn = item.querySelector('.delete-conv');
            if (delBtn) {
                delBtn.addEventListener('click', evt => {
                    evt.stopPropagation();
                    confirm.show('删除: ' + escHtml(c.title) + '？', () => {
                        _deleteConv(c.id).then(() => {
                            if (state.currentConvId === c.id) {
                                state.set('currentConvId', null);
                                if (dom.messagesContainer) dom.messagesContainer.innerHTML = '';
                                events.emit('chat:updateWelcome');
                            }
                            this.loadConversations();
                        }).catch(() => {});
                    });
                });
            }

            // Rename button (desktop)
            const renameBtn = item.querySelector('.rename-conv');
            if (renameBtn) {
                renameBtn.addEventListener('click', evt => {
                    evt.stopPropagation();
                    this._startRename(c, item);
                });
            }

            // Long press → context menu (mobile)
            let pressTimer;
            item.addEventListener('touchstart', () => {
                pressTimer = setTimeout(() => {
                    pressTimer = null;
                    navigator.vibrate && navigator.vibrate(20);
                    state.set('ctxTarget', { id: c.id, title: c.title, el: item });
                    this.showCtxMenu();
                }, 500);
            }, { passive: true });
            item.addEventListener('touchend', () => {
                if (pressTimer) { clearTimeout(pressTimer); pressTimer = null; }
            });
            item.addEventListener('touchmove', () => {
                if (pressTimer) { clearTimeout(pressTimer); pressTimer = null; }
            });

            list.appendChild(item);
        });

        console.log('[sidebar] Rendered %s conversations', convs.length);
    },

    // ── 对话操作 ──────────────────────────────────────────

    switchConversation(convId) {
        import('../services/stream.js').then(m => m.resetStream());
        state.set('currentConvId', convId);

        api.getMessages(convId).then(d => {
            if (dom.currentTitle) dom.currentTitle.textContent = d.conversation.title;
            // Re-render via events
            events.emit('render:refresh', { messages: d.messages, streaming: d.streaming });
            requestAnimationFrame(() => {
                if (dom.messagesContainer) {
                    dom.messagesContainer.scrollTop = dom.messagesContainer.scrollHeight;
                }
            });
            console.log('[sidebar] Switched to conv=%s (%s msgs)', convId.slice(0, 8), d.messages.length);
        }).catch(() => {});

        this.loadConversations();
    },

    renameConversation(convId, newTitle) {
        return api.post('/api/conversations/' + convId + '/title', { title: newTitle }).then(d => {
            if (convId === state.currentConvId && dom.currentTitle) {
                dom.currentTitle.textContent = d.title;
            }
            this.loadConversations();
            return d;
        });
    },

    newConversation() {
        import('../services/stream.js').then(m => m.resetStream());
        state.set('currentConvId', null);
        if (dom.messagesContainer) dom.messagesContainer.innerHTML = '';
        if (dom.currentTitle) dom.currentTitle.textContent = '新对话';
        this.close();
        this.loadConversations();
        events.emit('chat:updateWelcome');
        console.log('[sidebar] New conversation');
    },

    // ── 批量模式 ──────────────────────────────────────────

    enterBatchMode() {
        state.set('batchMode', true);
        state.set('selectedConvs', {});
        if (dom.batchBtn) dom.batchBtn.textContent = '完成';
        if (dom.batchBar) dom.batchBar.classList.remove('hidden');
        document.querySelectorAll('.conv-item').forEach(el => {
            el.classList.add('batch-mode');
            el.classList.remove('selected');
        });
        this._updateBatchCount();
    },

    exitBatchMode() {
        state.set('batchMode', false);
        state.set('selectedConvs', {});
        if (dom.batchBtn) dom.batchBtn.textContent = '批量';
        if (dom.batchBar) dom.batchBar.classList.add('hidden');
        document.querySelectorAll('.conv-item').forEach(el => {
            el.classList.remove('batch-mode', 'selected');
        });
    },

    toggleConvSelect(cid, el) {
        const sel = { ...state.selectedConvs };
        if (sel[cid]) { delete sel[cid]; el.classList.remove('selected'); }
        else { sel[cid] = true; el.classList.add('selected'); }
        state.set('selectedConvs', sel);
        this._updateBatchCount();
    },

    _updateBatchCount() {
        if (dom.batchCount) {
            dom.batchCount.textContent = '已选 ' + Object.keys(state.selectedConvs).length + ' 项';
        }
    },

    batchDelete() {
        const ids = Object.keys(state.selectedConvs);
        if (!ids.length) return;
        confirm.show('删除 ' + ids.length + ' 个对话？', () => {
            let done = 0;
            ids.forEach(id => {
                _deleteConv(id).then(() => {
                    done++;
                    if (done === ids.length) {
                        this.exitBatchMode();
                        this.loadConversations();
                        notify.push('已删除');
                    }
                }).catch(() => { done++; });
            });
        });
    },

    // ── 右键/长按菜单 ─────────────────────────────────────

    showCtxMenu() {
        const t = state.ctxTarget;
        if (!t || !t.el) return;
        const menu = dom.ctxMenu;
        const overlay = dom.ctxOverlay;
        const sidebarEl = dom.sidebar;
        if (!menu || !overlay || !sidebarEl) return;

        const row = t.el.getBoundingClientRect();
        const sbRect = sidebarEl.getBoundingClientRect();

        menu.classList.remove('hidden');
        menu.style.visibility = 'hidden';
        menu.classList.add('show');
        const mw = menu.offsetWidth || 110;
        const mh = menu.offsetHeight || 0;
        menu.classList.remove('show');
        menu.style.visibility = '';

        let top = row.bottom + 4;
        let left = sbRect.right - mw - 8;
        if (top + mh > window.innerHeight - 8) top = row.top - mh - 4;
        if (top < sbRect.top + 4) top = sbRect.top + 4;
        if (left < sbRect.left + 4) left = sbRect.left + 4;
        if (left + mw > sbRect.right - 4) left = sbRect.right - mw - 4;

        menu.style.top = top + 'px';
        menu.style.left = left + 'px';
        overlay.classList.remove('hidden');
        menu.classList.remove('hidden');
        requestAnimationFrame(() => menu.classList.add('show'));
    },

    hideCtxMenu() {
        const menu = dom.ctxMenu;
        const overlay = dom.ctxOverlay;
        if (menu) menu.classList.remove('show');
        setTimeout(() => {
            if (menu) menu.classList.add('hidden');
            if (overlay) overlay.classList.add('hidden');
            state.set('ctxTarget', null);
        }, 150);
    },

    _ctxRename() {
        const t = state.ctxTarget;
        if (!t) return;
        this.hideCtxMenu();
        const newTitle = prompt('重命名对话:', t.title);
        if (newTitle && newTitle.trim() && newTitle.trim() !== t.title) {
            this.renameConversation(t.id, newTitle.trim());
        }
    },

    _ctxDelete() {
        const t = state.ctxTarget;
        if (!t) return;
        this.hideCtxMenu();
        confirm.show('确认删除该对话？<br><span class="confirm-subtitle">"' + escHtml(t.title) + '"</span>', () => {
            _deleteConv(t.id).then(() => {
                if (state.currentConvId === t.id) {
                    state.set('currentConvId', null);
                    if (dom.messagesContainer) dom.messagesContainer.innerHTML = '';
                    events.emit('chat:updateWelcome');
                }
                this.loadConversations();
                notify.push('已删除');
            }).catch(() => notify.push('删除失败', 'error'));
        }, '删除');
    },

    _ctxPin() {
        const t = state.ctxTarget;
        if (!t) return;
        this.hideCtxMenu();
        api.post('/api/conversations/' + t.id + '/pin', {})
            .then(() => { this.loadConversations(); notify.push('已置顶'); })
            .catch(() => notify.push('置顶失败', 'error'));
    },

    // ── 行内重命名 ────────────────────────────────────────

    _startRename(c, item) {
        const titleSpan = item.querySelector('.conv-title');
        const oldTitle = titleSpan.textContent;
        const inp = document.createElement('input');
        inp.className = 'conv-title-input';
        inp.value = oldTitle;
        titleSpan.replaceWith(inp);
        inp.focus();
        inp.select();

        function finish(save) {
            if (!inp.parentNode) return;
            const newTitle = save ? inp.value.trim() : '';
            if (save && newTitle && newTitle !== oldTitle) {
                sidebar.renameConversation(c.id, newTitle);
            } else {
                titleSpan.textContent = oldTitle;
            }
            if (inp.parentNode) inp.replaceWith(titleSpan);
        }

        inp.addEventListener('keydown', e => {
            if (e.key === 'Enter') { e.preventDefault(); finish(true); }
            else if (e.key === 'Escape') { e.preventDefault(); finish(false); }
        });
        inp.addEventListener('blur', () => finish(true));
    },

    // ── 滑动关闭 ──────────────────────────────────────────

    _initSwipe() {
        const el = dom.sidebar;
        if (!el) return;

        let startX = 0, active = false;

        el.addEventListener('touchstart', e => {
            if (e.target.closest('.conv-item') || e.target.closest('button') || e.target.closest('input')) return;
            startX = e.touches[0].clientX;
            active = true;
        }, { passive: true });

        el.addEventListener('touchmove', e => {
            if (!active) return;
            const dx = e.touches[0].clientX - startX;
            if (dx > 0) el.style.transform = 'translateX(' + Math.min(dx, 120) + 'px)';
        }, { passive: true });

        el.addEventListener('touchend', e => {
            if (!active) { active = false; return; }
            active = false;
            const dx = e.changedTouches[0].clientX - startX;
            el.style.transform = '';
            if (dx > 80) this.close();
        });
    },
};

// ── helpers ──────────────────────────────────────────────────

function _deleteConv(convId) {
    return api.delete('/api/conversations/' + convId);
}

function _formatDate(isoStr) {
    const d = new Date(isoStr);
    const thisYear = new Date().getFullYear();
    if (d.getFullYear() === thisYear) {
        return (d.getMonth() + 1) + '/' + d.getDate();
    }
    return d.getFullYear() + '/' + (d.getMonth() + 1) + '/' + d.getDate();
}

console.log('[components/sidebar] Initialized');
