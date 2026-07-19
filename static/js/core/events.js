// ═══════════════════════════════════════════════════════════════
// core/events.js — Pub/sub event bus
// ═══════════════════════════════════════════════════════════════
//
// 跨模块消息传递。store 用于「状态变化通知」，events 用于「行为通知」
// (如 stream:state, toast:show, settings:opened)。
//
// 依赖: 零
// 被依赖: api, stream, 所有 components
//
// 用法:
//   import { events } from './core/events.js';
//   events.on('topic', (data) => {...});
//   events.emit('topic', { key: 'val' });
// ═══════════════════════════════════════════════════════════════

const _topics = {};   // { topic: [callback, ...] }
let _seq = 0;          // 事件序号, 调试用

export const events = {
    /**
     * 订阅主题。
     * @param {string} topic
     * @param {function} fn  — fn(data)
     */
    on(topic, fn) {
        (_topics[topic] = _topics[topic] || []).push(fn);
        console.log('[events] on("%s") — %s listener(s)', topic, _topics[topic].length);
    },

    /**
     * 取消订阅。
     */
    off(topic, fn) {
        const arr = _topics[topic];
        if (!arr) return;
        _topics[topic] = arr.filter(f => f !== fn);
    },

    /**
     * 发送事件。
     * @param {string} topic
     * @param {*} data
     */
    emit(topic, data) {
        const arr = _topics[topic];
        if (!arr || !arr.length) return;
        _seq++;
        const id = _seq;
        // 先复制数组 — 防止回调里 off() 导致遍历异常
        [...arr].forEach(fn => {
            try { fn(data); }
            catch (e) { console.error('[events] listener error for "%s" (#%s):', topic, id, e); }
        });
    },

    /**
     * 清空某个主题的所有监听器。
     */
    clear(topic) {
        delete _topics[topic];
    },

    /**
     * 调试: 列出所有活跃主题。
     */
    debug() {
        const result = {};
        for (const [t, fns] of Object.entries(_topics)) {
            result[t] = fns.length;
        }
        return result;
    },
};

console.log('[events] Initialized');
