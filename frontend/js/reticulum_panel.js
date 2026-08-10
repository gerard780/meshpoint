/**
 * Reticulum/LXMF monitoring panel.
 *
 * Structurally mirrors MeshCorePanel (Peers/Messages tabs, same
 * lorawan.css classes, same 15s poll). Two tabs to start, read-only --
 * a Peers roster (from received announces) and a flat Messages
 * conversation summary (reuses the existing cross-protocol
 * GET /api/messages/conversations, filtered client-side to
 * protocol==='reticulum' rather than adding a new backend endpoint).
 * No compose/send UI yet and no per-conversation thread view --
 * that's the "chat" step, deliberately deferred.
 */

const RT_TAB_STORE_KEY = 'meshpoint.rtTab';

class ReticulumPanel {
    constructor() {
        this._refreshTimer = null;
        this._mounted = false;
        this._peers = [];
        let stored = null;
        try { stored = localStorage.getItem(RT_TAB_STORE_KEY); } catch (_) {}
        this._tab = stored === 'messages' ? 'messages' : 'peers';
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
                </div>
            </section>
        `;

        document.getElementById('rt-refresh-btn')
            ?.addEventListener('click', () => this._load());
        root.querySelectorAll('[data-rt-tab]').forEach((btn) => {
            btn.addEventListener('click', () => this._setTab(btn.dataset.rtTab));
        });
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
        } catch (_) {}
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
                <td>${this._esc(p.aspect)}</td>
                <td class="lw-time">${this._fmtTime(p.first_seen)}</td>
            </tr>
        `).join('');
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
            <tr>
                <td class="lw-time">${this._fmtTime(c.last_timestamp)}</td>
                <td class="mt-name">${this._esc(c.node_name || c.node_id)}</td>
                <td>${this._esc(c.last_message || '')}</td>
                <td class="lw-num">${c.unread_count ? c.unread_count : ''}</td>
            </tr>
        `).join('');
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
