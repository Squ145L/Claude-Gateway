// ═══════════════════════════════════════════════════════════════
// utils/notify.js — 左上角通知栈
// ═══════════════════════════════════════════════════════════════
//
// 缓冲 + 统一 tick，所有 DOM 操作集中在 tick 内。
// 正常流 flexbox 堆叠，不依赖 translateY 手动移位。
// 新通知出现在顶部（insertBefore），旧通知自然下移。
// 超出 5 条时最老的通知 remaining 截断至 300ms，自然淡出。
//
// 依赖: dom (notifyStack 元素), events (sidebar 位移)
// 被依赖: 所有组件
//
// 用法:
//   import { notify } from '../utils/notify.js';
//   notify.push('保存成功');
//   notify.push('连接失败', 'error');
// ═══════════════════════════════════════════════════════════════

import { dom } from '../core/dom.js';
import { events } from '../core/events.js';

const MAX_VISIBLE = 5;
const TTL_MS      = 2500;   // 可见时长
const TICK_MS     = 100;    // tick 间隔
const FADE_AT     = 300;    // remaining ≤ 此值时开始淡出

// ── 状态 ──
// _items:  [{el, remaining}]  已渲染的 notify-item（数组头部=最新=顶部）
// _buffer: [{msg, type}]      待渲染
let _items  = [];
let _buffer = [];
let _timer  = null;

// ── Phase 1: 将 buffer 中所有消息一次性插入 DOM ──
function _flush() {
    if (_buffer.length === 0) return;
    const stack = dom.notifyStack;
    if (!stack) { _buffer = []; return; }

    const buf = _buffer;
    _buffer = [];

    for (const { msg, type } of buf) {
        const el = document.createElement('div');
        el.className = 'notify-item ' + (type || '');
        el.textContent = msg;
        el.style.animation = 'none';  // suppress on insert — we trigger via RAF

        // insertBefore → 每次插入都变成第一个子元素 → 新通知在顶部
        if (stack.firstChild) {
            stack.insertBefore(el, stack.firstChild);
        } else {
            stack.appendChild(el);
        }

        // Re-trigger CSS animation on next frame so browser sees the element first
        requestAnimationFrame(() => {
            el.style.animation = '';
        });

        _items.unshift({ el, remaining: TTL_MS });
    }

    console.log('[notify] flush — %s items, total=%s', buf.length, _items.length);
}

// ── Phase 2: 挤压 — 超出 5 条的通知截断 remaining ──
function _squeeze() {
    for (let i = MAX_VISIBLE; i < _items.length; i++) {
        if (_items[i].remaining > FADE_AT) {
            _items[i].remaining = FADE_AT;
            console.log('[notify] squeeze — item[%s] → %sms', i, FADE_AT);
        }
    }
}

// ── Phase 3+4: 倒计时 → 淡出+收缩 → 移除 → 停 tick ──
function _tick() {
    _flush();
    _squeeze();

    for (let i = _items.length - 1; i >= 0; i--) {
        const item = _items[i];
        item.remaining -= TICK_MS;

        // 进入过渡：opacity + max-height + margin + padding 同时收缩
        if (item.remaining <= FADE_AT && !item._fading) {
            item._fading = true;
            item.el.style.opacity = '0';
            item.el.style.maxHeight = '0';
            item.el.style.marginBottom = '0';
            item.el.style.paddingTop = '0';
            item.el.style.paddingBottom = '0';
        }
        // 过渡动画完成后移除 DOM（FADE_AT 时长 = CSS transition 时长）
        if (item.remaining <= -FADE_AT) {
            if (item.el.parentNode) item.el.remove();
            _items.splice(i, 1);
        }
    }

    // 队列 + buffer 双空 → 停 tick
    if (_items.length === 0 && _buffer.length === 0) {
        clearInterval(_timer);
        _timer = null;
        console.log('[notify] Timer stopped — stack empty');
    }
}

// ── 公开 API ──
export const notify = {
    /**
     * 绑定全局事件。app.js 在初始化时调用。
     */
    init() {
        // ── 侧边栏打开/关闭 → 通知栈左右位移 ────────────
        events.on('sidebar:opened', () => {
            const sidebarEl = dom.sidebar;
            if (sidebarEl && dom.notifyStack) {
                const w = sidebarEl.offsetWidth;
                dom.notifyStack.style.left = (w + 10) + 'px';
            }
        });
        events.on('sidebar:closed', () => {
            if (dom.notifyStack) {
                dom.notifyStack.style.left = '12px';
            }
        });

        // ── 点击任意通知 → 全部立刻消失 ──────────────────
        if (dom.notifyStack) {
            dom.notifyStack.addEventListener('click', e => {
                if (!e.target.closest('.notify-item')) return;
                for (const item of _items) {
                    if (item.remaining > FADE_AT) {
                        item.remaining = FADE_AT;
                    }
                }
            });
        }

        console.log('[notify] Events bound');
    },

    /**
     * @param {string} msg
     * @param {string} [type] — '' (default) | 'error'
     */
    push(msg, type) {
        _buffer.push({ msg, type: type || '' });
        console.log('[notify] push — %s "%s" (buf=%s)', type || 'info', msg.slice(0, 40), _buffer.length);

        if (!_timer) {
            _timer = setInterval(_tick, TICK_MS);
            console.log('[notify] Timer started (%sms tick)', TICK_MS);
        }
    },
};

console.log('[utils/notify] Initialized');
