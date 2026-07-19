// ═══════════════════════════════════════════════════════════════
// components/settings-panel.js — Slide-out settings panel
// ═══════════════════════════════════════════════════════════════
//
// BUGFIX #2: 异步数据加载前展开 section 导致内容截断 → 数据加载完再展开。
// BUGFIX #7: #sys-port 现在从 sysInfo 数据更新。
// BUGFIX #6: session_timeout_minutes 保存时同步更新运行时 config。
//
// 依赖: dom, state, api, theme, toast, confirm, events
// 被依赖: app.js (事件绑定)
// ═══════════════════════════════════════════════════════════════

import { dom } from '../core/dom.js';
import { state } from '../core/store.js';
import { events } from '../core/events.js';
import { api } from '../services/api.js';
import { theme } from '../services/theme.js';
import { notify } from '../utils/notify.js';
import { confirm } from './confirm.js';
import { settingsScreen } from './settings-screen.js';

export const settingsPanel = {
    // ── 生命周期 ──────────────────────────────────────────

    /**
     * 绑定所有事件。app.js 在初始化时调用一次。
     */
    init() {
        // Open / Close
        if (dom.settingsBtn) {
            dom.settingsBtn.addEventListener('click', () => this.open());
        }
        if (dom.settingsCloseBtn) {
            dom.settingsCloseBtn.addEventListener('click', () => this.close());
        }
        if (dom.settingsOverlay) {
            dom.settingsOverlay.addEventListener('click', () => this.close());
        }

        // Save connection
        if (dom.saveConnBtn) {
            dom.saveConnBtn.addEventListener('click', () => this._saveConnection());
        }

        // Theme presets
        document.querySelectorAll('.preset-btn').forEach(b => {
            b.addEventListener('click', () => {
                theme.apply(b.dataset.theme);
                b.parentElement.querySelectorAll('.preset-btn').forEach(x => x.classList.remove('active'));
                b.classList.add('active');
            });
        });

        // Accent color
        if (dom.setAccent) {
            dom.setAccent.addEventListener('input', () => theme.setAccent(dom.setAccent.value));
        }
        if (dom.setBg) {
            dom.setBg.addEventListener('input', () => theme.setBg(dom.setBg.value));
        }

        // Font size
        if (dom.setFontSize) {
            dom.setFontSize.addEventListener('input', function () {
                theme.setFontSize(parseInt(this.value));
            });
        }

        // System config: timeout, mirror, idle, file dir, max fsize
        this._bindSystemConfig();

        // System action buttons
        this._bindSystemActions();

        // Section collapse toggle
        document.addEventListener('click', e => this._handleCollapse(e));

        // BUGFIX #2: 初始化时折叠所有 section
        document.querySelectorAll('.settings-section').forEach(s => {
            if (s.classList.contains('no-collapse')) return;
            const body = s.querySelector('.section-body');
            if (!body) return;
            s.classList.add('collapsed');
            body.style.maxHeight = '0px';
        });

        console.log('[settings-panel] Events bound');
    },

    open() {
        // Fill form fields
        if (dom.setServerUrl) dom.setServerUrl.value = state.serverUrl;
        if (dom.setSecret) dom.setSecret.value = state.secret;

        // Show panel
        if (dom.settingsPanel) dom.settingsPanel.classList.remove('hidden');
        if (dom.settingsOverlay) dom.settingsOverlay.classList.remove('hidden');

        // BUGFIX #5: refresh theme UI
        theme.refreshUI();

        // Load async data — cached, only fetch once per session
        if (!this._infoLoaded) { this._loadSysInfo(); this._infoLoaded = true; }
        if (!this._configLoaded) { this._loadConfig(); this._configLoaded = true; }

        console.log('[settings-panel] Opened');
    },

    /** Force-reload system info (called after manual actions like migrate) */
    refreshSysInfo() {
        this._infoLoaded = false;
        this._loadSysInfo();
    },

    close() {
        if (dom.settingsPanel) dom.settingsPanel.classList.add('hidden');
        if (dom.settingsOverlay) dom.settingsOverlay.classList.add('hidden');
        console.log('[settings-panel] Closed');
    },

    // ── 系统信息 ──────────────────────────────────────────
    // BUGFIX #7: 更新 sysPort

    _loadSysInfo() {
        api.get('/api/system/info').then(d => {
            // BUGFIX #7: 更新端口
            if (dom.sysPort) dom.sysPort.textContent = d.port || '-';

            // System info block
            if (dom.sysInfo) {
                let bal = '';
                if (d.deepseek_balance && d.deepseek_balance.balance) {
                    bal = '余额: ' + d.deepseek_balance.balance + ' '
                        + (d.deepseek_balance.currency || 'CNY') + '<br>';
                }
                dom.sysInfo.innerHTML = bal
                    + '端口: ' + d.port + '<br>'
                    + '运行: ' + d.uptime + '<br>'
                    + '对话: ' + d.db.conversations + ' · 消息: ' + d.db.messages;
            }

            // File info
            if (dom.fileInfo) {
                dom.fileInfo.innerHTML = '文件: ' + d.files.count + ' 个 · '
                    + d.files.size_mb + ' MB<br>目录: ' + d.files.dir;
            }

            console.log('[settings-panel] SysInfo loaded — port=%s conv=%s msg=%s',
                d.port, d.db.conversations, d.db.messages);
        }).catch(e => {
            console.error('[settings-panel] SysInfo failed:', e);
        });
    },

    // ── 配置加载 ──────────────────────────────────────────

    _loadConfig() {
        api.get('/api/system/config').then(d => {
            if (dom.setTimeoutEl) dom.setTimeoutEl.value = String(d.session_timeout_minutes != null ? d.session_timeout_minutes : 0);
            if (dom.setMirrorEl) dom.setMirrorEl.value = d.console_mirror ? '1' : '0';
            if (dom.setFileDir) dom.setFileDir.value = d.file_root_dir || '';
            if (dom.setMaxFsize) dom.setMaxFsize.value = d.max_file_size_mb != null ? d.max_file_size_mb : 20;
            if (dom.setIdleEl) dom.setIdleEl.value = String(d.session_idle_timeout_minutes != null ? d.session_idle_timeout_minutes : 5);
            console.log('[settings-panel] Config loaded — timeout=%sm mirror=%s idle=%sm',
                d.session_timeout_minutes, d.console_mirror, d.session_idle_timeout_minutes);
        }).catch(e => {
            console.error('[settings-panel] Config load failed:', e);
        });
    },

    // ── 保存连接 ──────────────────────────────────────────

    _saveConnection() {
        const u = dom.setServerUrl;
        const s = dom.setSecret;
        const uVal = u ? u.value.trim() : '';
        const sVal = s ? s.value.trim() : '';

        if (!uVal || !sVal) {
            notify.push('请填写完整', 'error');
            return;
        }

        state.set('serverUrl', uVal);
        state.set('secret', sVal);
        localStorage.setItem('cg_server_url', uVal);
        localStorage.setItem('cg_secret', sVal);

        this.close();

        // Switch back to login screen and reconnect
        if (dom.chatScreen) dom.chatScreen.classList.remove('active');
        if (dom.settingsScreen) dom.settingsScreen.classList.add('active');
        if (dom.authSecret) dom.authSecret.value = sVal;

        console.log('[settings-panel] Connection saved — reconnecting to %s', uVal);
        settingsScreen.connect();
    },

    // ── 系统配置事件绑定 ──────────────────────────────────

    _bindSystemConfig() {
        const save = (key, value, successMsg) => {
            console.log('[settings-panel] Saving config: %s = %s', key, value);
            api.post('/api/system/config', { [key]: value })
                .then(() => notify.push(successMsg))
                .catch(() => {});
        };

        if (dom.setTimeoutEl) {
            dom.setTimeoutEl.addEventListener('change', function () {
                const v = parseInt(this.value);
                const msg = v === 0 ? '已设 永不 (重启后生效)' : '已设 ' + v + ' 分钟 (重启后生效)';
                save('session_timeout_minutes', v, msg);
            });
        }

        if (dom.setMirrorEl) {
            dom.setMirrorEl.addEventListener('change', function () {
                const on = this.value === '1';
                save('console_mirror', on, '终端镜像: ' + (on ? '开' : '关'));
            });
        }

        if (dom.setIdleEl) {
            dom.setIdleEl.addEventListener('change', function () {
                const v = parseInt(this.value);
                const msg = v === 0 ? '闲置回收: 永不' : '闲置回收: ' + v + ' 分钟';
                save('session_idle_timeout_minutes', v, msg);
            });
        }

        if (dom.setFileDir) {
            dom.setFileDir.addEventListener('change', function () {
                const v = this.value.trim();
                if (!v) return;
                save('file_root_dir', v, '存储路径已更新 (重启后生效)');
            });
        }

        if (dom.setMaxFsize) {
            dom.setMaxFsize.addEventListener('change', function () {
                const v = parseInt(this.value);
                if (!v || v < 1 || v > 500) return;
                save('max_file_size_mb', v, '上传大小上限: ' + v + ' MB');
            });
        }
    },

    // ── 系统操作按钮 ──────────────────────────────────────

    _bindSystemActions() {
        if (dom.sysClearLogs) {
            dom.sysClearLogs.addEventListener('click', () => {
                confirm.show('清除服务器日志？', () => {
                    api.post('/api/system/clear-logs', {}).then(() => notify.push('日志已清除')).catch(() => {});
                });
            });
        }

        if (dom.sysCleanCache) {
            dom.sysCleanCache.addEventListener('click', () => {
                confirm.show('清理 Python 缓存？', () => {
                    api.post('/api/system/clean-cache', {}).then(r => notify.push(r.message)).catch(() => {});
                });
            });
        }

        if (dom.sysViewLogs) {
            dom.sysViewLogs.addEventListener('click', () => {
                const v = dom.sysLogViewer;
                if (!v.classList.contains('hidden')) {
                    v.classList.add('hidden');
                    return;
                }
                api.get('/api/system/logs?lines=30').then(d => {
                    v.textContent = (d.logs || []).join('\n');
                    v.classList.remove('hidden');
                }).catch(() => {});
            });
        }

        if (dom.sysSoftRestart) {
            dom.sysSoftRestart.addEventListener('click', () => {
                confirm.show('平滑重启？', () => {
                    notify.push('平滑重启中...');
                    api.post('/api/system/soft-restart', {}).then(() => {
                        let n = 8;
                        const t = setInterval(() => {
                            notify.push('重启中... ' + n + 's');
                            n--;
                            if (n < 0) { clearInterval(t); window.location.reload(); }
                        }, 1000);
                    }).catch(() => notify.push('重启失败', 'error'));
                });
            });
        }

        if (dom.sysClearConvs) {
            dom.sysClearConvs.addEventListener('click', () => {
                confirm.show('删除所有对话？不可撤销。', () => {
                    api.post('/api/system/clear-conversations', {}).then(() => {
                        state.set('currentConvId', null);
                        if (dom.messagesContainer) dom.messagesContainer.innerHTML = '';
                        events.emit('sidebar:refresh');
                        notify.push('已清空');
                    }).catch(() => {});
                });
            });
        }

        // Migrate images to images/ subfolder
        if (dom.sysMigrateImages) {
            dom.sysMigrateImages.addEventListener('click', () => {
                console.log('[settings-panel] Migrate images');
                dom.sysMigrateImages.disabled = true;
                api.post('/api/system/migrate-images', {}).then(d => {
                    notify.push(d.message || '整理完成');
                    this.refreshSysInfo();
                }).catch(() => {
                    notify.push('整理失败', 'error');
                }).finally(() => {
                    dom.sysMigrateImages.disabled = false;
                });
            });
        }

        // Force refresh (reload page)
        if (dom.sysForceRefresh) {
            dom.sysForceRefresh.addEventListener('click', () => {
                console.log('[settings-panel] Force refresh');
                window.location.reload(true);
            });
        }

        if (dom.sysRestart) {
            dom.sysRestart.addEventListener('click', () => {
                confirm.show('强制重启服务器？', () => {
                    notify.push('重启中...');
                    api.post('/api/system/restart', {}).then(() => {
                        let n = 3;
                        const t = setInterval(() => {
                            notify.push('重启中... ' + n + 's');
                            n--;
                            if (n < 0) { clearInterval(t); window.location.reload(); }
                        }, 1000);
                    }).catch(() => notify.push('重启失败', 'error'));
                });
            });
        }
    },

    // ── Section 折叠/展开 ─────────────────────────────────

    _handleCollapse(e) {
        const h3 = e.target.closest('.settings-section h3');
        if (!h3) return;
        const section = h3.parentElement;
        if (section.classList.contains('no-collapse')) return;
        const body = section.querySelector('.section-body');
        if (!body) return;

        if (section.classList.contains('collapsed')) {
            section.classList.remove('collapsed');
            // BUGFIX #2: 用 scrollHeight 计算自然高度 (比预设值准确)
            body.style.maxHeight = body.scrollHeight + 'px';
            console.log('[settings-panel] Section expanded');
        } else {
            section.classList.add('collapsed');
            body.style.maxHeight = '0px';
            console.log('[settings-panel] Section collapsed');
        }
    },
};

console.log('[components/settings-panel] Initialized');
