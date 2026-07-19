// ═══════════════════════════════════════════════════════════════
// services/stream.js — StreamSession client state machine
// ═══════════════════════════════════════════════════════════════
//
// 管理单次 SSE 流的生命周期:
//   IDLE → CONNECTING → THINKING → GENERATING → COMPLETED
//                      ↘ WAITING (disconnect → polling)
//
// 依赖: state (读 currentConvId), events (发 stream:state)
// 被依赖: chat (doSendSSE), app (visibility恢复), render (状态同步)
//
// 用法:
//   import { getStream } from './services/stream.js';
//   const s = getStream();
//   s.start(convId);
//   s.onText();
//   s.onComplete();
// ═══════════════════════════════════════════════════════════════

import { state } from '../core/store.js';
import { events } from '../core/events.js';
import { api } from './api.js';

// ── 状态枚举 ─────────────────────────────────────────────────
const STATES = {
    IDLE:         'idle',
    CONNECTING:   'connecting',
    THINKING:     'thinking',
    GENERATING:   'generating',
    INTERRUPTING: 'interrupting',
    WAITING:      'waiting',
    COMPLETED:    'completed',
    ERROR:        'error',
};

// ═══════════════════════════════════════════════════════════════
// StreamSession class
// ═══════════════════════════════════════════════════════════════

class StreamSession {
    constructor() {
        this.state    = STATES.IDLE;
        this._convId  = null;
        this._pollTimer = null;
        this._pollAttempts = 0;
        this._pollUnchanged = 0;
    }

    // ── 状态迁移 ──────────────────────────────────────────

    start(convId) {
        this.reset();
        this._convId = convId;
        this._transition(STATES.CONNECTING);
        console.log('[stream] start → CONNECTING conv=%s', (convId || '').slice(0, 8));
    }

    onThinking() {
        if (this.state === STATES.CONNECTING || this.state === STATES.THINKING) {
            this._transition(STATES.THINKING);
        }
    }

    onText() {
        if (this.state !== STATES.IDLE && this.state !== STATES.COMPLETED && this.state !== STATES.ERROR) {
            this._transition(STATES.GENERATING);
        }
    }

    onComplete() {
        this._stopPoll();
        this._transition(STATES.COMPLETED);
        console.log('[stream] → COMPLETED');
    }

    onInterrupt() {
        if (this.state === STATES.COMPLETED || this.state === STATES.IDLE) return;
        this._transition(STATES.INTERRUPTING);
        console.log('[stream] → INTERRUPTING');
    }

    onDisconnect() {
        if (this.state === STATES.COMPLETED || this.state === STATES.IDLE) return;
        this._transition(STATES.WAITING);
        console.log('[stream] → WAITING (disconnected, start polling)');
        this._startPoll();
    }

    onError() {
        this._stopPoll();
        this._transition(STATES.ERROR);
        console.log('[stream] → ERROR');
    }

    reset() {
        this._stopPoll();
        if (this.state !== STATES.IDLE) {
            console.log('[stream] reset (%s → IDLE)', this.state);
        }
        this.state = STATES.IDLE;
        this._pollAttempts = 0;
        this._pollUnchanged = 0;
    }

    // ── 查询 ──────────────────────────────────────────────

    isActive() {
        return this.state !== STATES.IDLE && this.state !== STATES.COMPLETED && this.state !== STATES.ERROR;
    }

    isLive() {
        return this.state === STATES.CONNECTING || this.state === STATES.THINKING || this.state === STATES.GENERATING;
    }

    // ── 内部 ──────────────────────────────────────────────

    _transition(newState) {
        this.state = newState;
        events.emit('stream:state', newState);
    }

    // ── 轮询 (WAITING 状态) ───────────────────────────────

    _startPoll() {
        this._stopPoll();
        this._pollAttempts = 0;
        this._pollUnchanged = 0;
        this._doPoll();
    }

    _stopPoll() {
        if (this._pollTimer) {
            clearTimeout(this._pollTimer);
            this._pollTimer = null;
        }
    }

    _doPoll() {
        if (this.state !== STATES.WAITING) return;
        if (!state.currentConvId || state.currentConvId !== this._convId) return;
        if (this._pollAttempts >= 60) { this._stopPoll(); return; }

        const delay = this._pollAttempts < 3  ? 2000
                    : this._pollAttempts < 10 ? 3000
                    : this._pollAttempts < 30 ? 5000
                    : 10000;

        this._pollTimer = setTimeout(() => {
            if (this.state !== STATES.WAITING) return;
            if (!state.currentConvId || state.currentConvId !== this._convId) return;

            api.getMessages(this._convId).then(d => {
                if (this.state !== STATES.WAITING) return;
                if (!d || !d.messages || !d.messages.length) return;

                const lastMsg = d.messages[d.messages.length - 1];
                const stillStreaming = d.streaming && d.streaming.status !== 'finalized';

                console.log('[stream] poll #%s streaming=%s stillStreaming=%s',
                    this._pollAttempts, d.streaming?.status, stillStreaming);

                if (!stillStreaming) {
                    // Backend finalized
                    events.emit('render:refresh', { messages: d.messages, streaming: d.streaming });
                    this._transition(STATES.COMPLETED);
                    return;
                }

                // Check for content changes in DOM
                const el = document.querySelector('.msg.streaming');
                if (el) {
                    const ce = el.querySelector('.msg-content');
                    const curContent = ce ? (ce.textContent || '') : '';
                    const newContent = lastMsg ? (lastMsg.content || '') : '';
                    const tf = el.querySelector('.thinking-content');
                    const curThinking = tf ? (tf.textContent || '') : '';
                    const newThinking = lastMsg ? (lastMsg.thinking || '') : '';

                    if (newContent !== curContent || newThinking !== curThinking) {
                        this._pollUnchanged = 0;
                        if (newThinking && !tf) {
                            events.emit('render:refresh', { messages: d.messages, streaming: d.streaming });
                        } else {
                            if (newContent && ce) ce.textContent = newContent;
                            if (newThinking !== curThinking && tf) tf.textContent = newThinking;
                            events.emit('render:scroll');
                        }
                    } else {
                        this._pollUnchanged++;
                    }

                    // Safety net: 3+ polls unchanged with thinking → force complete
                    if (this._pollUnchanged >= 3 && lastMsg && lastMsg.thinking) {
                        events.emit('render:refresh', { messages: d.messages, streaming: d.streaming });
                        this._transition(STATES.COMPLETED);
                        return;
                    }
                } else {
                    events.emit('render:refresh', { messages: d.messages, streaming: d.streaming });
                }

                this._pollAttempts++;
                this._doPoll();
            }).catch(() => {
                this._pollAttempts++;
                this._doPoll();
            });
        }, delay);
    }
}

// ═══════════════════════════════════════════════════════════════
// 全局单例
// ═══════════════════════════════════════════════════════════════

let _instance = null;

/**
 * 获取或创建唯一的 StreamSession 实例。
 * @returns {StreamSession}
 */
export function getStream() {
    if (!_instance) _instance = new StreamSession();
    return _instance;
}

/**
 * 重置当前流 (切对话 / 发新消息时调用)。
 */
export function resetStream() {
    if (_instance) _instance.reset();
}

console.log('[stream] Initialized');
