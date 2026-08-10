/**
 * Configuration → Reticulum card.
 *
 * Editor for the ``reticulum:`` block: enabled/display name plus the
 * RNode interface and TCP backbone fields that
 * ``scripts/write_rnsd_config.py`` turns into rnsd's own config file.
 * Saving here only updates local.yaml -- applying RNode/backbone
 * changes needs rnsd to actually restart (so it re-runs that script),
 * which meshpoint's normal "restart the service" instruction does NOT
 * do on its own (rnsd is a separate opt-in unit). The "Restart rnsd"
 * button below exists for exactly that, alongside the usual
 * restart-meshpoint prompt for enabled/display_name.
 */

class ReticulumConfigCard {
    constructor(api) {
        this._api = api;
        this._root = null;
        this._enumeratedPorts = [];
        this._portUsage = {};
    }

    // Matches src/api/routes/reticulum_config_routes.py's
    // _VALID_BANDWIDTHS_HZ -- the only bandwidths an RNode's SX127x/
    // SX126x radio actually accepts.
    static _BANDWIDTHS_HZ = [
        7800, 10400, 15600, 20800, 31250, 41700, 62500, 125000, 250000, 500000,
    ];

    mount(root) {
        this._root = root;
        this._root.innerHTML = `
            <div class="cfg-section" data-rt-root>
                <article class="cfg-card">
                    <header class="cfg-card__head">
                        <h3 class="cfg-card__title">Reticulum</h3>
                        <p class="cfg-card__hint">
                            Native Reticulum/LXMF messaging, sharing an RNode over USB with
                            the opt-in <code>rnsd</code> service. Requires
                            <code>rnsd</code> to be installed (Settings → System, or
                            <code>install.sh</code>) -- this card only edits its config.
                        </p>
                    </header>
                    <form class="cfg-form" data-rt-form>
                        <label class="cfg-field cfg-field--toggle">
                            <input type="checkbox" data-rt-enabled>
                            <span class="cfg-field__label">Reticulum enabled</span>
                        </label>
                        <label class="cfg-field">
                            <span class="cfg-field__label">Display name</span>
                            <input class="cfg-field__input" type="text" maxlength="32"
                                   placeholder="Meshpoint" data-rt-display-name>
                            <span class="cfg-field__hint">Shown to peers over LXMF announces.</span>
                        </label>
                        <fieldset class="cfg-fieldset">
                            <legend class="cfg-fieldset__legend">RNode radio</legend>
                            <label class="cfg-field">
                                <span class="cfg-field__label">Serial port</span>
                                <select class="cfg-field__input" data-rt-serial-port></select>
                                <button class="terminal-button cfg-firmware-rescan" type="button"
                                        data-rt-rescan-usb title="Re-scan connected USB devices">
                                    ↻ Rescan USB
                                </button>
                            </label>
                            <div class="cfg-row">
                                <label class="cfg-field">
                                    <span class="cfg-field__label">Frequency (Hz)</span>
                                    <input class="cfg-field__input" type="number"
                                           min="100000000" max="1000000000" step="1"
                                           data-rt-frequency>
                                    <span class="cfg-field__hint" data-rt-frequency-mhz>--</span>
                                </label>
                                <label class="cfg-field cfg-field--narrow">
                                    <span class="cfg-field__label">Bandwidth</span>
                                    <select class="cfg-field__input" data-rt-bandwidth>
                                        ${ReticulumConfigCard._BANDWIDTHS_HZ.map((hz) => (
                                            `<option value="${hz}">${(hz / 1000).toLocaleString()} kHz</option>`
                                        )).join('')}
                                    </select>
                                </label>
                            </div>
                            <div class="cfg-row">
                                <label class="cfg-field cfg-field--narrow">
                                    <span class="cfg-field__label">TX power (dBm)</span>
                                    <input class="cfg-field__input" type="number"
                                           min="0" max="22" step="1" data-rt-tx-power>
                                </label>
                                <label class="cfg-field cfg-field--narrow">
                                    <span class="cfg-field__label">Spreading factor</span>
                                    <input class="cfg-field__input" type="number"
                                           min="5" max="12" step="1" data-rt-sf>
                                </label>
                                <label class="cfg-field cfg-field--narrow">
                                    <span class="cfg-field__label">Coding rate</span>
                                    <input class="cfg-field__input" type="number"
                                           min="5" max="8" step="1" data-rt-cr>
                                </label>
                            </div>
                        </fieldset>
                        <fieldset class="cfg-fieldset">
                            <legend class="cfg-fieldset__legend">TCP backbone</legend>
                            <p class="cfg-field__hint">
                                Community Reticulum backbone hop, reached over the internet
                                alongside the RNode's LoRa interface.
                            </p>
                            <div class="cfg-row">
                                <label class="cfg-field">
                                    <span class="cfg-field__label">Host</span>
                                    <input class="cfg-field__input" type="text"
                                           placeholder="node.reticulumnet.nl" data-rt-backbone-host>
                                </label>
                                <label class="cfg-field cfg-field--narrow">
                                    <span class="cfg-field__label">Port</span>
                                    <input class="cfg-field__input" type="number"
                                           min="1" max="65535" data-rt-backbone-port>
                                </label>
                            </div>
                        </fieldset>
                        <div class="cfg-card__actions">
                            <button class="terminal-button terminal-button--primary" type="submit">
                                Save Reticulum
                            </button>
                        </div>
                        <p class="cfg-status" data-rt-status aria-live="polite"></p>
                    </form>
                    <div class="cfg-card__actions">
                        <button class="terminal-button" type="button" data-rt-restart-rnsd>
                            Restart rnsd
                        </button>
                    </div>
                    <p class="cfg-field__hint">
                        Applies saved RNode/backbone settings by restarting the
                        <code>rnsd</code> service directly, without a full meshpoint
                        restart. Enabled/display name changes still need the usual
                        meshpoint service restart (Settings → System).
                    </p>
                    <p class="cfg-status" data-rt-rnsd-status aria-live="polite"></p>
                </article>
            </div>
        `;

        this._form = this._root.querySelector('[data-rt-form]');
        this._enabled = this._root.querySelector('[data-rt-enabled]');
        this._displayName = this._root.querySelector('[data-rt-display-name]');
        this._serialPort = this._root.querySelector('[data-rt-serial-port]');
        this._frequency = this._root.querySelector('[data-rt-frequency]');
        this._frequencyMhz = this._root.querySelector('[data-rt-frequency-mhz]');
        this._bandwidth = this._root.querySelector('[data-rt-bandwidth]');
        this._txPower = this._root.querySelector('[data-rt-tx-power]');
        this._sf = this._root.querySelector('[data-rt-sf]');
        this._cr = this._root.querySelector('[data-rt-cr]');
        this._backboneHost = this._root.querySelector('[data-rt-backbone-host]');
        this._backbonePort = this._root.querySelector('[data-rt-backbone-port]');
        this._statusEl = this._root.querySelector('[data-rt-status]');
        this._rnsdStatusEl = this._root.querySelector('[data-rt-rnsd-status]');

        this._form.addEventListener('submit', (e) => this._onSubmit(e));
        this._frequency.addEventListener('input', () => this._renderFrequencyHint());
        this._root.querySelector('[data-rt-rescan-usb]')
            .addEventListener('click', (e) => this._rescanUsb(e.currentTarget));
        this._root.querySelector('[data-rt-restart-rnsd]')
            .addEventListener('click', () => this._restartRnsd());

        this._refreshSerialPortsList();
    }

    render(config) {
        const rt = (config && config.reticulum) || {};
        this._portUsage = this._buildPortUsageMap(config);
        this._pendingPort = rt.rnode_serial_port || '';
        this._renderDevicePicker();

        if (this._enabled) this._enabled.checked = !!rt.enabled;
        if (this._displayName) this._displayName.value = rt.display_name || 'Meshpoint';
        if (this._frequency) {
            this._frequency.value = rt.rnode_frequency_hz ?? 869463000;
            this._renderFrequencyHint();
        }
        if (this._bandwidth) this._bandwidth.value = rt.rnode_bandwidth_hz ?? 125000;
        if (this._txPower) this._txPower.value = rt.rnode_tx_power ?? 20;
        if (this._sf) this._sf.value = rt.rnode_spreading_factor ?? 8;
        if (this._cr) this._cr.value = rt.rnode_coding_rate ?? 5;
        if (this._backboneHost) this._backboneHost.value = rt.backbone_host || 'node.reticulumnet.nl';
        if (this._backbonePort) this._backbonePort.value = rt.backbone_port ?? 4242;
    }

    _renderFrequencyHint() {
        if (!this._frequencyMhz) return;
        const hz = Number(this._frequency.value);
        this._frequencyMhz.textContent = hz ? `= ${(hz / 1_000_000).toFixed(3)} MHz` : '--';
    }

    /** Same shared USB pool every other companion's port picker draws
     * from -- duplicated logic, not a shared import, matching this
     * codebase's own established convention for these cards. */
    _buildPortUsageMap(config) {
        const usage = {};
        const cap = (config && config.capture) || {};
        (Array.isArray(cap.serial) ? cap.serial : []).forEach((d) => {
            if (d.serial_port) usage[d.serial_port] = d.label ? `Serial ${d.label}` : 'Serial';
        });
        (Array.isArray(cap.meshcore_usb) ? cap.meshcore_usb : []).forEach((c) => {
            if (c.serial_port) usage[c.serial_port] = c.label ? `MeshCore ${c.label}` : 'MeshCore';
        });
        (Array.isArray(cap.pocsag_serial) ? cap.pocsag_serial : []).forEach((d) => {
            if (d.serial_port) usage[d.serial_port] = d.label ? `POCSAG ${d.label}` : 'POCSAG';
        });
        return usage;
    }

    async _refreshSerialPortsList() {
        const result = await this._api.get('/api/config/serial-ports');
        this._enumeratedPorts = (result && Array.isArray(result.ports)) ? result.ports : [];
        this._renderDevicePicker();
    }

    async _rescanUsb(button) {
        const original = button.textContent;
        button.disabled = true;
        button.textContent = 'Scanning…';
        try {
            await this._refreshSerialPortsList();
        } finally {
            button.textContent = original;
            button.disabled = false;
        }
    }

    _portOptionLabel(p, usage) {
        const devName = (p.device || '').split('/').pop();
        const chip = (p.description || '')
            .replace(/^Silicon Labs\s+/i, '')
            .replace(/\s+USB to UART Bridge Controller.*$/i, '')
            .trim() || p.description || p.device;
        const usedBy = [p.device, p.by_id, p.by_path].filter(Boolean)
            .map((alias) => usage[alias]).find(Boolean);
        const parts = [devName, chip];
        if (usedBy) parts.push(`used by ${usedBy}`);
        return parts.filter(Boolean).join(' — ');
    }

    _renderDevicePicker() {
        if (!this._serialPort) return;
        const ports = this._enumeratedPorts || [];
        const usage = this._portUsage || {};
        const pending = this._pendingPort || '';
        const options = ['<option value="">-- none --</option>'];
        ports.forEach((p) => {
            options.push(
                `<option value="${this._esc(p.stable_path)}">${this._esc(this._portOptionLabel(p, usage))}</option>`,
            );
        });
        // The configured port may be saved under a different alias than
        // the one this enumeration happens to report (e.g. a raw
        // /dev/ttyUSBn value in local.yaml vs. a by-id stable_path here
        // for the same physical device) -- match against every known
        // alias, not just stable_path, or an actually-connected board
        // wrongly shows as unplugged (real bug, caught live: a pinned
        // "/dev/ttyUSB0" showed "not currently connected" even though
        // the very same device was listed two rows above as
        // "ttyUSB0 — CP2102"). Only fall back to the synthetic
        // "not currently connected" option when truly no enumerated
        // port matches any alias.
        const pendingConnected = pending && ports.some((p) => (
            [p.device, p.stable_path, p.by_id, p.by_path].includes(pending)
        ));
        if (pending && !pendingConnected) {
            options.push(`<option value="${this._esc(pending)}">${this._esc(pending)} (not currently connected)</option>`);
        }
        this._serialPort.innerHTML = options.join('');
        // The <option> values are always each port's own stable_path
        // (never a raw device/by_id/by_path alias), so a pending value
        // saved under a different alias must be resolved to that same
        // stable_path before assigning -- setting .value to an alias
        // that matches no <option> just silently leaves the picker on
        // its first entry ("-- none --").
        if (pendingConnected) {
            const match = ports.find((p) => (
                [p.device, p.stable_path, p.by_id, p.by_path].includes(pending)
            ));
            this._serialPort.value = match.stable_path;
        } else {
            this._serialPort.value = pending;
        }
    }

    async _onSubmit(event) {
        event.preventDefault();
        const payload = {
            enabled: this._enabled.checked,
            display_name: this._displayName.value.trim() || 'Meshpoint',
            rnode_serial_port: this._serialPort.value,
            rnode_frequency_hz: Number(this._frequency.value),
            rnode_bandwidth_hz: Number(this._bandwidth.value),
            rnode_tx_power: Number(this._txPower.value),
            rnode_spreading_factor: Number(this._sf.value),
            rnode_coding_rate: Number(this._cr.value),
            backbone_host: this._backboneHost.value.trim() || 'node.reticulumnet.nl',
            backbone_port: Number(this._backbonePort.value),
        };

        this._setStatus('pending', 'Saving…');
        const result = await this._api.put('/api/config/reticulum', payload);
        if (result) {
            this._setStatus('success', 'Saved.');
            this._api.signalRestart(
                'Reticulum settings updated. RNode/backbone changes also need '
                + '"Restart rnsd" below to take effect.',
            );
        } else {
            this._setStatus('error', 'Save failed.');
        }
    }

    async _restartRnsd() {
        const ok = await window.confirmModal({
            label: 'Restart rnsd',
            description: 'Restart the rnsd service now? It briefly drops the RNode '
                + 'interface and Reticulum messaging while it reconnects.',
        });
        if (!ok) return;

        const button = this._root.querySelector('[data-rt-restart-rnsd]');
        button.disabled = true;
        this._setRnsdStatus('pending', 'Restarting rnsd…');
        try {
            const result = await this._api.post('/api/config/reticulum/restart-rnsd', {});
            if (result && result.success) {
                this._setRnsdStatus('success', 'rnsd restarted.');
            } else {
                this._setRnsdStatus('error', 'Restart failed.');
            }
        } finally {
            button.disabled = false;
        }
    }

    _setStatus(kind, message) {
        if (!this._statusEl) return;
        this._statusEl.dataset.kind = kind;
        this._statusEl.textContent = message;
    }

    _setRnsdStatus(kind, message) {
        if (!this._rnsdStatusEl) return;
        this._rnsdStatusEl.dataset.kind = kind;
        this._rnsdStatusEl.textContent = message;
    }

    _esc(str) {
        const el = document.createElement('span');
        el.textContent = str == null ? '' : String(str);
        return el.innerHTML;
    }
}

window.ReticulumConfigCard = ReticulumConfigCard;
