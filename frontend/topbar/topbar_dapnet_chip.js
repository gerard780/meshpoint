/**
 * Topbar — DAPNET/POCSAG companion chip(s).
 *
 * One small badge per configured `capture.pocsag_serial` device, same
 * "no single primary" reasoning as TopbarSerialChip (each companion is
 * an independent passive capture source). Reuses the exact
 * `.topbar-serial*` CSS wholesale -- same lamp/brand/sep visual
 * language, just DAPNET's own fields: callsign instead of node ID,
 * board name (ttgo/heltec) instead of modem preset. Hidden entirely
 * when no POCSAG companion is configured, same as the sidebar's
 * `data-requires-source` gating for the DAPNET nav link.
 */
class TopbarDapnetChip {
    constructor(groupEl) {
        this._group = groupEl;
        this._lastDevices = [];
        this._dashboardReachable = false;
    }

    setDapnet(devices) {
        this._lastDevices = Array.isArray(devices) ? devices : [];
        this._paint();
    }

    setDashboardReachable(reachable) {
        this._dashboardReachable = Boolean(reachable);
        this._paint();
    }

    _paint() {
        const list = this._lastDevices;
        this._group.hidden = list.length === 0;
        this._group.textContent = '';
        list.forEach((dev) => this._group.appendChild(this._buildBadge(dev)));
    }

    _buildBadge(dev) {
        const reachable = this._dashboardReachable;
        const connected = reachable && Boolean(dev.connected);
        const callsign = (dev.callsign || '').trim();
        const callText = !reachable ? 'Reconnecting…' : (callsign || '----');

        const root = document.createElement('span');
        root.className = 'topbar-serial topbar-dapnet';
        root.setAttribute(
            'aria-label',
            `DAPNET ${callsign || 'companion'} `
                + `${!reachable ? 'reconnecting' : (connected ? 'connected' : 'offline')}`,
        );
        root.title = !reachable
            ? 'Reconnecting to the dashboard…'
            : 'POCSAG companion (extra/pocsag_companion)';

        const brand = document.createElement('span');
        brand.className = 'topbar-serial__brand';
        brand.textContent = 'DAPNET';
        root.appendChild(brand);

        const lampState = !reachable ? 'reconnecting' : (connected ? 'online' : 'offline');
        const lamp = document.createElement('span');
        lamp.className = `topbar-serial__lamp topbar-serial__lamp--${lampState}`;
        lamp.setAttribute('role', 'status');
        lamp.setAttribute('aria-live', 'polite');
        const dot = document.createElement('span');
        dot.className = 'topbar-serial__dot';
        dot.setAttribute('aria-hidden', 'true');
        lamp.appendChild(dot);
        root.appendChild(lamp);

        const callEl = document.createElement('span');
        callEl.className = 'topbar-serial__call';
        callEl.textContent = callText;
        root.appendChild(callEl);

        const freqEl = document.createElement('span');
        freqEl.className = 'topbar-serial__freq';
        freqEl.textContent = !reachable ? '--' : this._formatFreq(dev.frequency_mhz);
        root.appendChild(this._sep());
        root.appendChild(freqEl);

        const boardEl = document.createElement('span');
        boardEl.className = 'topbar-serial__preset';
        boardEl.textContent = !reachable ? '--' : this._formatBoard(dev.board);
        root.appendChild(this._sep(true));
        root.appendChild(boardEl);

        root.classList.toggle('topbar-serial--offline', reachable && !connected);
        root.classList.toggle('topbar-serial--reconnecting', !reachable);
        return root;
    }

    _sep(bar = false) {
        const sep = document.createElement('span');
        sep.className = bar ? 'topbar-serial__sep topbar-serial__sep--bar' : 'topbar-serial__sep';
        sep.setAttribute('aria-hidden', 'true');
        sep.textContent = bar ? '|' : '·';
        return sep;
    }

    _formatFreq(mhz) {
        const n = Number(mhz);
        if (!n || Number.isNaN(n)) return '--';
        return `${n.toFixed(4)} MHz`;
    }

    _formatBoard(board) {
        const labels = { ttgo: 'TTGO LoRa32', heltec: 'Heltec V3' };
        return labels[board] || board || '--';
    }
}

window.TopbarDapnetChip = TopbarDapnetChip;
