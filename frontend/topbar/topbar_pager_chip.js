/**
 * Topbar — emergency pager project chip (concentrator ch9, FSK).
 *
 * A single badge (unlike TopbarDapnetChip's one-per-device model --
 * there's exactly one FSK channel, not a list of companions). Reuses
 * the exact `.topbar-serial*` CSS wholesale, same visual language as
 * the DAPNET chip. Purely config-driven: no live reachability state
 * to track (no serial companion round-trip involved here at all), fed
 * directly from the same GET /api/config poll every other chip uses.
 * Hidden entirely when radio.pager_enabled is off, same as the
 * sidebar's data-requires-config gating for the Pager nav link.
 */
class TopbarPagerChip {
    constructor(groupEl) {
        this._group = groupEl;
    }

    setPager(pager) {
        const p = pager || {};
        this._group.hidden = !p.pager_enabled;
        this._group.textContent = '';
        if (!p.pager_enabled) return;
        this._group.appendChild(this._buildBadge(p));
    }

    _buildBadge(p) {
        const root = document.createElement('a');
        root.className = 'topbar-serial topbar-dapnet';
        root.href = '#/pager';
        root.setAttribute('aria-label', 'Pager channel active -- go to Pager page');
        root.title = 'Emergency pager project (concentrator ch9, FSK)';

        const brand = document.createElement('span');
        brand.className = 'topbar-serial__brand';
        brand.textContent = 'PAGER';
        root.appendChild(brand);

        const lamp = document.createElement('span');
        lamp.className = 'topbar-serial__lamp topbar-serial__lamp--online';
        lamp.setAttribute('role', 'status');
        lamp.setAttribute('aria-live', 'polite');
        const dot = document.createElement('span');
        dot.className = 'topbar-serial__dot';
        dot.setAttribute('aria-hidden', 'true');
        lamp.appendChild(dot);
        root.appendChild(lamp);

        const freqEl = document.createElement('span');
        freqEl.className = 'topbar-serial__freq';
        freqEl.textContent = this._formatFreq(p.pager_frequency_mhz);
        root.appendChild(freqEl);

        return root;
    }

    _formatFreq(mhz) {
        const n = Number(mhz);
        if (!n || Number.isNaN(n)) return '--';
        return `${n.toFixed(4)} MHz`;
    }
}

window.TopbarPagerChip = TopbarPagerChip;
