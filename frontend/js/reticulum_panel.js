/**
 * Reticulum/LXMF monitoring panel.
 *
 * Structurally mirrors MeshCorePanel/DapnetPanel (tabs, same
 * lorawan.css classes, same 15s poll). Peers (roster) + Messages (flat
 * conversation summary, reuses the existing cross-protocol
 * GET /api/messages/conversations filtered client-side to
 * protocol==='reticulum') + an admin-only Send tab -- a plain compose
 * form (destination picker + text), same shape as DapnetPanel's own
 * Send tab. Deliberately still not a per-conversation thread view --
 * sending is here to prove the round trip end-to-end, not yet a full
 * chat UI.
 */

const RT_TAB_STORE_KEY = 'meshpoint.rtTab';

// Reuses MeshCore/Meshtastic's own mt-badge--* color set (lorawan.css)
// rather than adding new CSS -- same idea, three aspects instead of
// packet types. delivery = an actual message recipient (cyan, same
// weight as a text packet); propagation/nomadnetwork.node are both
// infrastructure, not people, so they get the more muted routing/info
// colors.
const RT_ASPECT_BADGES = {
    'lxmf.delivery':      'mt-badge--text',
    'lxmf.propagation':   'mt-badge--routing',
    'nomadnetwork.node':  'mt-badge--nodeinfo',
};

class ReticulumPanel {
    constructor(identity) {
        this._refreshTimer = null;
        this._mounted = false;
        this._peers = [];
        this._sendPeerSearchQuery = '';
        // Fails open like every other panel's own guard (no identity/role
        // info at all means show it) -- the real security boundary is
        // server-side (POST /api/reticulum/send already requires admin).
        this._isAdmin = identity?.role !== 'viewer';
        let stored = null;
        try { stored = localStorage.getItem(RT_TAB_STORE_KEY); } catch (_) {}
        this._tab = (stored === 'messages' || (stored === 'send' && this._isAdmin))
            ? stored : 'peers';
        this._onWsPeer = this._onWsPeer.bind(this);
        this._onWsMessage = this._onWsMessage.bind(this);
    }

    show() {
        if (!this._mounted) {
            this._mount();
            this._mounted = true;
        }
        this._load();
        this._refreshTimer = setInterval(() => this._load(), 15_000);
        if (window.concentratorWS) {
            window.concentratorWS.on('reticulum_peer', this._onWsPeer);
            window.concentratorWS.on('reticulum_message', this._onWsMessage);
        }
    }

    hide() {
        clearInterval(this._refreshTimer);
        this._refreshTimer = null;
        // ConcentratorWebSocket has no unsubscribe primitive -- re-adding
        // the same bound callback on the next show() just means a brief
        // doubled-up refresh, not a real leak or duplicate rows (both
        // handlers below just trigger a full reload, no direct mutation).
    }

    _onWsPeer() { this._loadPeers(); }
    _onWsMessage() { this._loadMessages(); }

    _mount() {
        const root = document.getElementById('reticulum-panel');
        if (!root) return;
        root.innerHTML = `
            <header class="lw-panel__head">
                <h2 class="lw-panel__title">Reticulum</h2>
                <div class="lw-panel__actions">
                    <span class="lw-panel__limit" id="rt-own-address"></span>
                    <button class="terminal-button" type="button" id="rt-announce-btn"
                            ${this._isAdmin ? '' : 'hidden'}>Announce now</button>
                    <button class="terminal-button" type="button" id="rt-refresh-btn">Refresh</button>
                </div>
            </header>

            <section class="lw-stats" id="rt-stats">
                <div class="stat-card">
                    <div class="stat-card__label">Status</div>
                    <div class="stat-card__value" id="rt-stat-status">--</div>
                </div>
                <div class="stat-card">
                    <div class="stat-card__label">Known Peers</div>
                    <div class="stat-card__value" id="rt-stat-peers">--</div>
                </div>
                <div class="stat-card">
                    <div class="stat-card__label">Conversations</div>
                    <div class="stat-card__value" id="rt-stat-conversations">--</div>
                </div>
            </section>

            <section class="lw-section">
                <div class="panel">
                    <div class="panel__header panel__header--tabs">
                        <div class="lw-tabs" role="tablist">
                            <button class="lw-tab" type="button" role="tab"
                                    data-rt-tab="peers">Peers</button>
                            <button class="lw-tab" type="button" role="tab"
                                    data-rt-tab="messages">Messages</button>
                            <button class="lw-tab" type="button" role="tab"
                                    data-rt-tab="send" ${this._isAdmin ? '' : 'hidden'}>Send</button>
                        </div>
                    </div>
                    <div data-rt-view="peers">
                        <div class="panel__body lw-table-wrap">
                            <table class="lw-table lw-table--rt-peers">
                                <colgroup>
                                    <col class="col-time">
                                    <col class="col-name">
                                    <col class="col-id">
                                    <col class="col-type">
                                    <col class="col-time">
                                </colgroup>
                                <thead>
                                    <tr>
                                        <th>Last seen</th>
                                        <th>Display name</th>
                                        <th>Destination</th>
                                        <th>Aspect</th>
                                        <th>First seen</th>
                                    </tr>
                                </thead>
                                <tbody id="rt-peer-tbody"></tbody>
                            </table>
                            <p class="lw-empty" id="rt-peer-empty" style="display:none">
                                No Reticulum peers heard yet.
                            </p>
                        </div>
                    </div>
                    <div data-rt-view="messages" hidden>
                        <div class="panel__body lw-table-wrap">
                            <table class="lw-table lw-table--rt-messages">
                                <colgroup>
                                    <col class="col-time">
                                    <col class="col-name">
                                    <col class="col-text">
                                    <col class="col-type">
                                </colgroup>
                                <thead>
                                    <tr>
                                        <th>Last message</th>
                                        <th>Peer</th>
                                        <th>Preview</th>
                                        <th class="lw-r">Unread</th>
                                    </tr>
                                </thead>
                                <tbody id="rt-message-tbody"></tbody>
                            </table>
                            <p class="lw-empty" id="rt-message-empty" style="display:none">
                                No Reticulum messages yet.
                            </p>
                        </div>
                    </div>
                    <div data-rt-view="send" hidden>
                        <div class="panel__body">
                            <form class="cfg-form" id="rt-send-form" style="max-width:480px">
                                <label class="cfg-field">
                                    <span class="cfg-field__label">Peer</span>
                                    <div class="lw-search-wrap">
                                        <input type="text" id="rt-send-peer-search" class="lw-search"
                                               placeholder="Search by name or ID..."
                                               autocomplete="off" spellcheck="false" />
                                        <button id="rt-send-peer-search-clear" class="lw-search-clear"
                                                type="button" title="Clear search" hidden>&times;</button>
                                    </div>
                                    <select class="cfg-field__input" id="rt-send-peer" required></select>
                                </label>
                                <label class="cfg-field">
                                    <span class="cfg-field__label">Message</span>
                                    <input class="cfg-field__input" type="text"
                                           id="rt-send-text" placeholder="Message text" required>
                                </label>
                                <div class="cfg-card__actions">
                                    <button class="terminal-button terminal-button--primary"
                                            type="submit" id="rt-send-btn">Send message</button>
                                </div>
                                <p class="cfg-status" id="rt-send-status" aria-live="polite"></p>
                            </form>
                        </div>
                    </div>
                </div>
            </section>
        `;

        document.getElementById('rt-refresh-btn')
            ?.addEventListener('click', () => this._load());
        document.getElementById('rt-announce-btn')
            ?.addEventListener('click', () => this._handleAnnounce());
        root.querySelectorAll('[data-rt-tab]').forEach((btn) => {
            btn.addEventListener('click', () => this._setTab(btn.dataset.rtTab));
        });
        const messageTbody = document.getElementById('rt-message-tbody');
        if (messageTbody) {
            messageTbody.addEventListener('click', (e) => {
                const tr = e.target.closest('tr[data-node-id]');
                if (tr) this._markRead(tr.dataset.nodeId);
            });
        }
        document.getElementById('rt-send-form')
            ?.addEventListener('submit', (e) => this._handleSend(e));

        const sendPeerSearchEl = document.getElementById('rt-send-peer-search');
        const sendPeerSearchClearEl = document.getElementById('rt-send-peer-search-clear');
        if (sendPeerSearchEl) {
            sendPeerSearchEl.addEventListener('input', (e) => {
                this._sendPeerSearchQuery = e.target.value.toLowerCase();
                if (sendPeerSearchClearEl) sendPeerSearchClearEl.hidden = !e.target.value;
                this._renderSendPeers();
            });
        }
        if (sendPeerSearchClearEl && sendPeerSearchEl) {
            sendPeerSearchClearEl.addEventListener('click', () => {
                sendPeerSearchEl.value = '';
                this._sendPeerSearchQuery = '';
                sendPeerSearchClearEl.hidden = true;
                sendPeerSearchEl.focus();
                this._renderSendPeers();
            });
        }
        this._applyTab();
    }

    _setTab(tab) {
        if (tab === this._tab) return;
        this._tab = tab;
        try { localStorage.setItem(RT_TAB_STORE_KEY, tab); } catch (_) {}
        this._applyTab();
    }

    _applyTab() {
        const root = document.getElementById('reticulum-panel');
        if (!root) return;
        root.querySelectorAll('[data-rt-tab]').forEach((btn) => {
            const active = btn.dataset.rtTab === this._tab;
            btn.classList.toggle('lw-tab--active', active);
            btn.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        root.querySelectorAll('[data-rt-view]').forEach((el) => {
            el.hidden = el.dataset.rtView !== this._tab;
        });
    }

    async _load() {
        await Promise.all([this._loadStatus(), this._loadPeers(), this._loadMessages()]);
    }

    async _loadStatus() {
        try {
            const r = await fetch('/api/reticulum/status');
            if (!r.ok) return;
            const s = await r.json();
            this._setText('rt-stat-status', s.running ? 'Running' : (s.available ? 'Stopped' : 'Unavailable'));
            const addrEl = document.getElementById('rt-own-address');
            if (addrEl) addrEl.textContent = s.own_address ? `You: ${s.own_address}` : '';
        } catch (_) {}
    }

    async _loadPeers() {
        try {
            const r = await fetch('/api/reticulum/peers');
            if (!r.ok) return;
            const peers = await r.json();
            this._peers = peers;
            this._setText('rt-stat-peers', peers.length);
            this._renderPeers();
            this._renderSendPeers();
        } catch (_) {}
    }

    _renderSendPeers() {
        // Only lxmf.delivery destinations are real message recipients --
        // lxmf.propagation/nomadnetwork.node peers aren't people to
        // message, they're infrastructure, matching the backend's own
        // send_message() semantics (an LXMF delivery destination).
        const select = document.getElementById('rt-send-peer');
        if (!select) return;
        let deliveryPeers = this._peers.filter((p) => p.aspect === 'lxmf.delivery');
        if (this._sendPeerSearchQuery) {
            const q = this._sendPeerSearchQuery;
            deliveryPeers = deliveryPeers.filter((p) =>
                (p.display_name || '').toLowerCase().includes(q)
                || p.destination_hash.toLowerCase().includes(q)
            );
        }
        const previous = select.value;
        select.innerHTML = deliveryPeers.length
            ? deliveryPeers.map((p) => `
                <option value="${this._esc(p.destination_hash)}">
                    ${this._esc(p.display_name || p.destination_hash)}
                </option>
            `).join('')
            : '<option value="" disabled selected>No matching peers</option>';
        if (previous && deliveryPeers.some((p) => p.destination_hash === previous)) {
            select.value = previous;
        }
    }

    _renderPeers() {
        const tbody = document.getElementById('rt-peer-tbody');
        const empty = document.getElementById('rt-peer-empty');
        if (!tbody) return;

        if (!this._peers.length) {
            tbody.innerHTML = '';
            if (empty) empty.style.display = '';
            return;
        }
        if (empty) empty.style.display = 'none';

        tbody.innerHTML = this._peers.map((p) => `
            <tr>
                <td class="lw-time">${this._fmtTime(p.last_seen)}</td>
                <td class="mt-name">${this._esc(p.display_name || '--')}</td>
                <td class="lw-id">${this._esc(p.destination_hash)}</td>
                <td>${this._fmtAspect(p.aspect)}</td>
                <td class="lw-time">${this._fmtTime(p.first_seen)}</td>
            </tr>
        `).join('');
    }

    async _markRead(nodeId) {
        try {
            await fetch(`/api/messages/conversation/${encodeURIComponent(nodeId)}/read`, {
                method: 'POST', credentials: 'same-origin',
            });
        } catch (_) {}
        this._loadMessages();
    }

    async _loadMessages() {
        try {
            const r = await fetch('/api/messages/conversations');
            if (!r.ok) return;
            const conversations = (await r.json())
                .filter((c) => c.protocol === 'reticulum');
            this._setText('rt-stat-conversations', conversations.length);
            this._renderMessages(conversations);
        } catch (_) {}
    }

    _renderMessages(conversations) {
        const tbody = document.getElementById('rt-message-tbody');
        const empty = document.getElementById('rt-message-empty');
        if (!tbody) return;

        if (!conversations.length) {
            tbody.innerHTML = '';
            if (empty) empty.style.display = '';
            return;
        }
        if (empty) empty.style.display = 'none';

        tbody.innerHTML = conversations.map((c) => `
            <tr class="lw-pkt-row" data-node-id="${this._esc(c.node_id)}"
                ${c.unread_count ? 'title="Click to mark as read"' : ''}>
                <td class="lw-time">${this._fmtTime(c.last_timestamp)}</td>
                <td class="mt-name">${this._esc(c.node_name || c.node_id)}</td>
                <td>${this._esc(c.last_message || '')}</td>
                <td class="lw-num">${c.unread_count ? c.unread_count : ''}</td>
            </tr>
        `).join('');
    }

    async _handleAnnounce() {
        const btn = document.getElementById('rt-announce-btn');
        if (!btn) return;
        btn.disabled = true;
        try {
            const r = await fetch('/api/reticulum/announce', {
                method: 'POST', credentials: 'same-origin',
            });
            this._toast(r.ok ? 'Announce sent.' : 'Announce failed.');
        } catch (_) {
            this._toast('Announce failed.');
        } finally {
            btn.disabled = false;
        }
    }

    _toast(message) {
        // Same shared #r-toast pill app.js's own _toastAdminRequired()
        // uses -- reused directly rather than adding a second mechanism.
        let toast = document.getElementById('r-toast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'r-toast';
            toast.className = 'r-toast';
            document.body.appendChild(toast);
        }
        toast.textContent = message;
        toast.classList.add('r-toast--visible');
        setTimeout(() => toast.classList.remove('r-toast--visible'), 2500);
    }

    async _handleSend(event) {
        event.preventDefault();
        const status = document.getElementById('rt-send-status');
        const btn = document.getElementById('rt-send-btn');
        const peerEl = document.getElementById('rt-send-peer');
        const textEl = document.getElementById('rt-send-text');
        const destination_hash = peerEl?.value || '';
        const text = (textEl?.value || '').trim();
        if (!destination_hash || !text) return;

        btn.disabled = true;
        status.dataset.kind = 'pending';
        status.textContent = 'Sending…';
        try {
            const r = await fetch('/api/reticulum/send', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ destination_hash, text }),
            });
            const result = await r.json().catch(() => ({}));
            if (r.ok) {
                status.dataset.kind = 'success';
                status.textContent = 'Sent.';
                textEl.value = '';
                this._loadMessages();
            } else {
                status.dataset.kind = 'error';
                status.textContent = result.detail || 'Send failed.';
            }
        } catch (_) {
            status.dataset.kind = 'error';
            status.textContent = 'Send failed.';
        } finally {
            btn.disabled = false;
        }
    }

    _fmtAspect(aspect) {
        const cls = RT_ASPECT_BADGES[aspect] || '';
        return `<span class="mt-badge ${cls}">${this._esc(aspect || '--')}</span>`;
    }

    _fmtTime(ts) {
        if (!ts) return '--';
        try {
            const d = new Date(ts);
            const now = new Date();
            const sameDay = d.getFullYear() === now.getFullYear()
                && d.getMonth() === now.getMonth()
                && d.getDate() === now.getDate();
            if (sameDay) {
                return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
            }
            return d.toLocaleString([], {
                month: 'short', day: 'numeric',
                hour: '2-digit', minute: '2-digit', hour12: false,
            });
        } catch (_) { return ts; }
    }

    _esc(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    _setText(id, val) {
        const el = document.getElementById(id);
        if (el) el.textContent = val;
    }
}

window.ReticulumPanel = ReticulumPanel;
