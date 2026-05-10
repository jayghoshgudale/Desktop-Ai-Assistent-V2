/**
 * J.A.R.V.I.S. V2 - Frontend Logic
 * Refactored & Modularized for Production
 */

// ─────────────────────────────────────────────────────────────────
// CONFIG & STATE
// ─────────────────────────────────────────────────────────────────

const API = (typeof window !== 'undefined' && window.location.hostname.includes('github.io'))
    ? 'http://localhost:8000'
    : ((typeof window !== 'undefined' && window.location.origin) ? window.location.origin : 'http://localhost:8000');

const State = {
    sessionId: null,
    currentMode: 'jarvis',
    isStreaming: false,
    isListening: false,
    camStream: null,
    autoListenMode: false,
    speechErrorRetryCount: 0,
    speechSendTimeout: null,
    pendingSendTranscript: null,
    safariVoiceHintShown: false,
    clipboardEnabled: true,
    settings: {
        autoOpenActivity: true,
        autoOpenSearchResults: true,
        thinkingSounds: true,
        voiceInterrupt: true,
        wakeWordEnabled: false,
        clipboardEnabled: true
    }
};

const CONSTANTS = {
    SPEECH_ERROR_MAX_RETRIES: 3,
    SPEECH_SEND_DELAY_MS: 500,
    SPEECH_RESTART_DELAY_MS: 700,
    SETTINGS_KEY: 'jarvis_settings',
    CAM_BYPASS_TOKEN: 'TTCAMTOKENTT',
    PRE_STARTER_FILES: ['starter_1', 'starter_2', 'starter_3', 'starter_4', 'starter_5', 'starter_6', 'starter_7', 'starter_8', 'starter_9', 'starter_10']
};

let orb = null;
let recognition = null;
let ttsPlayer = null;
let wakeWordWS = null;
let preStarterPlayer = null;
const PRE_STARTER_CACHE = {};

// ─────────────────────────────────────────────────────────────────
// DOM ELEMENTS
// ─────────────────────────────────────────────────────────────────

const $ = id => document.getElementById(id);
const Elements = {
    chatMessages: $('chat-messages'),
    messageInput: $('message-input'),
    sendBtn: $('send-btn'),
    micBtn: $('mic-btn'),
    ttsBtn: $('tts-btn'),
    newChatBtn: $('new-chat-btn'),
    charCount: $('char-count'),
    welcomeTitle: $('welcome-title'),
    modeSlider: $('mode-slider'),
    btnJarvis: $('btn-jarvis'),
    statusDot: document.querySelector('.status-dot'),
    statusText: document.querySelector('.status-text'),
    orbContainer: $('orb-container'),
    searchResults: {
        toggle: $('search-results-toggle'),
        widget: $('search-results-widget'),
        close: $('search-results-close'),
        query: $('search-results-query'),
        answer: $('search-results-answer'),
        list: $('search-results-list')
    },
    activity: {
        panel: $('activity-panel'),
        toggle: $('activity-toggle'),
        close: $('activity-close'),
        list: $('activity-list')
    },
    panelOverlay: $('panel-overlay'),
    speechWidget: {
        container: $('speech-widget'),
        text: $('speech-widget-text')
    },
    settings: {
        btn: $('settings-btn'),
        panel: $('settings-panel'),
        close: $('settings-close'),
        toggleAutoActivity: $('toggle-auto-activity'),
        toggleAutoSearch: $('toggle-auto-search'),
        toggleThinkingSounds: $('toggle-thinking-sounds'),
        toggleVoiceInterrupt: $('toggle-voice-interrupt'),
        toggleWakeWord: $('toggle-wake-word'),
        toggleClipboard: $('toggle-clipboard')
    },
    camera: {
        btn: $('cam-btn'),
        panel: $('cam-panel'),
        video: $('cam-video'),
        canvas: $('cam-canvas'),
        visionMode: $('cam-vision-mode'),
        minimize: $('cam-minimize'),
        close: $('cam-close'),
        header: $('cam-panel-header'),
        resize: $('cam-panel-resize')
    },
    toastContainer: $('toast-container'),
    screen: {
        btn: $('screen-btn'),
        previewPanel: $('screen-preview-panel'),
        previewImg: $('screen-preview-img'),
        previewClose: $('screen-preview-close')
    },
    clipBtn: $('clip-btn'),
    wakeBadge: $('wake-badge')
};

// ─────────────────────────────────────────────────────────────────
// UTILS & UI HELPERS
// ─────────────────────────────────────────────────────────────────

const UI = {
    showToast(msg, durationMs = 5000) {
        if (!Elements.toastContainer || !msg) return;
        const el = document.createElement('div');
        el.className = 'toast';
        el.textContent = msg;
        Elements.toastContainer.appendChild(el);
        el.offsetHeight; // force reflow
        el.classList.add('toast-visible');
        const t = setTimeout(() => {
            el.classList.remove('toast-visible');
            setTimeout(() => el.remove(), 300);
        }, durationMs);
        el.addEventListener('click', () => {
            clearTimeout(t);
            el.classList.remove('toast-visible');
            setTimeout(() => el.remove(), 300);
        });
    },

    scrollToBottom() {
        requestAnimationFrame(() => {
            if (Elements.chatMessages) {
                Elements.chatMessages.scrollTop = Elements.chatMessages.scrollHeight;
            }
        });
    },

    escapeHtml(str) {
        if (typeof str !== 'string') return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    },

    autoResizeInput() {
        if (!Elements.messageInput) return;
        Elements.messageInput.style.height = 'auto';
        Elements.messageInput.style.height = Math.min(Elements.messageInput.scrollHeight, 120) + 'px';
    },

    updatePanelOverlay() {
        if (!Elements.panelOverlay) return;
        const anyOpen = (Elements.activity.panel?.classList.contains('open')) ||
            (Elements.searchResults.widget?.classList.contains('open')) ||
            (Elements.settings.panel?.classList.contains('open'));
        Elements.panelOverlay.classList.toggle('visible', !!anyOpen);
    },

    setGreeting() {
        const h = new Date().getHours();
        let g = 'Good evening.';
        if (h < 12) g = 'Good morning.';
        else if (h < 17) g = 'Good afternoon.';
        else if (h >= 22) g = 'Burning the midnight oil?';
        if (Elements.welcomeTitle) Elements.welcomeTitle.textContent = g;
    },

    hideWelcome() {
        const w = document.getElementById('welcome-screen');
        if (w) w.remove();
    }
};

// ─────────────────────────────────────────────────────────────────
// CORE SERVICES (TTS, Orb, Pre-Starter)
// ─────────────────────────────────────────────────────────────────

class PreStarterPlayer {
    constructor() {
        this.audio = document.createElement('audio');
        this.audio.preload = 'auto';
    }
    play(onComplete) {
        const loaded = CONSTANTS.PRE_STARTER_FILES.filter(f => PRE_STARTER_CACHE[f]);
        if (loaded.length === 0) { if (onComplete) onComplete(); return; }
        const file = loaded[Math.floor(Math.random() * loaded.length)];
        const base64 = PRE_STARTER_CACHE[file];
        if (!base64) { if (onComplete) onComplete(); return; }
        this.audio.src = 'data:audio/mp3;base64,' + base64;
        this.audio.currentTime = 0;
        let fired = false;
        const done = () => { if (fired) return; fired = true; this.audio.onended = null; this.audio.onerror = null; if (onComplete) onComplete(); };
        this.audio.onended = done;
        this.audio.onerror = done;
        const p = this.audio.play();
        if (p) p.catch(done);
    }
}

class TTSPlayer {
    constructor() {
        this.queue = [];
        this.playing = false;
        this.enabled = true;
        this.stopped = false;
        this.audio = document.createElement('audio');
        this.audio.preload = 'auto';
    }
    unlock() {
        const silentWav = 'data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAAABkYXRhAgAAAAEA';
        this.audio.src = silentWav;
        const p = this.audio.play();
        if (p) p.catch(() => { });
        try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const g = ctx.createGain(); g.gain.value = 0;
            const o = ctx.createOscillator(); o.connect(g); g.connect(ctx.destination);
            o.start(0); o.stop(ctx.currentTime + 0.001);
            setTimeout(() => ctx.close(), 200);
        } catch (_) { }
    }
    enqueue(base64Audio) {
        if (!this.enabled || this.stopped) return;
        this.queue.push(base64Audio);
        if (!this.playing) this._playLoop();
    }
    stop() {
        this.stopped = true;
        this.audio.pause();
        this.audio.removeAttribute('src');
        this.audio.load();
        this.queue = [];
        this.playing = false;
        if (Elements.ttsBtn) Elements.ttsBtn.classList.remove('tts-speaking');
        if (Elements.orbContainer) Elements.orbContainer.classList.remove('speaking');
        if (orb) orb.setActive(false);
        if (typeof this.onPlaybackComplete === 'function') this.onPlaybackComplete();
    }
    reset() {
        this.stop();
        this.stopped = false;
        this._loopId = (this._loopId || 0) + 1;
    }
    async _playLoop() {
        if (this.playing) return;
        this.playing = true;
        this._loopId = (this._loopId || 0) + 1;
        const myId = this._loopId;
        if (Elements.ttsBtn) Elements.ttsBtn.classList.add('tts-speaking');
        if (Elements.orbContainer) Elements.orbContainer.classList.add('speaking');
        if (orb) orb.setActive(true);
        while (this.queue.length > 0) {
            if (this.stopped || myId !== this._loopId) break;
            const b64 = this.queue.shift();
            try { await this._playB64(b64); } catch (e) { console.warn('TTS segment error:', e); }
        }
        if (myId !== this._loopId) { this.playing = false; return; }
        this.playing = false;
        if (Elements.ttsBtn) Elements.ttsBtn.classList.remove('tts-speaking');
        if (Elements.orbContainer) Elements.orbContainer.classList.remove('speaking');
        if (orb) orb.setActive(false);
        if (typeof this.onPlaybackComplete === 'function') this.onPlaybackComplete();
    }
    _playB64(b64) {
        return new Promise(resolve => {
            this.audio.src = 'data:audio/mp3;base64,' + b64;
            const done = () => resolve();
            this.audio.onended = done;
            this.audio.onerror = done;
            const p = this.audio.play();
            if (p) p.catch(done);
        });
    }
}

// ─────────────────────────────────────────────────────────────────
// CHAT & MESSAGING
// ─────────────────────────────────────────────────────────────────

const Chat = {
    AVATAR_USER: '<svg class="msg-avatar-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
    AVATAR_ASSISTANT: '<svg class="msg-avatar-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4"/><circle cx="9" cy="16" r="1" fill="currentColor"/><circle cx="15" cy="16" r="1" fill="currentColor"/></svg>',

    addMessage(role, text) {
        UI.hideWelcome();
        const msg = document.createElement('div');
        msg.className = `message ${role}`;
        const avatar = document.createElement('div');
        avatar.className = 'msg-avatar';
        avatar.innerHTML = role === 'assistant' ? this.AVATAR_ASSISTANT : this.AVATAR_USER;
        const body = document.createElement('div');
        body.className = 'msg-body';
        const labelText = role === 'assistant' ? `Jarvis (${State.currentMode === 'jarvis' ? 'Jarvis' : State.currentMode === 'realtime' ? 'Realtime' : 'General'})` : 'You';
        const label = document.createElement('div');
        label.className = 'msg-label';
        label.textContent = labelText;
        const content = document.createElement('div');
        content.className = 'msg-content';
        content.textContent = text;
        body.appendChild(label);
        body.appendChild(content);
        msg.appendChild(avatar);
        msg.appendChild(body);
        Elements.chatMessages.appendChild(msg);
        UI.scrollToBottom();
        return content;
    },

    addTypingIndicator() {
        UI.hideWelcome();
        const msg = document.createElement('div');
        msg.className = 'message assistant';
        msg.id = 'typing-msg';
        const avatar = document.createElement('div');
        avatar.className = 'msg-avatar';
        avatar.innerHTML = this.AVATAR_ASSISTANT;
        const body = document.createElement('div');
        body.className = 'msg-body';
        const label = document.createElement('div');
        label.className = 'msg-label';
        label.textContent = `Jarvis (${State.currentMode === 'jarvis' ? 'Jarvis' : State.currentMode === 'realtime' ? 'Realtime' : 'General'})`;
        const content = document.createElement('div');
        content.className = 'msg-content';
        content.innerHTML = '<span class="msg-stream-text">...</span>';
        body.appendChild(label);
        body.appendChild(content);
        msg.appendChild(avatar);
        msg.appendChild(body);
        Elements.chatMessages.appendChild(msg);
        UI.scrollToBottom();
        return content;
    },

    removeTypingIndicator() {
        const t = document.getElementById('typing-msg');
        if (t) t.remove();
    },

    async sendMessage(textOverride, imgBase64Override = null) {
        let text = (textOverride || Elements.messageInput.value).trim();
        const visionModeOn = Elements.camera.visionMode && Elements.camera.visionMode.checked;

        if (Camera.isScreenQuery(text) && !visionModeOn) {
            Elements.messageInput.value = '';
            UI.autoResizeInput();
            await Camera.captureScreen(text);
            return;
        }

        const wantsCamera = visionModeOn || Camera.isCameraQuery(text) || (State.camStream && text);
        if (wantsCamera && !text) text = 'What do you see?';
        if (!text && !imgBase64Override) return;
        if (State.isStreaming) return;

        if (State.isListening) {
            State.pendingSendTranscript = null;
            clearTimeout(State.speechSendTimeout);
            State.speechSendTimeout = null;
            Voice.stopListening();
        }

        if ((Camera.isCameraQuery(text) || visionModeOn) && !State.camStream && !imgBase64Override) {
            try {
                await Camera.start();
                await new Promise(resolve => {
                    if (!Elements.camera.video) { resolve(); return; }
                    if (Elements.camera.video.readyState >= 2 && Elements.camera.video.videoWidth > 0) { resolve(); return; }
                    const onReady = () => { Elements.camera.video.removeEventListener('loadeddata', onReady); clearTimeout(t); resolve(); };
                    const t = setTimeout(() => { Elements.camera.video.removeEventListener('loadeddata', onReady); resolve(); }, 3000);
                    Elements.camera.video.addEventListener('loadeddata', onReady);
                });
            } catch (_) { }
        }

        let imgBase64 = imgBase64Override;
        if (!imgBase64 && State.camStream && wantsCamera) {
            imgBase64 = await Camera.captureFrameAsBase64Safe();
            if (!imgBase64) UI.showToast('Camera frame not ready. Please try again.');
        }

        Elements.messageInput.value = '';
        UI.autoResizeInput();
        if (Elements.charCount) Elements.charCount.textContent = '';
        
        Chat.addMessage('user', text);
        Chat.addTypingIndicator();
        State.isStreaming = true;
        if (Elements.sendBtn) Elements.sendBtn.disabled = true;
        if (Elements.messageInput) Elements.messageInput.disabled = true;
        if (Elements.orbContainer) Elements.orbContainer.classList.add('active');
        if (ttsPlayer) { ttsPlayer.reset(); ttsPlayer.unlock(); }

        const messageToSend = imgBase64 ? (text + ' ' + CONSTANTS.CAM_BYPASS_TOKEN) : text;
        
        if (Elements.activity.list) {
            Elements.activity.list.innerHTML = '<div class="activity-empty" id="activity-empty">Processing…</div>';
            if (Elements.activity.toggle) Elements.activity.toggle.style.display = '';
            if (Elements.activity.panel && State.settings.autoOpenActivity) {
                Elements.activity.panel.classList.add('open');
                UI.updatePanelOverlay();
            }
        }

        let firstChunkReceived = false;
        let timeoutId = null;
        const controller = new AbortController();

        try {
            if (ttsPlayer?.enabled && State.settings.thinkingSounds && preStarterPlayer) {
                preStarterPlayer.play(() => { });
            }
            timeoutId = setTimeout(() => controller.abort(), 300000);
            
            const res = await fetch(`${API}/chat/jarvis/stream`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: messageToSend,
                    session_id: State.sessionId,
                    tts: !!(ttsPlayer && ttsPlayer.enabled),
                    imgbase64: imgBase64 || null
                }),
                signal: controller.signal,
            });

            if (!res.ok) {
                let errMsg = `HTTP ${res.status}`;
                try { const err = await res.json(); errMsg = err.detail || err.message || errMsg; } catch (_) { }
                throw new Error(errMsg);
            }

            Chat.removeTypingIndicator();
            const contentEl = Chat.addMessage('assistant', '');
            contentEl.innerHTML = '<span class="msg-stream-text">...</span>';
            UI.scrollToBottom();

            if (!res.body) throw new Error('No response body');
            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let sseBuffer = '';
            let fullResponse = '';
            let cursorEl = null;
            let streamDone = false;

            while (!streamDone) {
                const { done, value } = await reader.read();
                if (done) break;
                sseBuffer += decoder.decode(value, { stream: true });
                const lines = sseBuffer.split('\n\n');
                sseBuffer = lines.pop();
                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    try {
                        const data = JSON.parse(line.slice(6));
                        if (data.session_id) State.sessionId = data.session_id;
                        if (data.activity) {
                            Tasks.appendActivity(data.activity);
                        }
                        if (data.search_results) {
                            Tasks.renderSearchResults(data.search_results);
                        }
                        if (data.actions) Tasks.handleActions(data.actions, contentEl);
                        if (data.background_tasks) Tasks.handleBackgroundTasks(data.background_tasks, contentEl);
                        if (data.calendar_result) Tasks.renderCalendarCard(data.calendar_result, contentEl);
                        if (data.file_result) Tasks.renderFileCard(data.file_result, contentEl);
                        
                        if ('chunk' in data) {
                            const chunkText = data.chunk || '';
                            if (chunkText && !firstChunkReceived) {
                                firstChunkReceived = true;
                                if (ttsPlayer) ttsPlayer.reset();
                            }
                            fullResponse += chunkText;
                            const textSpan = contentEl.querySelector('.msg-stream-text');
                            if (textSpan) {
                                textSpan.textContent = fullResponse;
                                textSpan.classList.remove('stream-placeholder');
                            }
                            if (!cursorEl) {
                                cursorEl = document.createElement('span');
                                cursorEl.className = 'stream-cursor';
                                cursorEl.textContent = '|';
                                contentEl.appendChild(cursorEl);
                            }
                            UI.scrollToBottom();
                        }
                        if (data.audio && ttsPlayer) ttsPlayer.enqueue(data.audio);
                        if (data.error) throw new Error(data.error);
                        if (data.done) { streamDone = true; break; }
                    } catch (parseErr) {
                        if (parseErr.message && !parseErr.message.includes('JSON')) throw parseErr;
                    }
                }
                if (streamDone) break;
            }
            if (cursorEl) cursorEl.remove();
            const textSpan = contentEl.querySelector('.msg-stream-text');
            if (textSpan && !fullResponse) textSpan.textContent = '(No response)';
        } catch (err) {
            clearTimeout(timeoutId);
            Chat.removeTypingIndicator();
            let msg = 'Something went wrong. Please try again.';
            if (err.name === 'AbortError') msg = 'Request timed out.';
            else if (err.message && err.message.length > 0) msg = err.message.length > 200 ? err.message.slice(0, 197) + '...' : err.message;
            Chat.addMessage('assistant', msg);
            UI.showToast(msg, 6000);
        } finally {
            clearTimeout(timeoutId);
            State.isStreaming = false;
            if (Elements.sendBtn) Elements.sendBtn.disabled = false;
            if (Elements.messageInput) Elements.messageInput.disabled = false;
            if (Elements.orbContainer) Elements.orbContainer.classList.remove('active');
            Voice.maybeRestartListening();
        }
    },

    newChat() {
        if (ttsPlayer) ttsPlayer.stop();
        Camera.stop();
        State.sessionId = null;
        if (Elements.chatMessages) Elements.chatMessages.innerHTML = '';
        Elements.chatMessages.appendChild(Chat.createWelcome());
        Elements.messageInput.value = '';
        UI.autoResizeInput();
        UI.setGreeting();
        if (Elements.searchResults.widget) Elements.searchResults.widget.classList.remove('open');
        if (Elements.searchResults.toggle) Elements.searchResults.toggle.style.display = 'none';
        if (Elements.activity.panel) Elements.activity.panel.classList.remove('open');
        if (Elements.settings.panel) Elements.settings.panel.classList.remove('open');
        if (Elements.activity.toggle) Elements.activity.toggle.style.display = 'none';
        if (Elements.activity.list) Elements.activity.list.innerHTML = '<div class="activity-empty" id="activity-empty">Send a message to see the flow here.</div>';
        UI.updatePanelOverlay();
    },

    createWelcome() {
        const div = document.createElement('div');
        div.className = 'welcome-screen';
        div.id = 'welcome-screen';
        div.innerHTML = `
            <div class="welcome-icon">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
            </div>
            <h2 class="welcome-title">Loading...</h2>
            <p class="welcome-sub">How may I assist you today?</p>
            <div class="welcome-chips">
                <button class="chip" data-msg="What can you do?">What can you do?</button>
                <button class="chip" data-msg="Open YouTube for me">Open YouTube</button>
                <button class="chip" data-msg="Tell me a fun fact">Fun fact</button>
                <button class="chip" data-msg="Play some music">Play music</button>
                <button class="chip" data-msg="What's on my schedule today?">My schedule today</button>
                <button class="chip" data-msg="Look at my screen and tell me what you see">Analyze my screen</button>
            </div>`;
            
        div.querySelectorAll('.chip').forEach(c => {
            c.addEventListener('click', () => { if (!State.isStreaming) Chat.sendMessage(c.dataset.msg); });
        });
        return div;
    }
};

// ─────────────────────────────────────────────────────────────────
// VOICE & SPEECH
// ─────────────────────────────────────────────────────────────────

const Voice = {
    init() {
        const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SR) { if (Elements.micBtn) Elements.micBtn.title = 'Speech not supported'; return; }
        recognition = new SR();
        const safariMode = Voice.isSafariOrIOS();
        recognition.continuous = false;
        recognition.interimResults = !safariMode;
        recognition.maxAlternatives = 1;
        recognition.lang = 'en-US';

        recognition.onresult = e => {
            if (!e.results || e.results.length === 0) return;
            const last = e.results[e.results.length - 1];
            const transcript = (last && last[0]) ? last[0].transcript.trim() : '';
            const isFinal = last && last.isFinal;
            
            if (Elements.speechWidget.text) Elements.speechWidget.text.textContent = transcript;
            if (Elements.speechWidget.container) Elements.speechWidget.container.classList.add('visible');
            
            if (State.settings.voiceInterrupt && ttsPlayer && ttsPlayer.playing && transcript.length > 0) {
                ttsPlayer.stop();
                ttsPlayer.stopped = false;
            }
            
            if (isFinal && transcript) {
                State.pendingSendTranscript = transcript;
                clearTimeout(State.speechSendTimeout);
                State.speechSendTimeout = setTimeout(() => {
                    if (State.pendingSendTranscript) { Chat.sendMessage(State.pendingSendTranscript); State.pendingSendTranscript = null; }
                    State.speechSendTimeout = null;
                    Voice.stopListening();
                }, CONSTANTS.SPEECH_SEND_DELAY_MS);
            } else if (!isFinal) {
                State.pendingSendTranscript = null;
                clearTimeout(State.speechSendTimeout);
                State.speechSendTimeout = null;
            }
        };

        recognition.onstart = () => { State.speechErrorRetryCount = 0; };
        
        recognition.onerror = e => {
            Voice.stopListening();
            const msg = (e && e.error) ? String(e.error) : '';
            if (/denied|not-allowed|permission/i.test(msg) && Elements.micBtn) {
                Elements.micBtn.title = 'Mic access denied';
                State.speechErrorRetryCount = CONSTANTS.SPEECH_ERROR_MAX_RETRIES;
            }
            if (State.autoListenMode && !State.isStreaming && State.speechErrorRetryCount < CONSTANTS.SPEECH_ERROR_MAX_RETRIES) {
                State.speechErrorRetryCount++;
                setTimeout(() => Voice.maybeRestartListening(), CONSTANTS.SPEECH_RESTART_DELAY_MS);
            }
        };

        recognition.onend = () => {
            if (State.pendingSendTranscript) {
                clearTimeout(State.speechSendTimeout);
                State.speechSendTimeout = null;
                Chat.sendMessage(State.pendingSendTranscript);
                State.pendingSendTranscript = null;
            }
            if (State.isListening) Voice.stopListening();
            Voice.maybeRestartListening();
        };
    },

    startListening() {
        if (!recognition || State.isStreaming || State.isListening) return;
        if (Voice.isSafariOrIOS() && !State.safariVoiceHintShown) {
            UI.showToast('Voice works best in Chrome.');
            State.safariVoiceHintShown = true;
        }
        State.isListening = true;
        State.pendingSendTranscript = null;
        clearTimeout(State.speechSendTimeout);
        State.speechSendTimeout = null;
        
        if (Elements.micBtn) Elements.micBtn.classList.add('listening');
        if (Elements.speechWidget.container) Elements.speechWidget.container.classList.add('visible');
        
        try {
            recognition.start();
        } catch (err) {
            State.isListening = false;
            if (Elements.micBtn) Elements.micBtn.classList.remove('listening');
            if (Elements.speechWidget.container) Elements.speechWidget.container.classList.remove('visible');
        }
    },

    stopListening() {
        clearTimeout(State.speechSendTimeout);
        State.speechSendTimeout = null;
        State.pendingSendTranscript = null;
        State.isListening = false;
        if (Elements.micBtn) Elements.micBtn.classList.remove('listening');
        if (Elements.speechWidget.container) Elements.speechWidget.container.classList.remove('visible');
        try { recognition.stop(); } catch (_) { }
    },

    maybeRestartListening() {
        if (!State.autoListenMode || !recognition) return;
        if (State.isStreaming) return;
        const ttsActive = ttsPlayer && (ttsPlayer.playing || ttsPlayer.queue.length > 0);
        if (ttsActive && !State.settings.voiceInterrupt) return;
        const delay = ttsActive ? 150 : CONSTANTS.SPEECH_RESTART_DELAY_MS;
        setTimeout(() => { if (State.autoListenMode && !State.isStreaming && !State.isListening && recognition) Voice.startListening(); }, delay);
    },

    isSafariOrIOS() {
        if (typeof navigator === 'undefined') return false;
        const ua = navigator.userAgent || '';
        return /iPad|iPhone|iPod/.test(ua) || (navigator.vendor && navigator.vendor.indexOf('Apple') > -1) || (/Safari/.test(ua) && !/Chrome|Chromium|CriOS/.test(ua));
    },

    initWakeWordWS() {
        if (wakeWordWS && wakeWordWS.readyState === WebSocket.OPEN) return;
        const wsUrl = API.replace(/^http/, 'ws') + '/ws/wakeword';
        try {
            wakeWordWS = new WebSocket(wsUrl);
            wakeWordWS.onopen = () => { if (Elements.wakeBadge) Elements.wakeBadge.classList.add('active'); };
            wakeWordWS.onmessage = (ev) => {
                try {
                    const msg = JSON.parse(ev.data);
                    if (msg.event === 'wake_word_detected') Voice.onWakeWordHeard();
                    if (msg.event === 'wake_detected') Voice.onWakeDetected(msg.transcription || '', msg.response || '');
                } catch (_) { }
            };
            wakeWordWS.onclose = () => {
                if (Elements.wakeBadge) Elements.wakeBadge.classList.remove('active');
                if (State.settings.wakeWordEnabled) setTimeout(Voice.initWakeWordWS, 5000);
            };
        } catch (err) { console.warn('[JARVIS] Wake word WS init failed:', err); }
    },

    destroyWakeWordWS() {
        if (wakeWordWS) { wakeWordWS.onclose = null; wakeWordWS.close(); wakeWordWS = null; }
        if (Elements.wakeBadge) Elements.wakeBadge.classList.remove('active');
    },

    onWakeWordHeard() {
        if (Elements.wakeBadge) { Elements.wakeBadge.classList.add('triggered'); setTimeout(() => Elements.wakeBadge.classList.remove('triggered'), 1200); }
        UI.showToast('Listening...', 2000);
        if (Elements.orbContainer) Elements.orbContainer.classList.add('active');
        if (orb) orb.setActive(true);
    },

    onWakeDetected(transcription, response) {
        if (ttsPlayer) ttsPlayer.stop();
        if (Elements.orbContainer) Elements.orbContainer.classList.remove('active');
        if (orb) orb.setActive(false);

        if (transcription || response) {
            UI.hideWelcome();
            if (transcription) Chat.addMessage('user', transcription);
            if (response) {
                const contentEl = Chat.addMessage('assistant', response);
                if (contentEl) { contentEl.innerHTML = '<span class="msg-stream-text">' + UI.escapeHtml(response) + '</span>'; }
                UI.scrollToBottom();
            }
        }

        if (response && ttsPlayer && ttsPlayer.enabled) {
            ttsPlayer.reset(); ttsPlayer.unlock();
            fetch(API + '/tts', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: response }),
            })
            .then(r => r.blob())
            .then(blob => new Promise((resolve, reject) => {
                const reader = new FileReader();
                reader.onloadend = () => resolve((reader.result || '').split(',')[1] || '');
                reader.readAsDataURL(blob);
            }))
            .then(b64 => { if (b64) ttsPlayer.enqueue(b64); });
        }

        if (Elements.wakeBadge) { Elements.wakeBadge.classList.add('triggered'); setTimeout(() => Elements.wakeBadge.classList.remove('triggered'), 1200); }
    }
};

// ─────────────────────────────────────────────────────────────────
// CAMERA & SCREEN
// ─────────────────────────────────────────────────────────────────

const Camera = {
    SCREEN_QUERY_PATTERNS: [/look\s+at\s+my\s+screen/i, /what('s|s|\s+is)\s+on\s+my\s+screen/i, /analyze\s+my\s+screen/i, /read\s+(my|the)\s+screen/i, /what\s+do\s+you\s+see\s+on\s+my\s+screen/i, /screenshot/i, /capture\s+my\s+screen/i],
    CAMERA_QUERY_PATTERNS: [/what\s+(can|do)\s+you\s+see/i, /can\s+you\s+see/i, /describe\s+(what\s+you\s+see|this|the\s+image)/i, /what('s|s|\s+is)\s+in\s+(this\s+)?(picture|image)/i, /what\s+do\s+i\s+look\s+like/i, /what\s+(am\s+i\s+)?holding/i, /show\s+me\s+what\s+you\s+see/i],

    isScreenQuery(text) { return text && this.SCREEN_QUERY_PATTERNS.some(r => r.test(text.trim())); },
    isCameraQuery(text) {
        if (!text) return false;
        const t = text.trim().toLowerCase();
        return this.CAMERA_QUERY_PATTERNS.some(r => r.test(t)) || (t.includes('see') && (t.includes('what') || t.includes('describe')));
    },

    async start() {
        if (!navigator.mediaDevices?.getUserMedia) { UI.showToast('Camera not supported'); return Promise.reject(); }
        if (State.camStream) return Promise.resolve();
        return navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' }, audio: false })
            .then(stream => {
                State.camStream = stream;
                if (Elements.camera.video) Elements.camera.video.srcObject = stream;
                if (Elements.camera.panel) Elements.camera.panel.classList.add('visible');
                if (Elements.camera.btn) {
                    Elements.camera.btn.classList.add('cam-active');
                    const icon = Elements.camera.btn.querySelector('.cam-icon');
                    const iconActive = Elements.camera.btn.querySelector('.cam-icon-active');
                    if (icon) icon.style.display = 'none';
                    if (iconActive) iconActive.style.display = '';
                }
            })
            .catch(err => { UI.showToast('Camera access denied'); throw err; });
    },

    stop() {
        if (State.camStream) { State.camStream.getTracks().forEach(t => t.stop()); State.camStream = null; }
        if (Elements.camera.video) Elements.camera.video.srcObject = null;
        if (Elements.camera.panel) Elements.camera.panel.classList.remove('visible');
        if (Elements.camera.visionMode) Elements.camera.visionMode.checked = false;
        if (Elements.camera.btn) {
            Elements.camera.btn.classList.remove('cam-active');
            const icon = Elements.camera.btn.querySelector('.cam-icon');
            const iconActive = Elements.camera.btn.querySelector('.cam-icon-active');
            if (icon) icon.style.display = '';
            if (iconActive) iconActive.style.display = 'none';
        }
    },

    async captureScreen(promptOverride) {
        if (State.isStreaming) return;
        if (Elements.screen.btn) Elements.screen.btn.classList.add('screen-active');
        UI.showToast('Capturing screen…', 2000);

        try {
            const res = await fetch(`${API}/api/screen-capture`, { method: 'POST' });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            const imgBase64 = data.image;

            if (!imgBase64) throw new Error('No image returned');
            if (Elements.screen.previewPanel && Elements.screen.previewImg) {
                Elements.screen.previewImg.src = 'data:image/jpeg;base64,' + imgBase64;
                Elements.screen.previewPanel.classList.add('visible');
                setTimeout(() => Elements.screen.previewPanel.classList.remove('visible'), 4000);
            }

            const prompt = promptOverride || Elements.messageInput.value.trim() || 'Analyze my screen.';
            Chat.sendMessage(prompt, imgBase64);
        } catch (err) { UI.showToast('Screen capture failed'); }
        finally { if (Elements.screen.btn) Elements.screen.btn.classList.remove('screen-active'); }
    },

    async captureFrameAsBase64Safe() {
        if (!Elements.camera.video || !State.camStream || !Elements.camera.canvas) return null;
        return new Promise(resolve => {
            const doCapture = () => {
                const w = Elements.camera.video.videoWidth; const h = Elements.camera.video.videoHeight;
                if (!w || !h || w < 64 || h < 64) { resolve(null); return; }
                Elements.camera.canvas.width = w; Elements.camera.canvas.height = h;
                const ctx = Elements.camera.canvas.getContext('2d');
                if (!ctx) { resolve(null); return; }
                ctx.drawImage(Elements.camera.video, 0, 0, w, h);
                try { resolve(Elements.camera.canvas.toDataURL('image/jpeg', 0.9).split(',')[1]); } catch (_) { resolve(null); }
            };
            if (Elements.camera.video.readyState < 2) {
                const onReady = () => { Elements.camera.video.removeEventListener('loadeddata', onReady); doCapture(); };
                Elements.camera.video.addEventListener('loadeddata', onReady);
                setTimeout(() => { Elements.camera.video.removeEventListener('loadeddata', onReady); doCapture(); }, 3000);
                return;
            }
            if (typeof Elements.camera.video.requestVideoFrameCallback === 'function') Elements.camera.video.requestVideoFrameCallback(() => doCapture());
            else setTimeout(doCapture, 150);
        });
    }
};

// ─────────────────────────────────────────────────────────────────
// BACKGROUND TASKS & CARDS
// ─────────────────────────────────────────────────────────────────

const Tasks = {
    handleActions(actionsPayload, contentEl) {
        if (!actionsPayload || !contentEl) return;
        const actions = actionsPayload.actions || [];
        actions.forEach(act => {
            if (act.type === 'confirm') {
                const card = document.createElement('div');
                card.className = 'confirm-action-card';
                let html = '<div class="action-card-header">';
                
                if (act.data.type === 'system') {
                    html += '<strong>System Control</strong></div>';
                    html += `<div class="action-card-body">Are you sure you want to ${UI.escapeHtml(act.data.command)} the computer?</div>`;
                } else if (act.data.type === 'calendar') {
                    html += '<strong>📅 Calendar Event</strong></div>';
                    html += '<div class="action-card-body">';
                    html += `<div class="calendar-event-detail"><span class="cal-label">Title:</span> ${UI.escapeHtml(act.data.summary || '')}</div>`;
                    html += `<div class="calendar-event-detail"><span class="cal-label">When:</span> ${UI.escapeHtml(act.data.start || '')}</div>`;
                    if (act.data.description) html += `<div class="calendar-event-detail"><span class="cal-label">Note:</span> ${UI.escapeHtml(act.data.description)}</div>`;
                    html += '</div>';
                } else {
                    html += '<strong>Action Confirmation</strong></div>';
                    html += `<div class="action-card-body">Please confirm the ${UI.escapeHtml(act.data.type || 'action')}.</div>`;
                }

                html += '<div class="action-card-footer"><button class="btn-confirm-yes">Confirm</button> <button class="btn-confirm-no">Cancel</button></div>';
                card.innerHTML = html;
                card.querySelector('.btn-confirm-no').addEventListener('click', () => { card.innerHTML = '<em>Action Cancelled</em>'; });
                card.querySelector('.btn-confirm-yes').addEventListener('click', async () => {
                    card.innerHTML = '<em>Executing…</em>';
                    try {
                        const r = await fetch(API + '/api/execute-action', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ type: act.data.type, data: act.data }) });
                        const resData = await r.json();
                        if (!r.ok) throw new Error(resData.detail || 'Execution failed');
                        card.innerHTML = `<strong>✅ Success:</strong> ${UI.escapeHtml(resData.result)}`;
                    } catch (e) { card.innerHTML = `<strong style="color:var(--danger)">❌ Failed:</strong> ${UI.escapeHtml(e.message)}`; }
                });
                contentEl.appendChild(card);
                UI.scrollToBottom();
            }
        });

        const flat = actionsPayload;
        [flat.wopens, flat.plays, flat.googlesearches, flat.youtubesearches].forEach(arr => {
            (arr || []).forEach(url => { if (url && url.startsWith('http')) window.open(url, '_blank', 'noopener'); });
        });

        if (flat.images?.length) {
            const wrap = document.createElement('div'); wrap.className = 'msg-actions-images';
            flat.images.forEach(url => {
                const img = document.createElement('img'); img.src = url; img.className = 'msg-action-image'; img.onerror = () => img.remove();
                wrap.appendChild(img);
            });
            contentEl.appendChild(wrap);
        }
        
        if (flat.contents?.length) {
            const wrap = document.createElement('div'); wrap.className = 'msg-actions-contents';
            flat.contents.forEach(t => {
                const p = document.createElement('div'); p.className = 'msg-action-content'; p.textContent = t; wrap.appendChild(p);
            });
            contentEl.appendChild(wrap);
        }

        if (flat.cam) {
            if (flat.cam.action === 'open') Camera.start();
            else if (flat.cam.action === 'close') Camera.stop();
            else if (flat.cam.action === 'open_and_capture') {
                const resendMsg = flat.cam.resend_message || 'What do you see?';
                (async () => { await Camera.start(); await new Promise(r => setTimeout(r, 1000)); const frame = await Camera.captureFrameAsBase64Safe(); if (frame) Chat.sendMessage(resendMsg, frame); })();
            }
        }
    },

    handleBackgroundTasks(tasks, contentEl) {
        if (!tasks?.length || !contentEl) return;
        tasks.forEach(task => {
            const card = document.createElement('div');
            card.className = 'bg-task-card';
            card.dataset.taskId = task.task_id;
            const label = task.type === 'generate image' ? 'Image Generation' : task.type === 'content' ? 'Content Writing' : task.type === 'sandbox' ? '⚙️ Code Execution' : task.type === 'file' ? '📁 File Operation' : task.type;
            const promptText = task.label ? `"${task.label}"` : '';
            card.innerHTML = `<div class="bg-task-header"><div class="bg-task-spinner"></div><span class="bg-task-label">${label}</span><span class="bg-task-status">Working…</span></div>${promptText ? `<div class="bg-task-prompt">${promptText}</div>` : ''}`;
            contentEl.appendChild(card);
            UI.scrollToBottom();
            Tasks.pollBackgroundTask(task.task_id, card, task.type);
        });
    },

    pollBackgroundTask(taskId, cardEl, taskType) {
        let pollCount = 0;
        const interval = setInterval(() => {
            if (++pollCount > 120) { clearInterval(interval); Tasks.updateTaskCard(cardEl, 'failed', 'Timed out', taskType); return; }
            fetch(`${API}/tasks/${encodeURIComponent(taskId)}`)
                .then(r => r.json())
                .then(data => {
                    if (data.status === 'completed') { clearInterval(interval); Tasks.updateTaskCard(cardEl, 'completed', data, taskType); }
                    else if (data.status === 'failed') { clearInterval(interval); Tasks.updateTaskCard(cardEl, 'failed', data.error, taskType); }
                }).catch(() => { });
        }, 1500);
    },

    updateTaskCard(cardEl, status, data, taskType) {
        if (!cardEl) return;
        const spinner = cardEl.querySelector('.bg-task-spinner');
        const statusEl = cardEl.querySelector('.bg-task-status');
        if (status === 'completed') {
            if (spinner) spinner.className = 'bg-task-done-icon';
            if (statusEl) statusEl.textContent = 'Ready!';
            cardEl.classList.add('bg-task-done');
            if (taskType === 'sandbox' && data) {
                if (data.stdout) { const p = document.createElement('pre'); p.className = 'sandbox-output'; p.textContent = data.stdout; cardEl.appendChild(p); }
                if (data.stderr) { const p = document.createElement('pre'); p.className = 'sandbox-stderr'; p.textContent = data.stderr; cardEl.appendChild(p); }
            } else if (taskType === 'file' && data?.content) { Tasks.renderFileCard(data, cardEl); }
            else {
                const btn = document.createElement('button'); btn.className = 'bg-task-view-btn'; btn.textContent = 'Open result';
                btn.onclick = () => window.open(`${API}/app/viewer.html?task_id=${cardEl.dataset.taskId}`, '_blank');
                cardEl.appendChild(btn);
            }
        } else if (status === 'failed') {
            if (spinner) spinner.className = 'bg-task-fail-icon';
            if (statusEl) statusEl.textContent = data || 'Failed';
            cardEl.classList.add('bg-task-failed');
        }
        UI.scrollToBottom();
    },

    renderFileCard(payload, parentEl) {
        const wrapper = document.createElement('div');
        wrapper.className = 'file-result-card';
        wrapper.innerHTML = `<div class="file-result-header"><span class="file-result-name">📄 ${UI.escapeHtml(payload.filename)}</span></div>`;
        if (payload.content) {
            const body = document.createElement('div'); body.className = 'file-result-body';
            const pre = document.createElement('pre'); pre.className = 'file-result-text';
            pre.textContent = payload.content.length > 2000 ? payload.content.slice(0, 2000) + '\n\n…' : payload.content;
            body.appendChild(pre); wrapper.appendChild(body);
        }
        parentEl.appendChild(wrapper);
    },

    renderCalendarCard(payload, contentEl) {
        if (!payload || !contentEl) return;
        const card = document.createElement('div'); card.className = 'calendar-result-card';
        card.innerHTML = `<div class="calendar-result-title">📅 ${UI.escapeHtml(payload.title || 'Schedule')}</div>`;
        (payload.events || []).forEach(ev => {
            const row = document.createElement('div'); row.className = 'calendar-event-row';
            row.innerHTML = `<span class="cal-event-time">${UI.escapeHtml(ev.start || '')}</span><span class="cal-event-title">${UI.escapeHtml(ev.summary || 'Event')}</span>`;
            card.appendChild(row);
        });
        contentEl.appendChild(card);
        UI.scrollToBottom();
    },

    renderSearchResults(payload) {
        if (!payload || !Elements.searchResults.list) return;
        if (Elements.searchResults.query) Elements.searchResults.query.textContent = (payload.query || '').trim();
        if (Elements.searchResults.answer) Elements.searchResults.answer.textContent = (payload.answer || '').trim();
        Elements.searchResults.list.innerHTML = '';
        (payload.results || []).forEach(r => {
            const card = document.createElement('div'); card.className = 'search-result-card';
            card.innerHTML = `<div class="card-title">${UI.escapeHtml(r.title || 'Source')}</div><a href="${r.url}" target="_blank" class="card-url">${r.url}</a>`;
            Elements.searchResults.list.appendChild(card);
        });
        if (Elements.searchResults.toggle) Elements.searchResults.toggle.style.display = '';
        if (Elements.searchResults.widget && State.settings.autoOpenSearchResults) { Elements.searchResults.widget.classList.add('open'); UI.updatePanelOverlay(); }
    },

    appendActivity(activity) {
        if (!Elements.activity.list || !activity) return;
        const item = document.createElement('div');
        item.className = 'activity-item';
        item.innerHTML = `<div class="activity-event">${UI.escapeHtml(activity.event || 'Activity')}</div><div class="activity-detail">${UI.escapeHtml(activity.message || '')}</div>`;
        const empty = Elements.activity.list.querySelector('.activity-empty');
        if (empty) empty.style.display = 'none';
        Elements.activity.list.appendChild(item);
        Elements.activity.list.scrollTop = Elements.activity.list.scrollHeight;
        if (Elements.activity.toggle) Elements.activity.toggle.style.display = '';
        if (Elements.activity.panel && State.settings.autoOpenActivity) { Elements.activity.panel.classList.add('open'); UI.updatePanelOverlay(); }
    }
};

// ─────────────────────────────────────────────────────────────────
// INITIALIZATION & EVENT BINDING
// ─────────────────────────────────────────────────────────────────

async function init() {
    if (!Elements.chatMessages || !Elements.messageInput) return;
    
    // Load Settings
    try {
        const s = localStorage.getItem(CONSTANTS.SETTINGS_KEY);
        if (s) State.settings = { ...State.settings, ...JSON.parse(s) };
        if (Elements.settings.toggleAutoActivity) Elements.settings.toggleAutoActivity.checked = State.settings.autoOpenActivity;
        if (Elements.settings.toggleAutoSearch) Elements.settings.toggleAutoSearch.checked = State.settings.autoOpenSearchResults;
        if (Elements.settings.toggleThinkingSounds) Elements.settings.toggleThinkingSounds.checked = State.settings.thinkingSounds;
        if (Elements.settings.toggleVoiceInterrupt) Elements.settings.toggleVoiceInterrupt.checked = State.settings.voiceInterrupt;
        if (Elements.settings.toggleWakeWord) Elements.settings.toggleWakeWord.checked = State.settings.wakeWordEnabled;
        if (Elements.settings.toggleClipboard) Elements.settings.toggleClipboard.checked = State.settings.clipboardEnabled;
    } catch (_) { }

    ttsPlayer = new TTSPlayer();
    ttsPlayer.onPlaybackComplete = Voice.maybeRestartListening;

    UI.setGreeting();
    
    // Orb
    if (typeof OrbRenderer !== 'undefined') {
        orb = new OrbRenderer(Elements.orbContainer, { hue: 0, hoverIntensity: 0.3, backgroundColor: [0.02, 0.02, 0.06] });
    }

    Voice.init();
    
    // Preload Audio
    for (const file of CONSTANTS.PRE_STARTER_FILES) {
        try {
            const r = await fetch(`${API}/app/audio/${file}.mp3`);
            if (r.ok) {
                const blob = await r.blob();
                const base64 = await new Promise(res => {
                    const reader = new FileReader();
                    reader.onloadend = () => res(reader.result.split(',')[1]);
                    reader.readAsDataURL(blob);
                });
                if (base64) PRE_STARTER_CACHE[file] = base64;
            }
        } catch (_) { }
    }
    preStarterPlayer = new PreStarterPlayer();

    // Health Check
    setInterval(async () => {
        try {
            const r = await fetch(`${API}/health`, { signal: AbortSignal.timeout(3000) });
            const d = await r.json();
            const ok = d?.status === 'healthy';
            if (Elements.statusDot) Elements.statusDot.classList.toggle('offline', !ok);
            if (Elements.statusText) Elements.statusText.textContent = ok ? 'Online' : 'Offline';
        } catch (_) {
            if (Elements.statusDot) Elements.statusDot.classList.add('offline');
            if (Elements.statusText) Elements.statusText.textContent = 'Offline';
        }
    }, 10000);

    bindEvents();
    Chat.newChat(); // Initialize welcome screen
    
    if (State.settings.wakeWordEnabled) Voice.initWakeWordWS();
}

function bindEvents() {
    Elements.sendBtn?.addEventListener('click', () => Chat.sendMessage());
    Elements.messageInput?.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); Chat.sendMessage(); } });
    Elements.messageInput?.addEventListener('input', UI.autoResizeInput);
    
    Elements.screen.btn?.addEventListener('click', () => Camera.captureScreen());
    Elements.clipBtn?.addEventListener('click', () => {
        navigator.clipboard.readText().then(text => {
            if (text) Chat.sendMessage(`Analyze this clipboard content:\n\n${text}`);
            else UI.showToast('Clipboard empty');
        });
    });

    Elements.camera.btn?.addEventListener('click', () => { if (State.camStream) Camera.stop(); else Camera.start(); });
    Elements.camera.close?.addEventListener('click', () => Camera.stop());
    Elements.camera.minimize?.addEventListener('click', () => Elements.camera.panel?.classList.toggle('minimized'));

    Elements.micBtn?.addEventListener('click', () => {
        if (State.isListening) { State.autoListenMode = false; Voice.stopListening(); }
        else { State.autoListenMode = true; Voice.startListening(); }
    });

    Elements.ttsBtn?.addEventListener('click', () => {
        ttsPlayer.enabled = !ttsPlayer.enabled;
        Elements.ttsBtn.classList.toggle('tts-active', ttsPlayer.enabled);
        if (!ttsPlayer.enabled) ttsPlayer.stop();
    });

    Elements.newChatBtn?.addEventListener('click', Chat.newChat);
    Elements.settings.btn?.addEventListener('click', () => { Elements.settings.panel?.classList.toggle('open'); UI.updatePanelOverlay(); });
    Elements.settings.close?.addEventListener('click', () => { Elements.settings.panel?.classList.remove('open'); UI.updatePanelOverlay(); });
    
    Elements.activity.toggle?.addEventListener('click', () => { Elements.activity.panel?.classList.toggle('open'); UI.updatePanelOverlay(); });
    Elements.activity.close?.addEventListener('click', () => { Elements.activity.panel?.classList.remove('open'); UI.updatePanelOverlay(); });

    Elements.searchResults.close?.addEventListener('click', () => { Elements.searchResults.widget?.classList.remove('open'); UI.updatePanelOverlay(); });
    Elements.searchResults.toggle?.addEventListener('click', () => { Elements.searchResults.widget?.classList.toggle('open'); UI.updatePanelOverlay(); });

    Elements.panelOverlay?.addEventListener('click', () => {
        Elements.settings.panel?.classList.remove('open');
        Elements.activity.panel?.classList.remove('open');
        Elements.searchResults.widget?.classList.remove('open');
        UI.updatePanelOverlay();
    });

    // Toggles
    Elements.settings.toggleAutoActivity?.addEventListener('change', e => { State.settings.autoOpenActivity = e.target.checked; saveSettings(); });
    Elements.settings.toggleAutoSearch?.addEventListener('change', e => { State.settings.autoOpenSearchResults = e.target.checked; saveSettings(); });
    Elements.settings.toggleThinkingSounds?.addEventListener('change', e => { State.settings.thinkingSounds = e.target.checked; saveSettings(); });
    Elements.settings.toggleVoiceInterrupt?.addEventListener('change', e => { State.settings.voiceInterrupt = e.target.checked; saveSettings(); });
    Elements.settings.toggleWakeWord?.addEventListener('change', e => {
        State.settings.wakeWordEnabled = e.target.checked;
        saveSettings();
        if (State.settings.wakeWordEnabled) Voice.initWakeWordWS();
        else Voice.destroyWakeWordWS();
    });
    Elements.settings.toggleClipboard?.addEventListener('change', e => { State.settings.clipboardEnabled = e.target.checked; saveSettings(); });
}

function saveSettings() { localStorage.setItem(CONSTANTS.SETTINGS_KEY, JSON.stringify(State.settings)); }

document.addEventListener('DOMContentLoaded', init);