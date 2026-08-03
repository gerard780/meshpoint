/**
 * DAPNET (POCSAG companion) monitoring panel.
 *
 * Shows a capcode roster and a recent-pages feed for extra/pocsag_companion
 * traffic. Structurally mirrors LoRaWANPanel (one-way receive protocol, no
 * conversations) and reuses its CSS classes (frontend/css/lorawan.css) --
 * a plain table/tabs/stat-card layout with no LoRaWAN-specific styling.
 *
 * One real difference from LoRaWAN: DapnetConfig's "blacklist" tier
 * (coordinator.py) shows a page live over the WebSocket feed but never
 * writes it to the database (DAPNET's own housekeeping/time-sync
 * beacons -- worth confirming they're still ticking, not worth
 * persisting). A pure DB-poll page (like LoRaWAN's) would never show
 * those at all, so this panel also subscribes to the same live
 * `window.concentratorWS.on('packet', ...)` feed the main dashboard
 * packet log uses, and prepends anything not already in the polled
 * list. Since the poll fully replaces the list every 15s, a
 * blacklisted page naturally drops off screen again once its live-only
 * moment passes -- that's intentional, not a bug: it was never stored,
 * so there's nothing for the next poll to reconstruct it from.
 */

const DP_TAB_STORE_KEY = 'meshpoint.dpTab';

class DapnetPanel {
    constructor() {
        this._refreshTimer = null;
        this._mounted = false;
        this._allCapcodes = [];
        this._capcodeSearchQuery = '';
        this._packets = [];
        this._liveOnlyIds = new Set();
        let storedTab = null;
        try { storedTab = localStorage.getItem(DP_TAB_STORE_KEY); } catch (_) {}
        this._tab = (storedTab === 'capcodes' || storedTab === 'send') ? storedTab : 'packets';
        this._sendDevices = [];
        this._onWsPacket = this._onWsPacket.bind(this);
    }

    /** Called by the router when the section becomes active. */
    show() {
        if (!this._mounted) {
            this._mount();
            this._mounted = true;
        }
        this._load();
        this._refreshTimer = setInterval(() => this._load(), 15_000);
        if (window.concentratorWS) window.concentratorWS.on('packet', this._onWsPacket);
    }

    /** Called by the router when the section is hidden. */
    hide() {
        clearInterval(this._refreshTimer);
        this._refreshTimer = null;
        // ConcentratorWebSocket has no unsubscribe primitive (on() only)
        // -- re-navigating to this page re-adds the same bound callback,
        // but _onWsPacket's own packet_id dedup makes the resulting
        // duplicate calls harmless no-ops rather than duplicate rows.
    }

    _onWsPacket(packet) {
        if (!packet || packet.protocol !== 'dapnet') return;
        if (this._packets.some((p) => p.packet_id === packet.packet_id)) return;
        const payload = packet.decoded_payload || {};
        this._liveOnlyIds.add(packet.packet_id);
        this._packets.unshift({
            packet_id: packet.packet_id,
            // protocol/source_id kept (not just flattened out to capcode/
            // function/text) so a row clicked while still live-only --
            // arrived over the WS feed, not yet caught up by the next
            // _loadPackets() poll -- still normalizes correctly in
            // PacketDetailModal (it keys off packet.protocol === 'dapnet'
            // to know to reshape this flattened row into the nested
            // decoded_payload shape every other protocol's rows already
            // have); without it the popup silently showed no page text.
            protocol: packet.protocol,
            source_id: packet.source_id,
            capcode: packet.destination_id,
            packet_type: packet.packet_type,
            capture_source: packet.capture_source,
            timestamp: packet.timestamp,
            function: payload.function,
            text: payload.text || '',
        });
        this._renderPackets();
    }

    _mount() {
        const root = document.getElementById('dapnet-panel');
        if (!root) return;
        root.innerHTML = `
            <header class="lw-panel__head">
                <h2 class="lw-panel__title">DAPNET</h2>
                <div class="lw-panel__actions">
                    <button class="terminal-button" type="button" id="dp-export-btn">Export CSV</button>
                    <button class="terminal-button" type="button" id="dp-refresh-btn">Refresh</button>
                </div>
            </header>

            <section class="lw-stats" id="dp-stats">
                <div class="stat-card">
                    <div class="stat-card__label">Total Pages</div>
                    <div class="stat-card__value" id="dp-stat-total">--</div>
                </div>
                <div class="stat-card">
                    <div class="stat-card__label">Unique Capcodes</div>
                    <div class="stat-card__value" id="dp-stat-capcodes">--</div>
                </div>
                <div class="stat-card">
                    <div class="stat-card__label">Alpha</div>
                    <div class="stat-card__value" id="dp-stat-alpha">--</div>
                </div>
                <div class="stat-card">
                    <div class="stat-card__label">Tone</div>
                    <div class="stat-card__value" id="dp-stat-tone">--</div>
                </div>
            </section>

            <section class="lw-section">
                <div class="panel">
                    <div class="panel__header panel__header--tabs">
                        <div class="lw-tabs" role="tablist">
                            <button class="lw-tab" type="button" role="tab"
                                    data-dp-tab="packets">Recent pages</button>
                            <button class="lw-tab" type="button" role="tab"
                                    data-dp-tab="capcodes">Capcodes</button>
                            <button class="lw-tab" type="button" role="tab"
                                    data-dp-tab="send">Send</button>
                        </div>
                        <span class="lw-panel__limit" data-dp-suffix="packets">(last 100)</span>
                        <div class="lw-search-wrap" data-dp-suffix="capcodes" hidden>
                            <span class="lw-panel__limit" id="dp-capcode-count"></span>
                            <input type="text" id="dp-capcode-search" class="lw-search"
                                   placeholder="Search..." autocomplete="off" spellcheck="false" />
                            <button id="dp-capcode-search-clear" class="lw-search-clear"
                                    title="Clear search" hidden>&times;</button>
                        </div>
                    </div>
                    <div data-dp-view="packets">
                        <div class="panel__body lw-table-wrap">
                        <table class="lw-table lw-table--dapnet-packets">
                            <colgroup>
                                <col class="col-time">
                                <col class="col-type">
                                <col class="col-dev">
                                <col class="col-text">
                            </colgroup>
                            <thead>
                                <tr>
                                    <th>Time</th>
                                    <th>Type</th>
                                    <th>Capcode</th>
                                    <th>Text</th>
                                </tr>
                            </thead>
                            <tbody id="dp-packet-tbody"></tbody>
                        </table>
                        <p class="lw-empty" id="dp-packet-empty" style="display:none">
                            No pages yet.
                        </p>
                        </div>
                    </div>
                    <div data-dp-view="capcodes" hidden>
                        <div class="panel__body lw-table-wrap">
                        <table class="lw-table lw-table--dapnet-capcodes">
                            <colgroup>
                                <col class="col-time">
                                <col class="col-time">
                                <col class="col-id">
                                <col class="col-type">
                                <col class="col-frames">
                                <col class="col-text">
                            </colgroup>
                            <thead>
                                <tr>
                                    <th>Last seen</th>
                                    <th>First seen</th>
                                    <th>Capcode</th>
                                    <th>Type</th>
                                    <th class="lw-r">Pages</th>
                                    <th>Last text</th>
                                </tr>
                            </thead>
                            <tbody id="dp-capcode-tbody"></tbody>
                        </table>
                        <p class="lw-empty" id="dp-capcode-empty" style="display:none">
                            No DAPNET capcodes heard yet.
                        </p>
                        </div>
                    </div>
                    <div data-dp-view="send" hidden>
                        <div class="panel__body">
                            <form class="cfg-form" id="dp-send-form" style="max-width:480px">
                                <label class="cfg-field" data-dp-send-device-wrap hidden>
                                    <span class="cfg-field__label">Companion</span>
                                    <select class="cfg-field__input" id="dp-send-device"></select>
                                </label>
                                <label class="cfg-field">
                                    <span class="cfg-field__label">Capcode (optional)</span>
                                    <input class="cfg-field__input" type="number" min="1"
                                           id="dp-send-capcode" placeholder="Companion default">
                                </label>
                                <label class="cfg-field">
                                    <span class="cfg-field__label">Message</span>
                                    <input class="cfg-field__input" type="text"
                                           id="dp-send-text" placeholder="Message text" required>
                                </label>
                                <div class="cfg-card__actions">
                                    <button class="terminal-button terminal-button--primary"
                                            type="submit" id="dp-send-btn">Send page</button>
                                </div>
                                <p class="cfg-status" id="dp-send-status" aria-live="polite"></p>
                            </form>
                        </div>
                    </div>
                </div>
            </section>
        `;

        document.getElementById('dp-refresh-btn')
            ?.addEventListener('click', () => this._load());
        document.getElementById('dp-export-btn')
            ?.addEventListener('click', () => {
                const ds = this._tab === 'capcodes' ? 'capcodes' : 'packets';
                window.location = `/api/dapnet/export/${ds}.csv`;
            });
        root.querySelectorAll('[data-dp-tab]').forEach((btn) => {
            btn.addEventListener('click', () => this._setTab(btn.dataset.dpTab));
        });
        this._applyTab();

        const capcodeSearchEl = document.getElementById('dp-capcode-search');
        const capcodeSearchClearEl = document.getElementById('dp-capcode-search-clear');
        if (capcodeSearchEl) {
            capcodeSearchEl.addEventListener('input', (e) => {
                this._capcodeSearchQuery = e.target.value.toLowerCase();
                if (capcodeSearchClearEl) capcodeSearchClearEl.hidden = !e.target.value;
                this._renderCapcodes();
            });
        }
        if (capcodeSearchClearEl && capcodeSearchEl) {
            capcodeSearchClearEl.addEventListener('click', () => {
                capcodeSearchEl.value = '';
                this._capcodeSearchQuery = '';
                capcodeSearchClearEl.hidden = true;
                capcodeSearchEl.focus();
                this._renderCapcodes();
            });
        }

        const pktTbody = document.getElementById('dp-packet-tbody');
        if (pktTbody) {
            pktTbody.addEventListener('click', (e) => {
                const tr = e.target.closest('tr[data-pkt]');
                if (!tr || !window.PacketDetailModal) return;
                const pkt = (this._packets || [])[Number(tr.dataset.pkt)];
                if (!pkt) return;
                window.PacketDetailModal.show(pkt, { selectedRow: tr });
            });
        }

        const capcodeTbody = document.getElementById('dp-capcode-tbody');
        if (capcodeTbody) {
            capcodeTbody.addEventListener('click', (e) => {
                const tr = e.target.closest('tr[data-capcode]');
                if (!tr || !window.CapcodeHistoryModal) return;
                this._openCapcodeHistory(tr.dataset.capcode);
            });
        }

        document.getElementById('dp-send-form')
            ?.addEventListener('submit', (e) => this._handleSend(e));
    }

    async _loadSendDevices() {
        try {
            const r = await fetch('/api/config', { credentials: 'same-origin' });
            if (!r.ok) return;
            const cfg = await r.json();
            const cap = cfg.capture || {};
            const configured = Array.isArray(cap.pocsag_serial) ? cap.pocsag_serial : [];
            const liveByName = {};
            (Array.isArray(cfg.dapnet_status) ? cfg.dapnet_status : []).forEach((s) => {
                liveByName[s.name] = s;
            });
            this._sendDevices = configured.map((d) => {
                const name = d.label ? `dapnet_${d.label}` : 'dapnet';
                return { label: d.label || '', connected: !!liveByName[name]?.connected };
            });
            this._renderSendDevices();
        } catch (_) {}
    }

    _renderSendDevices() {
        const wrap = document.querySelector('[data-dp-send-device-wrap]');
        const select = document.getElementById('dp-send-device');
        if (!wrap || !select) return;
        // Only worth choosing between when there's more than one -- with
        // 0 or 1 configured, whichever exists (or none) is implied.
        wrap.hidden = this._sendDevices.length < 2;
        select.innerHTML = this._sendDevices.map((d) => `
            <option value="${this._esc(d.label)}">
                ${this._esc(d.label || 'Default')}${d.connected ? '' : ' (offline)'}
            </option>
        `).join('');
    }

    async _handleSend(event) {
        event.preventDefault();
        const status = document.getElementById('dp-send-status');
        const btn = document.getElementById('dp-send-btn');
        const textEl = document.getElementById('dp-send-text');
        const capcodeEl = document.getElementById('dp-send-capcode');
        const deviceEl = document.getElementById('dp-send-device');
        const text = (textEl?.value || '').trim();
        if (!text) return;

        const body = { label: deviceEl?.value || '', text };
        if (capcodeEl?.value) body.capcode = Number(capcodeEl.value);

        btn.disabled = true;
        status.dataset.kind = 'pending';
        status.textContent = 'Sending…';
        try {
            const r = await fetch('/api/config/dapnet/send', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const result = await r.json().catch(() => ({}));
            if (r.ok) {
                status.dataset.kind = 'success';
                status.textContent = 'Sent.';
                textEl.value = '';
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

    async _openCapcodeHistory(capcode) {
        window.CapcodeHistoryModal.show(capcode, null);
        try {
            const r = await fetch(`/api/dapnet/packets?capcode=${encodeURIComponent(capcode)}&limit=200`);
            if (!r.ok) return;
            const pages = await r.json();
            // Only redraw if the modal is still open on this same capcode --
            // the fetch could resolve after the operator already closed it
            // or clicked a different row.
            if (window.CapcodeHistoryModal.isShowing(capcode)) {
                window.CapcodeHistoryModal.show(capcode, pages);
            }
        } catch (_) {}
    }

    _setTab(tab) {
        if (tab === this._tab) return;
        this._tab = tab;
        try { localStorage.setItem(DP_TAB_STORE_KEY, tab); } catch (_) {}
        this._applyTab();
    }

    _applyTab() {
        const root = document.getElementById('dapnet-panel');
        if (!root) return;
        root.querySelectorAll('[data-dp-tab]').forEach((btn) => {
            const active = btn.dataset.dpTab === this._tab;
            btn.classList.toggle('lw-tab--active', active);
            btn.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        root.querySelectorAll('[data-dp-view]').forEach((el) => {
            el.hidden = el.dataset.dpView !== this._tab;
        });
        root.querySelectorAll('[data-dp-suffix]').forEach((el) => {
            el.hidden = el.dataset.dpSuffix !== this._tab;
        });
    }

    async _load() {
        await Promise.all([
            this._loadStats(),
            this._loadCapcodes(),
            this._loadPackets(),
            this._loadSendDevices(),
        ]);
    }

    async _loadStats() {
        try {
            const r = await fetch('/api/dapnet/stats');
            if (!r.ok) return;
            const s = await r.json();
            this._setText('dp-stat-total', s.total_packets ?? '--');
            this._setText('dp-stat-capcodes', s.unique_capcodes ?? '--');
            this._setText('dp-stat-alpha', s.by_type?.dapnet_alpha ?? 0);
            this._setText('dp-stat-tone', s.by_type?.dapnet_tone ?? 0);
        } catch (_) {}
    }

    async _loadCapcodes() {
        try {
            const r = await fetch('/api/dapnet/capcodes');
            if (!r.ok) return;
            this._allCapcodes = await r.json();
            this._renderCapcodes();
        } catch (_) {}
    }

    _renderCapcodes() {
        const tbody = document.getElementById('dp-capcode-tbody');
        const empty = document.getElementById('dp-capcode-empty');
        if (!tbody) return;

        let capcodes = this._allCapcodes;
        if (this._capcodeSearchQuery) {
            capcodes = capcodes.filter((c) => {
                const id = String(c.capcode || '').toLowerCase();
                const type = (c.packet_type || '').toLowerCase();
                const text = (c.last_text || '').toLowerCase();
                return id.includes(this._capcodeSearchQuery)
                    || type.includes(this._capcodeSearchQuery)
                    || text.includes(this._capcodeSearchQuery);
            });
        }

        const count = document.getElementById('dp-capcode-count');
        if (count) {
            count.textContent = this._allCapcodes.length
                ? (this._capcodeSearchQuery
                    ? `(${capcodes.length} of ${this._allCapcodes.length})`
                    : `(${this._allCapcodes.length} total)`)
                : '';
        }

        if (!capcodes.length) {
            tbody.innerHTML = '';
            if (empty) {
                empty.textContent = this._allCapcodes.length
                    ? 'No capcodes match your search.'
                    : 'No DAPNET capcodes heard yet.';
                empty.style.display = '';
            }
            return;
        }
        if (empty) empty.style.display = 'none';

        tbody.innerHTML = capcodes.map((c) => `
            <tr class="lw-device-row" data-capcode="${this._esc(String(c.capcode ?? ''))}">
                <td class="lw-time">${this._fmtTime(c.last_seen)}</td>
                <td class="lw-time">${this._fmtTime(c.first_seen)}</td>
                <td class="lw-id">${this._esc(String(c.capcode ?? '--'))}</td>
                <td>${this._fmtType(c.packet_type)}</td>
                <td class="lw-num">${c.frame_count}</td>
                <td class="lw-text">${this._esc(c.last_text || '')}</td>
            </tr>
        `).join('');
    }

    async _loadPackets() {
        try {
            const r = await fetch('/api/dapnet/packets?limit=100');
            if (!r.ok) return;
            const polled = await r.json();
            // Merge rather than replace: live-only (blacklisted, never
            // stored) rows aren't in `polled` and would otherwise vanish
            // the instant this runs. Keep any live-only row still not
            // covered by the poll, drop the rest, re-sort newest first.
            const polledIds = new Set(polled.map((p) => p.packet_id));
            const stillLiveOnly = this._packets.filter(
                (p) => this._liveOnlyIds.has(p.packet_id) && !polledIds.has(p.packet_id),
            );
            this._packets = [...stillLiveOnly, ...polled].sort(
                (a, b) => new Date(b.timestamp) - new Date(a.timestamp),
            );
            this._renderPackets();
        } catch (_) {}
    }

    _renderPackets() {
        const tbody = document.getElementById('dp-packet-tbody');
        const empty = document.getElementById('dp-packet-empty');
        if (!tbody) return;

        const packets = this._packets;
        if (!packets.length) {
            tbody.innerHTML = '';
            if (empty) empty.style.display = '';
            return;
        }
        if (empty) empty.style.display = 'none';

        tbody.innerHTML = packets.map((p, i) => `
            <tr class="lw-pkt-row" data-pkt="${i}">
                <td class="lw-time">${this._fmtTime(p.timestamp)}</td>
                <td>${this._fmtType(p.packet_type)}</td>
                <td class="lw-id">${this._esc(String(p.capcode ?? '--'))}</td>
                <td class="lw-text">${this._esc(p.text || '')}</td>
            </tr>
        `).join('');
    }

    _fmtType(t) {
        const map = {
            dapnet_alpha:      '<span class="lw-badge lw-badge--data">Alpha</span>',
            dapnet_numeric:    '<span class="lw-badge lw-badge--join">Numeric</span>',
            dapnet_tone:       '<span class="lw-badge lw-badge--rejoin">Tone</span>',
            dapnet_activation: '<span class="lw-badge">Activation</span>',
        };
        return map[t] || `<span class="lw-badge">${this._esc(t || '--')}</span>`;
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

    _setText(id, val) {
        const el = document.getElementById(id);
        if (el) el.textContent = val;
    }

    _esc(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }
}

window.DapnetPanel = DapnetPanel;
