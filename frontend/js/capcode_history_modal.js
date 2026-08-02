/**
 * Modal listing every page a DAPNET capcode has received, freshest
 * first -- opened by clicking a row on the DAPNET Capcodes tab. Reuses
 * the packet detail modal's pdm- and nbm- CSS classes for a consistent
 * look, same pattern as NeighboursModal. Clicking a page in the list
 * opens PacketDetailModal for that packet's full breakdown.
 */
class CapcodeHistoryModal {
    constructor() {
        this._overlay = null;
        this._capcode = null;
        this._onKeyDown = this._onKeyDown.bind(this);
    }

    /** @param {string} capcode
     *  @param {Array|null} pages - null means "still loading", an empty
     *  array means "loaded, genuinely nothing recorded" -- shown as two
     *  different messages rather than both reading as "empty". */
    show(capcode, pages) {
        this.close();
        this._capcode = capcode;

        const overlay = document.createElement('div');
        overlay.className = 'pdm-overlay';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');
        overlay.setAttribute('aria-label', 'Capcode message history');

        const modal = document.createElement('div');
        modal.className = 'pdm-modal';
        modal.addEventListener('click', (e) => e.stopPropagation());

        const loading = pages === null;
        const sorted = (pages || []).slice().sort(
            (a, b) => new Date(b.timestamp) - new Date(a.timestamp),
        );

        modal.innerHTML = `
            <header class="pdm-modal__header">
                <div>
                    <h2 class="pdm-modal__title">Capcode history</h2>
                    <div class="pdm-modal__meta">${this._esc(capcode)}${loading ? '' : ` · ${sorted.length} page${sorted.length === 1 ? '' : 's'}`}</div>
                </div>
                <button type="button" class="pdm-modal__close" aria-label="Close">&times;</button>
            </header>
            <div class="pdm-modal__body">
                <div class="nbm-list"></div>
            </div>
        `;

        const list = modal.querySelector('.nbm-list');
        if (loading) {
            list.innerHTML = '<div class="pdm-row">Loading…</div>';
        } else if (sorted.length) {
            sorted.forEach((p) => list.appendChild(this._row(p)));
        } else {
            list.innerHTML = '<div class="pdm-row">No pages recorded for this capcode yet.</div>';
        }

        modal.querySelector('.pdm-modal__close').addEventListener('click', () => this.close());
        overlay.addEventListener('click', () => this.close());
        overlay.appendChild(modal);
        document.body.appendChild(overlay);
        this._overlay = overlay;

        document.addEventListener('keydown', this._onKeyDown);
        modal.querySelector('.pdm-modal__close').focus();
    }

    /** Whether this modal is currently open on the given capcode -- lets a
     * caller's in-flight fetch check it's still relevant before rendering
     * results into what could now be a closed modal or a different one. */
    isShowing(capcode) {
        return !!this._overlay && this._capcode === capcode;
    }

    close() {
        document.removeEventListener('keydown', this._onKeyDown);
        if (this._overlay) {
            this._overlay.remove();
            this._overlay = null;
        }
        this._capcode = null;
    }

    _onKeyDown(e) {
        if (e.key === 'Escape') this.close();
    }

    _row(p) {
        const row = document.createElement('div');
        row.className = 'pdm-row nbm-row';
        if (window.PacketDetailModal) {
            row.classList.add('nbm-row--clickable');
            row.addEventListener('click', () => window.PacketDetailModal.show(p, {}));
        }
        row.innerHTML = `
            <span class="pdm-row__val nbm-row__name">${this._esc(p.text || '(no text)')}</span>
            <span class="pdm-row__val nbm-row__meta">${this._fmtTime(p.timestamp)} · ${this._esc(this._typeLabel(p.packet_type))}</span>
        `;
        return row;
    }

    _typeLabel(t) {
        if (!t) return t;
        return t.startsWith('dapnet_') ? t.slice('dapnet_'.length) : t;
    }

    _fmtTime(ts) {
        if (!ts) return '--';
        try {
            return new Date(ts).toLocaleString([], {
                month: 'short', day: 'numeric',
                hour: '2-digit', minute: '2-digit', hour12: false,
            });
        } catch (_) { return ts; }
    }

    _esc(str) {
        const el = document.createElement('span');
        el.textContent = str == null ? '' : String(str);
        return el.innerHTML;
    }
}

window.CapcodeHistoryModal = new CapcodeHistoryModal();
