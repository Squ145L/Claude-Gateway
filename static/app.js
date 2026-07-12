// ═══════════════════════════
// Claude Gateway — Chat PWA
// ═══════════════════════════
var $ = function (s) { return document.querySelector(s); };
/**
 * ── Background Recovery ──
 *
 * When the user backgrounds the PWA (switch apps, lock screen) and comes back:
 * 1. If a message is currently streaming (.msg.streaming exists in DOM),
 *    skip reload — don't destroy the live SSE rendering. Let r.done finish.
 * 2. Otherwise, reload messages from the server to catch any that completed
 *    while the page was suspended (SSE may have been cut off mid-stream).
 *
 * Only triggers when: page becomes visible AND we're in a conversation.
 */
document.addEventListener('visibilitychange', function onVisibilityChange() {
    if (document.hidden) return;
    if (!state.currentConvId) return;

    var _pollTimer = null, _pollAttempts = 0;

    function reloadAndMaybePoll() {
        apiGet('/api/conversations/' + state.currentConvId)
            .then(function onMessagesLoaded(d) {
                if (!d.messages || !d.messages.length) return;
                renderMessages(d.messages);
                showToast('↻ 已恢复', '');
                var folds = msgsContainer.querySelectorAll('.thinking-fold');
                if (folds.length) { folds[folds.length - 1].classList.add('open'); }
                void msgsContainer.offsetHeight;
                msgsContainer.scrollTop = msgsContainer.scrollHeight;
                // If no streaming msg remains, we're done
                if (!msgsContainer.querySelector('.msg.streaming')) {
                    if (_pollTimer) { clearTimeout(_pollTimer); _pollTimer = null; }
                }
            })
            .catch(function onError(err) {
                // Retry on network error
            });

        // If a streaming message is still in DOM, the response may still be generating.
        // Poll until it completes (new msg saved) or timeout 30s.
        if (msgsContainer.querySelector('.msg.streaming')) {
            _pollAttempts++;
            if (_pollAttempts < 15) {
                _pollTimer = setTimeout(reloadAndMaybePoll, 2000);
            }
        }
    }
    reloadAndMaybePoll();
});

var state = {
    serverUrl: localStorage.getItem('cg_server_url') || window.location.origin,
    secret: localStorage.getItem('cg_secret') || '',
    currentConvId: null, pendingFiles: [],
    batchMode: false, selectedConvs: {}, confirmCallback: null,
    ctxTarget: null, // context menu target conversation id
};
if (!localStorage.getItem('cg_server_url')) { state.serverUrl = window.location.origin; localStorage.setItem('cg_server_url', state.serverUrl); }

// ═══════════════════ Settings Screen ═══════════════════
var settingsScreen = $('#settings-screen'), chatScreen = $('#chat-screen'),
    secretInput = $('#auth-secret'), connectBtn = $('#connect-btn'), connectStatus = $('#connect-status');
secretInput.value = state.secret;
function doConnect() {
    var s = secretInput.value.trim();
    if (!s) { secretInput.style.borderColor = 'var(--danger)'; setTimeout(function(){secretInput.style.borderColor=''},1500); return; }
    secretInput.style.borderColor = '';
    connectStatus.textContent = '验证中...'; connectStatus.className = 'status-text'; connectBtn.disabled = true;
    fetch(state.serverUrl + '/api/auth/verify', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({secret:s}) })
    .then(function(r){
        if (!r.ok) throw new Error(_errMsg(r.status));
        return r.json();
    }).then(function(d){
        if(d.valid){ state.secret=s; localStorage.setItem('cg_secret',s); connectStatus.textContent='已连接'; connectStatus.className='status-text success'; setTimeout(function(){showChatScreen()},300); }
        else{ secretInput.value=''; secretInput.focus(); connectStatus.textContent='密钥错误，请重试'; connectStatus.className='status-text error'; secretInput.style.borderColor='var(--danger)'; setTimeout(function(){secretInput.style.borderColor=''},2000); }
    }).catch(function(e){
        connectStatus.textContent = e.message || '连接失败';
        connectStatus.className = 'status-text error';
    }).finally(function(){ connectBtn.disabled=false; });
}
window._gwConnect = doConnect;
connectBtn.addEventListener('click',doConnect);
secretInput.addEventListener('keydown',function(e){if(e.key==='Enter')doConnect()});
function showChatScreen(){ settingsScreen.classList.remove('active'); chatScreen.classList.add('active'); loadConversations(); updateWelcomeState(); }

// ═══════════════════ API ═══════════════════
function apiH(){ return {'Authorization':'Bearer '+state.secret,'Content-Type':'application/json'}; }
var _errs={400:'请求有误',401:'密钥错误',404:'未找到',413:'文件过大',429:'请求太频繁',500:'服务器内部错误',502:'服务器未开启',503:'服务器繁忙',504:'连接超时'};
function _errMsg(s){var m=_errs[s]||'网络错误';return '[错误]'+s+':'+m}
function apiGet(p){ return fetch(state.serverUrl+p,{headers:apiH()}).then(function(r){if(!r.ok)throw new Error(_errMsg(r.status));return r.json()}); }
function apiPost(p,b){ return fetch(state.serverUrl+p,{method:'POST',headers:apiH(),body:JSON.stringify(b||{})}).then(function(r){if(!r.ok)throw new Error(_errMsg(r.status));return r.json()}); }

// ═══════════════════ SSE Chat ═══════════════════
function streamChat(userText, fileIds) {
    return fetch(state.serverUrl + '/api/chat', {
        method: 'POST',
        headers: { 'Authorization': 'Bearer ' + state.secret, 'Content-Type': 'application/json' },
        body: JSON.stringify({ conversation_id: state.currentConvId, message: userText, file_ids: fileIds || [], show_thinking: true }),
    });
}

// ═══════════════════ Chat ═══════════════════
var msgInput = $('#msg-input'), sendBtn = $('#send-btn'), plusBtn = $('#plus-btn'),
    msgsContainer = $('#messages-container'), fileInput = $('#file-input'), filePreviewBar = $('#file-preview-bar'),
    actionSheet = $('#action-sheet'), actionOverlay = $('#action-sheet-overlay'),
    composeBar = $('#compose-bar'), welcomeScreen = $('#welcome-screen'),
    welcomeInput = $('#welcome-input'), welcomeSendBtn = $('#welcome-send-btn'),
    welcomePlusBtn = $('#welcome-plus-btn');

// ── Welcome screen ──
function updateWelcomeState() {
    var hasMsgs = msgsContainer.querySelector('.msg');
    if (!state.currentConvId && !hasMsgs) {
        msgsContainer.style.display = 'none';
        welcomeScreen.classList.add('active');
        composeBar.classList.add('hidden');
    } else {
        msgsContainer.style.display = '';
        welcomeScreen.classList.remove('active');
        composeBar.classList.remove('hidden');
    }
}

// Welcome input → send
function welcomeSend() {
    var text = welcomeInput.value.trim();
    if (!text && state.pendingFiles.length === 0) return;
    welcomeInput.value = '';
    msgsContainer.style.display = '';
    welcomeScreen.classList.remove('active');
    composeBar.classList.remove('hidden');
    msgInput.value = text;
    sendMessage();
}
welcomeSendBtn.addEventListener('click', welcomeSend);
welcomePlusBtn.addEventListener('click', function(e) { e.stopPropagation(); toggleActionSheet(); });
if (!_isMobile) {
    welcomeInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); welcomeSend(); }
    });
}

// Plus button
function toggleActionSheet() {
    var open = !actionSheet.classList.contains('show');
    if (open) { actionSheet.classList.remove('hidden'); actionOverlay.classList.remove('hidden'); actionSheet.offsetHeight; actionSheet.classList.add('show'); plusBtn.classList.add('active'); }
    else closeActionSheet();
}
function closeActionSheet() { actionSheet.classList.remove('show'); plusBtn.classList.remove('active'); setTimeout(function(){actionSheet.classList.add('hidden');actionOverlay.classList.add('hidden')},250); }
plusBtn.addEventListener('click',toggleActionSheet); actionOverlay.addEventListener('click',closeActionSheet); $('#action-cancel').addEventListener('click',closeActionSheet);

function autoResizeTextarea() {
    msgInput.style.height = 'auto';
    msgInput.style.height = (msgInput.scrollHeight) + 'px';
}
function updateComposeButtons() {
    var hasText = msgInput.value.trim().length > 0 || state.pendingFiles.length > 0;
    if (hasText) { sendBtn.classList.remove('hidden'); } else { sendBtn.classList.add('hidden'); }
    autoResizeTextarea();
}
msgInput.addEventListener('input', updateComposeButtons);

sendBtn.addEventListener('click', sendMessage);
var _isMobile = /Mobi|Android/i.test(navigator.userAgent) || ('ontouchstart' in window && window.innerWidth < 768);
var _isTouch = ('ontouchstart' in window || navigator.maxTouchPoints > 0);
if (!_isMobile) {
    msgInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });
}

// File actions
$('#action-camera').addEventListener('click',function(){closeActionSheet();$('#camera-input').click()});
$('#action-album').addEventListener('click',function(){closeActionSheet();$('#album-input').click()});
$('#action-file').addEventListener('click',function(){closeActionSheet();fileInput.click()});
$('#action-status').addEventListener('click',function(){closeActionSheet();
    fetch(state.serverUrl+'/api/health').then(function(r){return r.json()}).then(function(d){showToast('OK: '+d.status+' | Claude: '+d.claude_cli)}).catch(function(){showToast('无法连接','error')});
});
/**
 * ── File Upload Handler ──
 * Uploads files to the server and stores metadata in pendingFiles.
 * Image files get a local blob preview URL for inline thumbnail display.
 */
function handleFileInput(input) {
    var files = input.files;
    for (var i = 0; i < files.length; i++) {
        (function uploadOne(f) {
            var isImg = /\.(png|jpe?g|gif|webp|bmp)$/i.test(f.name);
            var previewUrl = isImg ? URL.createObjectURL(f) : null;

            showToast('上传 ' + f.name + '...');

            var fd = new FormData();
            fd.append('file', f);
            fetch(state.serverUrl + '/api/files/upload', {
                method: 'POST',
                headers: { 'Authorization': 'Bearer ' + state.secret },
                body: fd,
            })
            .then(function(r) { return r.json(); })
            .then(function onUploaded(r) {
                state.pendingFiles.push({
                    name: f.name,
                    file_id: r.file_id,
                    preview: previewUrl,  // blob URL for images, null for others
                });
                updateFilePreview();
                updateComposeButtons();
            })
            .catch(function() { showToast('上传失败', 'error'); });
        })(files[i]);
    }
    input.value = '';
}
$('#camera-input').addEventListener('change', function() { handleFileInput(this); });
$('#album-input').addEventListener('change', function() { handleFileInput(this); });
fileInput.addEventListener('change', function() { handleFileInput(this); });

/**
 * ── File Preview Bar ──
 * Shows pending files above the compose bar.
 * Image files show a small thumbnail; all files show the filename chip.
 */
function updateFilePreview() {
    if (state.pendingFiles.length === 0) {
        filePreviewBar.classList.add('hidden');
        return;
    }
    filePreviewBar.classList.remove('hidden');
    filePreviewBar.innerHTML = state.pendingFiles.map(function(f, i) {
        var thumb = f.preview
            ? '<img class="file-preview-thumb" src="' + f.preview + '" alt="">'
            : '';
        return '<span class="file-chip">'
            + thumb
            + escHtml(f.name)
            + '<span class="remove" onclick="removeFile(' + i + ')">✕</span>'
            + '</span>';
    }).join('');
}
function removeFile(i) {
    var f = state.pendingFiles[i];
    if (f && f.preview) URL.revokeObjectURL(f.preview);  // free blob memory
    state.pendingFiles.splice(i, 1);
    updateFilePreview();
    updateComposeButtons();
}

function sendMessage() {
    var text = msgInput.value.trim();
    if (!text && state.pendingFiles.length === 0) return;
    msgInput.value = ''; sendBtn.disabled = true; updateComposeButtons();
    var userText = text || '[文件]';

    if (!state.currentConvId) {
        apiPost('/api/conversations').then(function(d){ state.currentConvId = d.id; doSendSSE(userText); }).catch(function(){showToast('创建对话失败','error')});
        return;
    }
    doSendSSE(userText);
}

function doSendSSE(userText) {
    // Capture full file info before clearing pendingFiles (needed for history restore)
    var uploadFiles = state.pendingFiles.map(function(f) {
        return { name: f.name, file_id: f.file_id, preview: f.preview };
    });
    // API expects [{id, name}] — stored in DB so history messages can reconstruct
    var fileIds = uploadFiles.map(function(f) { return { id: f.file_id, name: f.name }; });
    // Escape [FILE: and [DOWNLOAD: so user-typed file tags render as plain text
    var displayText = userText.replace(/\[(FILE|DOWNLOAD):/gi, '\\[$1]:');
    appendMessage({role:'user',content:displayText}, uploadFiles);
    state.pendingFiles = []; updateFilePreview(); updateWelcomeState();

    var aiEl = appendMessage({role:'assistant',content:''}, [], true);
    var statusEl = document.createElement('div'); statusEl.className='status-bar';
    statusEl.innerHTML = '<span class="thinking-dots"><span></span><span></span><span></span></span>  Thinking...';
    aiEl.insertBefore(statusEl, aiEl.firstChild);
    updateStatus(statusEl, 'thinking');
    var thinkingP = [], textP = [], tokens = null, thinkingStart = null, thinkingEnd = false;

    streamChat(userText, fileIds).then(function(resp) {
        if (!resp.ok) { throw new Error(_errMsg(resp.status)); }
        var reader = resp.body.getReader(), decoder = new TextDecoder(), buf = '';

        function pump() {
            return reader.read().then(function(r) {
                if (r.done) {
                    aiEl.classList.remove('streaming');
                    if (statusEl) { statusEl.remove(); statusEl = null; }
                    if (!thinkingP.length) removeThinkingFold(aiEl);
                    if (thinkingP.length && !textP.length) {
                        // Only thinking, no text — show as content
                        var ce = aiEl.querySelector('.msg-content');
                        if (ce) ce.innerHTML = renderMarkdown(thinkingP.join(''));
                        removeThinkingFold(aiEl);
                    }
                    var contentEl = aiEl.querySelector('.msg-content');
                    if (contentEl) {
                        var final = textP.join('');
                        if (!final && thinkingP.length) final = thinkingP.join('');
                        if (final) contentEl.innerHTML = renderMarkdown(final);
                    }

                    // ── Footer: token + timestamp (always created) ──
                    var footer = aiEl._footer;
                    if (!footer) {
                        footer = document.createElement('div');
                        footer.className = 'msg-footer';
                        aiEl.appendChild(footer);
                        aiEl._footer = footer;
                    }
                    var now = new Date().toLocaleTimeString();
                    var tokenHtml = '';
                    if (tokens) {
                        tokenHtml = '<span class="token-info">↑ ' + tokens.i + '   ↓ ' + tokens.o + '</span>';
                    }
                    footer.innerHTML = tokenHtml + '<span class="timestamp">' + now + '</span>';
                    loadConversations();
                    updateWelcomeState();
                    // Force reflow then synchronous scroll — same as appendMessage
                    void msgsContainer.offsetHeight;
                    msgsContainer.scrollTop = msgsContainer.scrollHeight;
                    return;
                }
                buf += decoder.decode(r.value, {stream:true});
                var lines = buf.split('\n'); buf = lines.pop() || '';
                for (var i=0; i<lines.length; i++) {
                    if (lines[i].indexOf('data: ') !== 0) continue;
                    try { var c = JSON.parse(lines[i].slice(6)); }
                    catch(e) { continue; }
                    if (c.type === 'text') {
                        if (!thinkingEnd && thinkingP.length) {
                            thinkingEnd = true;
                            var ms = Date.now() - thinkingStart;
                            var durTxt = ms >= 60000 ? Math.floor(ms/60000)+'m '+Math.floor((ms%60000)/1000)+'s' : (ms/1000).toFixed(1)+'s';
                            var wc = thinkingP.join('').split(/\s+/).filter(Boolean).length;
                            updateThinkingLabel(aiEl, durTxt, wc);
                        }
                        textP.push(c.content);
                        updateStatus(statusEl, 'text');
                        updateAssistantContent(aiEl, textP.join(''));
                    } else if (c.type === 'thinking') {
                        if (!thinkingStart) thinkingStart = Date.now();
                        thinkingP.push(c.content);
                        updateStatus(statusEl, 'thinking');
                        updateThinkingFold(aiEl, thinkingP.join(''));
                    } else if (c.type === 'status') {
                        if (c.state === 'done') { updateStatus(statusEl, 'done'); }
                        else { updateStatus(statusEl, 'tool', c.tool); }
                    } else if (c.type === 'done') {
                        if (c.usage) tokens = {i:fmtNum(c.usage.i), o:fmtNum(c.usage.o)};
                        if (!state.currentConvId) { state.currentConvId = c.conversation_id; loadConversations(); }
                    } else if (c.type === 'error') {
                        if (statusEl) statusEl.remove(); statusEl = null;
                        updateAssistantContent(aiEl, c.content);
                    }
                }
                return pump();
            });
        }
        return pump();
    }).catch(function(e) {
        if (statusEl) statusEl.remove(); statusEl = null;
        aiEl.classList.remove('streaming');
        // Reload from DB — backend CancelledError saves partial response
        if (state.currentConvId) {
            apiGet('/api/conversations/' + state.currentConvId).then(function(d) {
                if (d.messages && d.messages.length) renderMessages(d.messages);
            }).catch(function() {});
        }
        showToast('连接断开，已自动恢复', '');
        void msgsContainer.offsetHeight;
        msgsContainer.scrollTop = msgsContainer.scrollHeight;
    }).finally(function() {
        sendBtn.disabled = false; if (msgInput) msgInput.focus();
    });
}
function fmtNum(n){return n>=1000?(n/1000).toFixed(1)+'k':String(n)}

// ═══════════════════ Dynamic Status Bar ═══════════════════
// Geek-style terminal verbs — all prefixed with bouncing dots
var TOOL_VERBS = {
    'Read': 'Reading', 'Glob': 'Scanning', 'Grep': 'Searching',
    'Bash': 'Bashing', 'PowerShell': 'Executing',
    'Edit': 'Editing', 'Write': 'Writing',
    'WebSearch': 'Crawling', 'WebFetch': 'Fetching',
    'Task': 'Dispatching', 'Agent': 'Dispatching',
    'TodoWrite': 'Planning', 'TaskCreate': 'Planning',
};

function updateStatus(el, type, tool) {
    if (!el) return;
    var dots = '<span class="thinking-dots"><span></span><span></span><span></span></span>';
    if (type === 'thinking') {
        el.innerHTML = dots + '  Thinking...';
    } else if (type === 'text') {
        el.innerHTML = dots + '  Writing...';
    } else if (type === 'tool') {
        el.innerHTML = dots + '  ' + (TOOL_VERBS[tool] || tool) + '...';
    } else if (type === 'done') {
        el.innerHTML = dots + '  Done.';
    }
}

// ═══════════════════ Messages ═══════════════════
function appendMessage(msg, files, streaming) {
    var el = document.createElement('div');
    el.className = 'msg ' + msg.role + (streaming ? ' streaming' : '');
    if (files && files.length) {
        var b = document.createElement('div'); b.className = 'file-badges';
        b.innerHTML = files.map(function(f) {
            var chip = '<span class="file-badge">📎 ' + escHtml(f.name) + '</span>';
            // Show inline thumbnail for uploaded images
            if (f.preview) {
                chip += '<img class="user-upload-preview" src="' + f.preview + '" alt="' + escHtml(f.name) + '">';
            }
            return chip;
        }).join('');
        el.appendChild(b);
    }
    var cd = document.createElement('div'); cd.className = 'msg-content';
    if (streaming) cd.textContent = ''; else cd.innerHTML = renderMarkdown(msg.content||'');
    el.appendChild(cd);
    if (msg.role === 'assistant' && msg.thinking) { addThinkingFold(el, msg.thinking, msg.thinking_dur, msg.thinking_wc); }
    if (msg.created_at && !streaming) {
        var ft = document.createElement('div'); ft.className='msg-footer';
        var tu="";if(msg.token_usage){try{var u2=JSON.parse(msg.token_usage);tu='<span class="token-info">↑ '+fmtNum(u2.i)+'   ↓ '+fmtNum(u2.o)+'</span>'}catch(e){}};ft.innerHTML=tu+"<span class=\"timestamp\">"+new Date(msg.created_at).toLocaleTimeString()+"</span>"
        el.appendChild(ft);
        el._footer = ft;
    }
    msgsContainer.appendChild(el); requestAnimationFrame(function(){el.classList.add('msg-enter')}); msgsContainer.scrollTop = msgsContainer.scrollHeight;
    return el;
}
document.addEventListener('click',function(e){var h3=e.target.closest('.settings-section h3');if(!h3)return;var s=h3.parentElement,b=s.querySelector('.section-body');if(!b)return;if(s.classList.contains('collapsed')){s.classList.remove('collapsed');b.style.maxHeight=b.scrollHeight+'px'}else{s.classList.add('collapsed');b.style.maxHeight='0px'}});
document.addEventListener('DOMContentLoaded',function(){var ss=document.querySelectorAll('.settings-section');ss.forEach(function(s,i){var b=s.querySelector('.section-body');if(b)b.style.maxHeight=i===0?b.scrollHeight+'px':'0px';if(i!==0)s.classList.add('collapsed')})});
function updateAssistantContent(el, text) { var c = el.querySelector('.msg-content'); if (c) c.textContent = text; msgsContainer.scrollTop = msgsContainer.scrollHeight; }
function updateThinkingFold(el, text) {
    var fold = el.querySelector('.thinking-fold');
    if (!fold) {
        fold = document.createElement('div'); fold.className = 'thinking-fold';
        fold.innerHTML = '<div class="thinking-header" onclick="this.parentElement.classList.toggle(\'open\')"><span>Thinking...</span><span>▶</span></div><div class="thinking-content"></div>';
        el.insertBefore(fold, el.querySelector('.msg-content'));
    }
    fold.querySelector('.thinking-content').textContent = text;
}
function updateThinkingLabel(el, dur, wc) {
    var hdr = el.querySelector('.thinking-header');
    if (hdr) hdr.innerHTML = '<span>已思考(' + dur + ') — ' + wc + ' words</span><span>▶</span>';
}
function addThinkingFold(el, text, dur, wc) {
    var fold = document.createElement('div'); fold.className = 'thinking-fold';
    if (!wc) wc = text.split(/\s+/).filter(Boolean).length;
    var label = dur ? '已思考(' + dur + ') — ' + wc + ' words' : wc + ' words';
    fold.innerHTML = '<div class="thinking-header" onclick="this.parentElement.classList.toggle(\'open\')"><span>' + label + '</span><span>▶</span></div><div class="thinking-content">'+escHtml(text)+'</div>';
    el.insertBefore(fold, el.querySelector('.msg-content'));
}
function removeThinkingFold(el) { var f = el.querySelector('.thinking-fold'); if (f) f.remove(); }
/**
 * ── Render Messages from History ──
 * Reconstructs file info from file_ids JSON so uploaded images show
 * inline thumbnails even after switching conversations and coming back.
 * Uses server /files/view/ endpoint instead of ephemeral blob URLs.
 */
function renderMessages(msgs) {
    msgsContainer.innerHTML = '';
    for (var i = 0; i < msgs.length; i++) {
        var msg = msgs[i];
        var files = null;
        // Reconstruct file array from stored file_ids JSON
        if (msg.file_ids) {
            try {
                var ids = JSON.parse(msg.file_ids);
                if (Array.isArray(ids) && ids.length) {
                    files = ids.map(function(f) {
                        var name = typeof f === 'string' ? f : (f.name || f.id || '');
                        var isImg = /\.(png|jpe?g|gif|webp|bmp)$/i.test(name);
                        return {
                            name: name,
                            file_id: typeof f === 'string' ? f : (f.id || ''),
                            // Server view URL for persistent image thumbnails
                            preview: isImg
                                ? state.serverUrl + '/api/files/view/' + encodeURIComponent(name) + '?token=' + encodeURIComponent(state.secret)
                                : null,
                        };
                    });
                }
            } catch (e) { /* ignore parse errors */ }
        }
        appendMessage(msg, files);
    }
    msgsContainer.scrollTop = msgsContainer.scrollHeight;
    updateWelcomeState();
}

// ═══════════════════ Sidebar ═══════════════════
var sidebar = $('#sidebar'), sidebarOverlay = $('#sidebar-overlay'), convList = $('#conversation-list'),
    currentTitle = $('#current-title'), batchBtn = $('#batch-btn'), batchBar = $('#batch-bar'), batchCount = $('#batch-count');
function openSidebar(){sidebar.classList.remove('hidden');sidebarOverlay.classList.remove('hidden');loadConversations()}
function closeSidebar(){sidebar.classList.add('hidden');sidebarOverlay.classList.add('hidden');exitBatchMode()}
sidebarOverlay.addEventListener('click',closeSidebar); $('#menu-btn').addEventListener('click',openSidebar);

function loadConversations(){apiGet('/api/conversations').then(function(d){renderConvList(d.conversations)}).catch(function(){})}
function renderConvList(convs) {
    convList.innerHTML = '';
    if (!convs||!convs.length) { convList.innerHTML = '<div style="padding:24px;text-align:center;color:var(--text-dim);font-size:0.85rem">暂无对话</div>'; return; }
    for(var i=0;i<convs.length;i++){(function(c){
        var item = document.createElement('div');
        item.className = 'conv-item' + (c.id===state.currentConvId?' active':'');
        item.setAttribute('data-cid', c.id);
        if(state.batchMode) item.classList.add('batch-mode');
        if(state.selectedConvs[c.id]) item.classList.add('selected');
        var extraBtns = _isTouch ? '' : '<span class="rename-conv" title="重命名">✏️</span><span class="delete-conv">✕</span>';
        var dateStr = '';
        if (c.updated_at) {
            var d = new Date(c.updated_at);
            var thisYear = new Date().getFullYear();
            dateStr = d.getFullYear() === thisYear
                ? (d.getMonth() + 1) + '/' + d.getDate()
                : d.getFullYear() + '/' + (d.getMonth() + 1) + '/' + d.getDate();
        }
        item.innerHTML = '<span class="conv-check"></span><span class="conv-title">'+escHtml(c.title)+'</span><span class="conv-time">'+dateStr+'</span>'+extraBtns;

        // Click item → switch conversation (unless in batch mode)
        item.addEventListener('click',function(e){if(state.batchMode){toggleConvSelect(c.id,item);return} switchConversation(c.id); closeSidebar()});

        // Long press → context menu (mobile)
        var pressTimer = null;
        item.addEventListener('touchstart', function(e) {
            pressTimer = setTimeout(function() {
                pressTimer = null;
                navigator.vibrate && navigator.vibrate(20);
                state.ctxTarget = {id: c.id, title: c.title, el: item};
                showCtxMenu();
            }, 500);
        }, {passive: true});
        item.addEventListener('touchend', function() { if (pressTimer) { clearTimeout(pressTimer); pressTimer = null; } });
        item.addEventListener('touchmove', function() { if (pressTimer) { clearTimeout(pressTimer); pressTimer = null; } });

        // Delete (desktop only — buttons not rendered on touch)
        var delBtn = item.querySelector('.delete-conv');
        if (delBtn) delBtn.addEventListener('click',function(evt){evt.stopPropagation();showConfirm('删除: '+c.title+'？',function(){
            fetch(state.serverUrl+'/api/conversations/'+c.id,{method:'DELETE',headers:apiH()}).then(function(){if(state.currentConvId===c.id){state.currentConvId=null;$('#messages-container').innerHTML=''} loadConversations()}).catch(function(){})
        })});

        // Rename (desktop only — buttons not rendered on touch)
        var renameBtn = item.querySelector('.rename-conv');
        if (renameBtn) renameBtn.addEventListener('click',function(evt){evt.stopPropagation();
            var titleSpan = item.querySelector('.conv-title');
            var oldTitle = titleSpan.textContent;
            var inp = document.createElement('input');
            inp.className = 'conv-title-input'; inp.value = oldTitle;
            titleSpan.replaceWith(inp); inp.focus(); inp.select();

            function finish(save) {
                if (!inp.parentNode) return;  // already finished
                var newTitle = save ? inp.value.trim() : '';
                if (save && newTitle && newTitle !== oldTitle) {
                    renameConversation(c.id, newTitle);
                } else {
                    titleSpan.textContent = oldTitle;
                }
                if (inp.parentNode) inp.replaceWith(titleSpan);
            }
            inp.addEventListener('keydown', function(e) {
                if (e.key === 'Enter') { e.preventDefault(); finish(true); }
                else if (e.key === 'Escape') { e.preventDefault(); finish(false); }
            });
            inp.addEventListener('blur', function() { finish(true); });
        });

        convList.appendChild(item);
    })(convs[i])}
}
function switchConversation(convId) {
    state.currentConvId = convId;
    apiGet('/api/conversations/'+convId).then(function(d){
        currentTitle.textContent=d.conversation.title;
        renderMessages(d.messages);
        // Ensure scroll to bottom after DOM paints
        requestAnimationFrame(function() {
            msgsContainer.scrollTop = msgsContainer.scrollHeight;
        });
    }).catch(function(){});
    loadConversations();
}
function renameConversation(convId, newTitle) {
    return apiPost('/api/conversations/'+convId+'/title', {title: newTitle}).then(function(d) {
        if (convId === state.currentConvId) { currentTitle.textContent = d.title; }
        loadConversations();
        return d;
    });
}

// ── Title inline edit ──
function startTitleEdit() {
    if (!state.currentConvId || currentTitle._editing) return;
    var old = currentTitle.textContent.trim();
    currentTitle._editing = true;
    var input = document.createElement('input');
    input.className = 'chat-title-input'; input.value = old;
    var okBtn = document.createElement('button'); okBtn.className = 'confirm-edit-btn'; okBtn.textContent = '✓';

    currentTitle.replaceWith(input); input.focus(); input.select();
    input.parentNode.insertBefore(okBtn, input.nextSibling);

    function finish(save) {
        if (!input.parentNode) return;  // already finished
        var newTitle = save ? input.value.trim() : '';
        if (save && newTitle && newTitle !== old) {
            renameConversation(state.currentConvId, newTitle);
        } else if (!save) {
            currentTitle.textContent = old;
        }
        input.replaceWith(currentTitle);
        if (okBtn.parentNode) okBtn.remove();
        currentTitle._editing = false;
    }
    input.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') { e.preventDefault(); finish(true); }
        else if (e.key === 'Escape') { e.preventDefault(); finish(false); }
    });
    // Click outside = cancel
    function onOutside(e) {
        if (!input.parentNode) { document.removeEventListener('click', onOutside); return; }
        if (e.target !== input && e.target !== okBtn) { document.removeEventListener('click', onOutside); finish(true); }
    }
    setTimeout(function() { document.addEventListener('click', onOutside); }, 50);
    okBtn.addEventListener('click', function(e) { e.stopPropagation(); finish(true); });
}
currentTitle.addEventListener('click', startTitleEdit);
function newConversation(){state.currentConvId=null;$('#messages-container').innerHTML='';currentTitle.textContent='新对话';closeSidebar();loadConversations();updateWelcomeState()}
$('#new-chat-btn').addEventListener('click',newConversation);

batchBtn.addEventListener('click',function(){state.batchMode?exitBatchMode():enterBatchMode()});
function enterBatchMode(){state.batchMode=true;state.selectedConvs={};batchBtn.textContent='完成';batchBar.classList.remove('hidden');document.querySelectorAll('.conv-item').forEach(function(el){el.classList.add('batch-mode');el.classList.remove('selected')});updateBC()}
function exitBatchMode(){state.batchMode=false;state.selectedConvs={};batchBtn.textContent='批量';batchBar.classList.add('hidden');document.querySelectorAll('.conv-item').forEach(function(el){el.classList.remove('batch-mode','selected')})}
function toggleConvSelect(cid,el){if(state.selectedConvs[cid]){delete state.selectedConvs[cid];el.classList.remove('selected')}else{state.selectedConvs[cid]=true;el.classList.add('selected')}updateBC()}
function updateBC(){batchCount.textContent='已选 '+Object.keys(state.selectedConvs).length+' 项'}
$('#batch-delete-btn').addEventListener('click',function(){var ids=Object.keys(state.selectedConvs);if(!ids.length)return;showConfirm('删除 '+ids.length+' 个对话？',function(){var d=0;ids.forEach(function(id){fetch(state.serverUrl+'/api/conversations/'+id,{method:'DELETE',headers:apiH()}).then(function(){d++;if(d===ids.length){exitBatchMode();loadConversations();showToast('已删除')}}).catch(function(){d++})})})});
$('#batch-cancel-btn').addEventListener('click',exitBatchMode);

// ═══════════════════ Context Menu (long press) ═══════════════════
var ctxMenu = $('#ctx-menu'), ctxOverlay = $('#ctx-overlay');
function showCtxMenu() {
    var t = state.ctxTarget;
    if (!t || !t.el) return;
    var row = t.el.getBoundingClientRect();
    var sidebar = document.getElementById('sidebar');
    var sbRect = sidebar.getBoundingClientRect();

    // Measure menu size
    ctxMenu.classList.remove('hidden');
    ctxMenu.style.visibility = 'hidden';
    ctxMenu.classList.add('show');
    var mw = ctxMenu.offsetWidth || 110;
    var mh = ctxMenu.offsetHeight || 0;
    ctxMenu.classList.remove('show');
    ctxMenu.style.visibility = '';

    // Position below row, right-aligned within sidebar
    var top = row.bottom + 4;
    var left = sbRect.right - mw - 8;

    // If menu goes below viewport, flip above row
    if (top + mh > window.innerHeight - 8) {
        top = row.top - mh - 4;
    }
    // Clamp top
    if (top < sbRect.top + 4) top = sbRect.top + 4;

    // Clamp left within sidebar
    if (left < sbRect.left + 4) left = sbRect.left + 4;
    if (left + mw > sbRect.right - 4) left = sbRect.right - mw - 4;

    ctxMenu.style.top = top + 'px';
    ctxMenu.style.left = left + 'px';

    ctxOverlay.classList.remove('hidden');
    ctxMenu.classList.remove('hidden');
    requestAnimationFrame(function() { ctxMenu.classList.add('show'); });
}
function hideCtxMenu() {
    ctxMenu.classList.remove('show');
    setTimeout(function() {
        ctxMenu.classList.add('hidden');
        ctxOverlay.classList.add('hidden');
        state.ctxTarget = null;
    }, 150);
}
ctxOverlay.addEventListener('click', hideCtxMenu);
$('#ctx-rename').addEventListener('click', function() {
    if (!state.ctxTarget) return;
    var t = state.ctxTarget;
    hideCtxMenu();
    showRenamePrompt(t.id, t.title);
});
$('#ctx-delete').addEventListener('click', function() {
    if (!state.ctxTarget) return;
    var t = state.ctxTarget;
    hideCtxMenu();
    showConfirm('确认删除该对话？<br><span class="confirm-subtitle">"' + escHtml(t.title) + '"</span>', function() {
        fetch(state.serverUrl+'/api/conversations/'+t.id, {method:'DELETE', headers:apiH()}).then(function() {
            if (state.currentConvId === t.id) { state.currentConvId = null; $('#messages-container').innerHTML = ''; updateWelcomeState(); }
            loadConversations(); showToast('已删除');
        }).catch(function() { showToast('删除失败', 'error'); });
    }, '删除');
});
$('#ctx-pin').addEventListener('click', function() {
    if (!state.ctxTarget) return;
    var t = state.ctxTarget;
    hideCtxMenu();
    apiPost('/api/conversations/' + t.id + '/pin', {}).then(function() {
        loadConversations(); showToast('已置顶');
    }).catch(function() { showToast('置顶失败', 'error'); });
});
function showRenamePrompt(cid, oldTitle) {
    var newTitle = prompt('重命名对话:', oldTitle);
    if (newTitle && newTitle.trim() && newTitle.trim() !== oldTitle) {
        renameConversation(cid, newTitle.trim());
    }
}

// ═══════════════════ Sidebar Search ═══════════════════
var convSearch = $('#conv-search');
convSearch.addEventListener('input', function() {
    var q = convSearch.value.toLowerCase().trim();
    var items = convList.querySelectorAll('.conv-item');
    for (var i = 0; i < items.length; i++) {
        var title = (items[i].querySelector('.conv-title')||{}).textContent||'';
        items[i].style.display = (!q || title.toLowerCase().indexOf(q) !== -1) ? '' : 'none';
    }
});

// ═══════════════════ Sidebar Swipe-to-close ═══════════════════
var swipeStartX = 0, swipeActive = false;
sidebar.addEventListener('touchstart', function(e) {
    if (e.target.closest('.conv-item') || e.target.closest('button') || e.target.closest('input')) return;
    swipeStartX = e.touches[0].clientX;
    swipeActive = true;
}, {passive: true});
sidebar.addEventListener('touchmove', function(e) {
    if (!swipeActive) return;
    var dx = e.touches[0].clientX - swipeStartX;
    if (dx > 0) { sidebar.style.transform = 'translateX(' + Math.min(dx, 120) + 'px)'; }
}, {passive: true});
sidebar.addEventListener('touchend', function(e) {
    if (!swipeActive) { swipeActive = false; return; }
    swipeActive = false;
    var dx = e.changedTouches[0].clientX - swipeStartX;
    sidebar.style.transform = '';
    if (dx > 80) closeSidebar();
});

// ═══════════════════ Settings Panel ═══════════════════
var settingsPanel=$('#settings-panel'),settingsOverlay=$('#settings-overlay');
function openSettings(){$('#set-server-url').value=state.serverUrl;$('#set-secret').value=state.secret;settingsPanel.classList.remove('hidden');settingsOverlay.classList.remove('hidden');loadSysInfo();loadConfig()}
function closeSettings(){settingsPanel.classList.add('hidden');settingsOverlay.classList.add('hidden')}
$('#settings-btn').addEventListener('click',openSettings);$('#settings-close-btn').addEventListener('click',closeSettings);settingsOverlay.addEventListener('click',closeSettings);
$('#save-conn-btn').addEventListener('click',function(){var u=$('#set-server-url').value.trim(),s=$('#set-secret').value.trim();if(!u||!s){showToast('请填写完整','error');return}state.serverUrl=u;state.secret=s;localStorage.setItem('cg_server_url',u);localStorage.setItem('cg_secret',s);closeSettings();chatScreen.classList.remove('active');settingsScreen.classList.add('active');secretInput.value=s;doConnect()});
var THEMES={black:{bg:'#0a0a0a',surface:'#121212',accent:'#4a9eff'},dark:{bg:'#1a1a1a',surface:'#222222',accent:'#4ec9b0'},gray:{bg:'#1e1e24',surface:'#282830',accent:'#569cd6'},blue:{bg:'#0d1117',surface:'#161b22',accent:'#58a6ff'}};
function applyTheme(n){var t=THEMES[n]||THEMES.black,r=document.documentElement.style;r.setProperty('--bg-primary',t.bg);r.setProperty('--bg-surface',t.surface);r.setProperty('--accent-hover',t.accent+'cc');r.setProperty('--accent-dim',t.accent+'22');localStorage.setItem('cg_theme',n);document.querySelectorAll('.preset-btn').forEach(function(b){b.classList.toggle('active',b.dataset.theme===n)});$('#set-accent').value=t.accent;setAccent(t.accent,true)}
document.querySelectorAll('.preset-btn').forEach(function(b){b.addEventListener('click',function(){applyTheme(this.dataset.theme)})});
function setAccent(c,skipSave){var r=document.documentElement.style;r.setProperty('--accent',c);r.setProperty('--accent-hover',c+'cc');r.setProperty('--accent-dim',c+'22');if(!skipSave)localStorage.setItem('cg_accent',c)}
$('#set-accent').addEventListener('input',function(){setAccent(this.value)});
$('#set-font-size').addEventListener('input',function(){var s=parseInt(this.value);document.documentElement.style.fontSize=s+'px';localStorage.setItem('cg_font_size',s);var label=s<=16?'小':s<=19?'中':'大';$('#font-label').textContent=label+' ('+s+'px)'});
(function(){var t=localStorage.getItem('cg_theme')||'black';var a=localStorage.getItem('cg_accent');applyTheme(t);if(a){setAccent(a,true);$('#set-accent').value=a}var f=localStorage.getItem('cg_font_size')||'17';document.documentElement.style.fontSize=f+'px';$('#set-font-size').value=f})();
function loadSysInfo(){fetch(state.serverUrl+'/api/system/info',{headers:apiH()}).then(function(r){return r.json()}).then(function(d){var info='端口: '+d.port+'<br>运行: '+d.uptime+'<br>对话: '+d.db.conversations+' · 消息: '+d.db.messages;if(d.deepseek_balance){info+='<br>DeepSeek余额: '+d.deepseek_balance.balance+' '+d.deepseek_balance.currency}$('#sys-info').innerHTML=info;$('#file-info').innerHTML='文件: '+d.files.count+' 个 · '+d.files.size_mb+' MB<br>目录: '+d.files.dir}).catch(function(){})}
function loadConfig(){fetch(state.serverUrl+'/api/system/config',{headers:apiH()}).then(function(r){return r.json()}).then(function(d){$('#set-timeout').value=String(d.session_timeout_minutes!=null?d.session_timeout_minutes:0);$('#set-mirror').value=d.console_mirror?'1':'0';$('#set-file-dir').value=d.file_root_dir||'';$('#set-max-fsize').value=d.max_file_size_mb!=null?d.max_file_size_mb:20;$('#set-idle-timeout').value=String(d.session_idle_timeout_minutes!=null?d.session_idle_timeout_minutes:5)}).catch(function(){})}
$('#set-timeout').addEventListener('change',function(){var v=parseInt(this.value);fetch(state.serverUrl+'/api/system/config',{method:'POST',headers:apiH(),body:JSON.stringify({session_timeout_minutes:v})}).then(function(){showToast('已设 '+(v===0?'永不':v+'分钟')+' (重启后生效)')}).catch(function(){})});
$('#set-mirror').addEventListener('change',function(){var on=this.value==='1';fetch(state.serverUrl+'/api/system/config',{method:'POST',headers:apiH(),body:JSON.stringify({console_mirror:on})}).then(function(){showToast('终端镜像: '+(on?'开':'关'))}).catch(function(){})});
$('#set-idle-timeout').addEventListener('change',function(){var v=parseInt(this.value);fetch(state.serverUrl+'/api/system/config',{method:'POST',headers:apiH(),body:JSON.stringify({session_idle_timeout_minutes:v})}).then(function(){showToast('闲置回收: '+(v===0?'永不':v+'分钟'))}).catch(function(){})});
$('#set-file-dir').addEventListener('change',function(){var v=this.value.trim();if(!v)return;fetch(state.serverUrl+'/api/system/config',{method:'POST',headers:apiH(),body:JSON.stringify({file_root_dir:v})}).then(function(){showToast('存储路径已更新 (重启后生效)')}).catch(function(){})});
$('#set-max-fsize').addEventListener('change',function(){var v=parseInt(this.value);if(!v||v<1||v>500)return;fetch(state.serverUrl+'/api/system/config',{method:'POST',headers:apiH(),body:JSON.stringify({max_file_size_mb:v})}).then(function(){showToast('上传大小上限: '+v+' MB')}).catch(function(){})});

// System event polling (session killed notifications etc)
(function(){
    var _since = 0;
    function pollEvents() {
        fetch(state.serverUrl+'/api/system/events?since='+_since,{headers:apiH()})
        .then(function(r){return r.json()})
        .then(function(d){_since=d.next_since;(d.events||[]).forEach(function(e){showToast(e.message,'info')})})
        .catch(function(){});
    }
    setInterval(pollEvents, 30000);
})();
$('#sys-clear-logs').addEventListener('click',function(){showConfirm('清除服务器日志？',function(){fetch(state.serverUrl+'/api/system/clear-logs',{method:'POST',headers:apiH()}).then(function(r){return r.json()}).then(function(){showToast('日志已清除')}).catch(function(){})})});
$('#sys-clear-convs').addEventListener('click',function(){showConfirm('删除所有对话？不可撤销。',function(){fetch(state.serverUrl+'/api/system/clear-conversations',{method:'POST',headers:apiH()}).then(function(){state.currentConvId=null;$('#messages-container').innerHTML='';loadConversations();showToast('已清空')}).catch(function(){})})});
$('#sys-clean-cache').addEventListener('click',function(){showConfirm('清理 Python 缓存？',function(){fetch(state.serverUrl+'/api/system/clean-cache',{method:'POST',headers:apiH()}).then(function(r){return r.json()}).then(function(d){showToast(d.message)}).catch(function(){})})});
$('#sys-view-logs').addEventListener('click',function(){var v=$('#sys-log-viewer');if(!v.classList.contains('hidden')){v.classList.add('hidden');return}fetch(state.serverUrl+'/api/system/logs?lines=30',{headers:apiH()}).then(function(r){return r.json()}).then(function(d){v.textContent=d.logs.join('\n');v.classList.remove('hidden')}).catch(function(){})});
$('#sys-restart').addEventListener('click',function(){showConfirm('强制重启服务器？会杀死所有进程。',function(){showToast('重启中...');fetch(state.serverUrl+'/api/system/restart',{method:'POST',headers:apiH()}).then(function(){var n=3;var t=setInterval(function(){showToast('重启中... '+n+'s');n--;if(n<0){clearInterval(t);window.location.reload()}},1000)}).catch(function(){showToast('重启失败','error')})})});
$('#sys-soft-restart').addEventListener('click',function(){showConfirm('平滑重启？不强制杀进程，关闭更干净。',function(){showToast('平滑重启中... 稍等');fetch(state.serverUrl+'/api/system/soft-restart',{method:'POST',headers:apiH()}).then(function(){var n=8;var t=setInterval(function(){showToast('重启中... '+n+'s');n--;if(n<0){clearInterval(t);window.location.reload()}},1000)}).catch(function(){showToast('重启失败','error')})})});

// ═══════════════════ Confirm / Toast / Utils ═══════════════════
function showConfirm(m,cb,okText){state.confirmCallback=cb;$('#confirm-msg').innerHTML=m;$('#confirm-ok').textContent=okText||'确定';$('#confirm-overlay').classList.remove('hidden')}
function hideConfirm(){$('#confirm-overlay').classList.add('hidden');state.confirmCallback=null}
$('#confirm-cancel').addEventListener('click',hideConfirm);
$('#confirm-ok').addEventListener('click',function(){var cb=state.confirmCallback;hideConfirm();if(cb)cb()});
$('#confirm-overlay').addEventListener('click',function(e){if(e.target===this)hideConfirm()});
var tt;function showToast(m,t){var el=$('#toast');el.textContent=m;el.className='toast '+(t||'');clearTimeout(tt);tt=setTimeout(function(){el.classList.add('hidden')},2500)}
function escHtml(t){var d=document.createElement('div');d.textContent=t;return d.innerHTML}
function renderMarkdown(text) {
    if(!text)return'';var h=escHtml(text);
    // [DOWNLOAD:filename] → download card (always, any file type)
    h=h.replace(/\[DOWNLOAD:([^\]]+)\]/g,function(_,name){
        var url=state.serverUrl+'/api/files/download/'+encodeURIComponent(name)+'?token='+encodeURIComponent(state.secret);
        return '<a class="download-card" href="'+url+'" download="'+escHtml(name)+'"><span class="file-icon">&#128196;</span><span class="file-name">'+escHtml(name)+'</span><span class="file-action">&#8595; 下载</span></a>';
    });
    // [FILE:filename] → smart: images inline thumbnail, others download card
    h=h.replace(/\[FILE:([^\]]+)\]/g,function(_,name){
        var isImg = /\.(png|jpe?g|gif|webp|bmp)$/i.test(name);
        if (isImg) {
            var vurl = state.serverUrl + '/api/files/view/' + encodeURIComponent(name) + '?token=' + encodeURIComponent(state.secret);
            var durl = state.serverUrl + '/api/files/download/' + encodeURIComponent(name) + '?token=' + encodeURIComponent(state.secret);
            return '<img class="chat-image" src="'+vurl+'" alt="'+escHtml(name)+'" loading="lazy" onclick="viewImageFullscreen(this.src)" onerror="this.outerHTML=\'<a class=download-card href='+"'"+durl+"'"+'>📄 '+escHtml(name)+' ⬇ 下载</a>\'">';
        }
        var durl = state.serverUrl + '/api/files/download/' + encodeURIComponent(name) + '?token=' + encodeURIComponent(state.secret);
        return '<a class="download-card" href="'+durl+'" download="'+escHtml(name)+'"><span class="file-icon">&#128196;</span><span class="file-name">'+escHtml(name)+'</span><span class="file-action">&#8595; 下载</span></a>';
    });
    h=h.replace(/```(\w*)\n?([\s\S]*?)```/g,function(_,lang,code){return'<pre><code>'+code.trim()+'</code></pre>'});
    h=h.replace(/((?:^\|.+\|$\n?)+)/gm,function(m){var l=m.trim().split('\n');if(l.length<2)return m;var sep=/^\|[\s\-:|]+\|$/;if(!l.some(function(x){return sep.test(x)}))return m;var r=[];for(var i=0;i<l.length;i++){if(sep.test(l[i]))continue;var cells=l[i].split('|').slice(1,-1);var tag='td';if(r.length===0)tag='th';r.push('<tr>'+cells.map(function(x){return'<'+tag+'>'+x.trim()+'</'+tag+'>'}).join('')+'</tr>')}return r.length?'<table>'+r.join('')+'</table>':m});
    h=h.replace(/`([^`]+)`/g,'<code>$1</code>');h=h.replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>');
    h=h.replace(/^### (.+)$/gm,'<h4>$1</h4>');h=h.replace(/^## (.+)$/gm,'<h3>$1</h3>');h=h.replace(/^# (.+)$/gm,'<h2>$1</h2>');
    h=h.replace(/^[*-] (.+)$/gm,'<li>$1</li>');h=h.replace(/((?:<li>.*<\/li>\n?)+)/g,'<ul>$1</ul>');
    h=h.replace(/\n\n/g,'</p><p>');h=h.replace(/\n/g,'<br>');h='<p>'+h+'</p>';h=h.replace(/<p>\s*<\/p>/g,'');
    return h;
}

/**
 * ── Image Fullscreen Overlay ──
 * Tapping an inline chat thumbnail opens the image in a full-screen dark overlay.
 * Tapping anywhere on the overlay closes it.
 */
function viewImageFullscreen(src) {
    var overlay = document.createElement('div');
    overlay.className = 'image-overlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-label', '图片全屏');

    var img = document.createElement('img');
    img.className = 'image-full';
    img.src = src;
    overlay.appendChild(img);

    // Close on tap — anywhere on the dark background
    overlay.addEventListener('click', function dismissOverlay() {
        overlay.remove();
    });

    document.body.appendChild(overlay);
}

// ═══════════════════ Custom Scrollbar + Scroll-to-Bottom ═══════════════════
(function() {

// ── A: Custom scrollbar — CSS-only, native scroll handles everything ──
function initCustomScroll() {
    // Desktop uses -webkit-scrollbar CSS
    // Mobile uses native overlay scrollbar
    // No JS thumb — avoids interfering with native scroll
}

// ── B: Scroll-to-bottom button ──
function initScrollBottom(container) {
    if (container.dataset.sbInit) return;
    container.dataset.sbInit = '1';

    var btn = document.createElement('button');
    btn.className = 'scroll-bottom-btn';
    btn.textContent = '↓';
    btn.title = '回到底部';
    document.body.appendChild(btn);

    container.addEventListener('scroll', function() {
        var dist = container.scrollHeight - container.scrollTop - container.clientHeight;
        btn.classList.toggle('show', dist > 200);
    });

    btn.addEventListener('click', function() {
        container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
    });
}

// ── Auto-init on messages container ──
function initScrollFeatures() {
    var mc = msgsContainer;
    if (!mc) return;
    initCustomScroll(mc);
    initScrollBottom(mc);
}
// Init after DOM ready + after first connection
setTimeout(initScrollFeatures, 1000);
var _origShowChat = showChatScreen;
showChatScreen = function() {
    _origShowChat();
    setTimeout(initScrollFeatures, 500);
};

})();

// ═══════════════════ Auto-login ═══════════════════
// Must run LAST — after all variables and event listeners are set up
if (state.secret) { setTimeout(function() { showChatScreen(); }, 0); }
