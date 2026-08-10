/**
 * Topbar — Reticulum chip.
 *
 * Unlike every other chip here, Reticulum's live data (own address,
 * running state, peer count) isn't part of the shared GET /api/config
 * poll every other chip reads from -- that's runtime service state,
 * not config. So this chip is config-gated the same way as the others
 * (setReticulum(cfg.reticulum), called from TopbarController's normal
 * 10s /api/config poll, purely to decide visibility), but runs its
 * own separate poll of GET /api/reticulum/status once actually
 * enabled -- started/stopped as the config flag flips, not left
 * running when hidden. Same 15s cadence the Reticulum page's own
 * panel already polls at, for consistency.
 */
class TopbarReticulumChip {
    constructor(groupEl) {
        this._group = groupEl;
        this._enabled = false;
        this._statusTimer = null;
    }

    setReticulum(reticulum) {
        const r = reticulum || {};
        const wasEnabled = this._enabled;
        this._enabled = !!r.enabled;
        this._group.hidden = !this._enabled;

        if (this._enabled && !wasEnabled) {
            this._group.textContent = '';
            this._group.appendChild(this._buildBadge({ display_name: r.display_name }));
            this._loadStatus();
            this._statusTimer = setInterval(() => this._loadStatus(), 15_000);
        } else if (!this._enabled && wasEnabled) {
            clearInterval(this._statusTimer);
            this._statusTimer = null;
            this._group.textContent = '';
        }
    }

    async _loadStatus() {
        try {
            const r = await fetch('/api/reticulum/status', { credentials: 'same-origin' });
            if (!r.ok) return;
            const status = await r.json();
            this._applyStatus(status);
        } catch (_) { /* leave last-known state showing */ }
    }

    _applyStatus(status) {
        const lamp = this._group.querySelector('.topbar-serial__lamp');
        const callEl = this._group.querySelector('.topbar-serial__call');
        const freqEl = this._group.querySelector('.topbar-serial__freq');
        if (!lamp || !callEl || !freqEl) return;

        lamp.classList.remove(
            'topbar-serial__lamp--online',
            'topbar-serial__lamp--offline',
        );
        lamp.classList.add(
            status.running ? 'topbar-serial__lamp--online' : 'topbar-serial__lamp--offline',
        );
        lamp.setAttribute('aria-label', status.running ? 'Running' : 'Not running');

        callEl.textContent = status.running
            ? this._shortAddress(status.own_address)
            : 'starting…';
        freqEl.textContent = status.running
            ? `${status.peer_count ?? 0} peers`
            : '--';
    }

    _shortAddress(addr) {
        if (!addr) return '--';
        const hex = addr.replace(/[<>]/g, '');
        return hex.length > 8 ? `${hex.slice(0, 8)}…` : hex;
    }

    _buildBadge({ display_name }) {
        const root = document.createElement('a');
        root.className = 'topbar-serial topbar-reticulum';
        root.href = '#/reticulum';
        root.setAttribute('aria-label', 'Reticulum enabled -- go to Reticulum page');
        root.title = display_name ? `Reticulum (${display_name})` : 'Reticulum';

        const brand = document.createElement('span');
        brand.className = 'topbar-serial__brand';
        brand.textContent = 'RETICULUM';
        root.appendChild(brand);

        const lamp = document.createElement('span');
        lamp.className = 'topbar-serial__lamp';
        lamp.setAttribute('role', 'status');
        lamp.setAttribute('aria-live', 'polite');
        const dot = document.createElement('span');
        dot.className = 'topbar-serial__dot';
        dot.setAttribute('aria-hidden', 'true');
        lamp.appendChild(dot);
        root.appendChild(lamp);

        const callEl = document.createElement('span');
        callEl.className = 'topbar-serial__call';
        callEl.textContent = 'starting…';
        root.appendChild(callEl);

        const sep = document.createElement('span');
        sep.className = 'topbar-serial__sep';
        sep.setAttribute('aria-hidden', 'true');
        sep.textContent = '·';
        root.appendChild(sep);

        const freqEl = document.createElement('span');
        freqEl.className = 'topbar-serial__freq';
        freqEl.textContent = '--';
        root.appendChild(freqEl);

        return root;
    }
}

window.TopbarReticulumChip = TopbarReticulumChip;
