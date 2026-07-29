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
        this._tab = storedTab === 'capcodes' ? 'capcodes' : 'packets';
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
            capcode: packet.source_id,
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
            <tr class="lw-device-row">
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

        tbody.innerHTML = packets.map((p) => `
            <tr class="lw-pkt-row">
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
