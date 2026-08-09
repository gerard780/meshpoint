/**
 * Radio tab — SX1302 Concentrator Channels card (observational).
 *
 * Read-only table of the full 9-slot concentrator plan the capture
 * source runs: per channel name, frequency, bandwidth, SF, sync word,
 * protocol, RF chain, and enabled state. ``name`` (optional, e.g.
 * eu868_reticulum()'s spare channels) is what distinguishes individual
 * channels when several share one plan-wide protocol -- for a plan with
 * multi_sf_protocol="auto", ``protocol`` itself IS each channel's own
 * name lowercased (server-derived, see config_routes.py's
 * _derive_channel_protocol()), so _protocolLabel() below has to handle
 * arbitrary values, not just the 4 known protocols.
 * Data comes from the
 * ``concentrator`` block of GET /api/config (rebuilt server-side with
 * the same call the capture source makes). Hidden when the box has no
 * concentrator source configured.
 */
/** Canonical display casing for the few protocols this dashboard actually
 * knows about. Anything else (e.g. an "auto" plan's per-channel-name-
 * derived label, like a phonetic-alphabet spare channel) falls back to
 * a plain capitalized version of whatever string arrives -- see
 * _protocolLabel(). */
const KNOWN_PROTOCOL_LABELS = {
    meshtastic: 'Meshtastic',
    pager: 'Pager',
    reticulum: 'Reticulum',
    lorawan: 'LoRaWAN',
};

class RadioConcentratorCard {
    constructor(api) {
        this._api = api;
        this._root = null;
    }

    _protocolLabel(protocol) {
        if (!protocol) return '';
        if (KNOWN_PROTOCOL_LABELS[protocol]) return KNOWN_PROTOCOL_LABELS[protocol];
        // Per-word title case, not just the string's first character --
        // multi-word "auto"-derived names (e.g. "lora pager", from a
        // channel named "LoRa Pager") need every word capitalized, or
        // "lora pager" renders as "Lora pager" instead of "Lora Pager".
        return protocol
            .split(' ')
            .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
            .join(' ');
    }

    mount(rootEl) {
        this._root = rootEl;
        rootEl.classList.add('r-card', 'r-card--readout');
        rootEl.style.display = 'none';
    }

    render(config) {
        const conc = (config && config.concentrator) || {};
        const channels = conc.channels || [];
        if (!conc.active || !channels.length) {
            this._root.style.display = 'none';
            return;
        }
        this._root.style.display = '';

        const rows = channels.map((ch) => {
            const sf = ch.protocol === 'pager'
                ? `${(ch.datarate_bps / 1000).toFixed(1)}k FSK`
                : (ch.spreading_factor ? `SF${ch.spreading_factor}` : 'SF7–12');
            const proto = this._protocolLabel(ch.protocol);
            const stateClass = ch.enabled
                ? 'ch-table__pill ch-table__pill--on'
                : 'ch-table__pill ch-table__pill--off';
            const dim = ch.enabled ? '' : ' style="opacity:0.45"';
            return `
                <tr class="ch-table__row"${dim}>
                    <td class="ch-table__idx">${ch.ch}</td>
                    <td class="ch-table__name">${ch.name ? this._esc(ch.name) : '—'}</td>
                    <td class="ch-table__hash">${ch.frequency_mhz.toFixed(3)}</td>
                    <td class="ch-table__hash">${ch.bandwidth_khz} kHz</td>
                    <td class="ch-table__hash">${sf}</td>
                    <td class="ch-table__hash">${this._esc(ch.syncword)}</td>
                    <td class="ch-table__name">${ch.enabled ? proto : '—'}</td>
                    <td class="ch-table__idx">RF${ch.rf_chain}</td>
                    <td><span class="${stateClass}">${ch.enabled ? 'On' : 'Off'}</span></td>
                </tr>
            `;
        }).join('');

        const onCount = channels.filter((c) => c.enabled).length;
        const rf = (conc.radio_0_mhz != null && conc.radio_1_mhz != null)
            ? ` · RF0 ${conc.radio_0_mhz} / RF1 ${conc.radio_1_mhz} MHz`
            : '';

        this._root.innerHTML = `
            <div class="r-card__header">
                <h3 class="r-card__title">Concentrator Channels</h3>
                <span class="r-card__subtitle">
                    SX1302 · ${onCount} of ${channels.length} on${rf}
                </span>
            </div>
            <table class="ch-table ch-table--readout">
                <thead>
                    <tr>
                        <th>CH</th>
                        <th>Name</th>
                        <th>Freq (MHz)</th>
                        <th>BW</th>
                        <th>SF</th>
                        <th>Sync</th>
                        <th>Protocol</th>
                        <th>RF</th>
                        <th>State</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        `;
    }

    _esc(str) {
        const el = document.createElement('span');
        el.textContent = str || '';
        return el.innerHTML;
    }
}

window.RadioConcentratorCard = RadioConcentratorCard;
