/**
 * Configuration → POCSAG card.
 *
 * Edits the list of POCSAG companion boards (extra/pocsag_companion,
 * an ESP32 + SX1276/SX1262 sketch talking JSON over USB serial).
 * Deliberately minimal compared to SerialConfigCard/MeshcoreConfigCard:
 * no identity sub-block, no "send advert", no live readouts -- the
 * board has no mesh identity to rename and no protocol-level settings
 * configured from here (callsign, screen timeout, etc. live on the
 * device's own WiFi web dashboard at pocsag-companion.local). This
 * card only owns connection info: which USB port, what baud, and a
 * free-text display name/label pair.
 */

class PocsagSerialConfigCard {
    constructor(api) {
        this._api = api;
        this._root = null;
    }

    _MAX_DEVICES = 4;

    mount(root) {
        this._root = root;
        this._root.innerHTML = `
            <div class="cfg-section" data-pocsag-serial-root>
                <article class="cfg-card">
                    <header class="cfg-card__head">
                        <h3 class="cfg-card__title">POCSAG companions</h3>
                        <p class="cfg-card__hint">
                            One entry per POCSAG companion board (TTGO LoRa32, Heltec V3).
                            Up to ${this._MAX_DEVICES}. Requires a service restart after changes.
                        </p>
                    </header>
                    <label class="cfg-field cfg-field--toggle">
                        <input type="checkbox" data-pocsag-serial-enable>
                        <span class="cfg-field__label">Include POCSAG capture source</span>
                    </label>
                    <div class="cfg-companions" data-pocsag-serial-devices></div>
                    <datalist id="pocsag-serial-ports-list"></datalist>
                    <div class="cfg-companions__add-row">
                        <button class="terminal-button" type="button" data-pocsag-serial-add-device>
                            + Add device
                        </button>
                        <button class="terminal-button" type="button" data-pocsag-serial-rescan-usb
                                title="Re-scan connected USB devices for the port picker below">
                            ↻ Rescan USB
                        </button>
                    </div>
                    <div class="cfg-card__actions">
                        <button class="terminal-button terminal-button--primary"
                                type="button" data-pocsag-serial-save>
                            Save POCSAG devices
                        </button>
                    </div>
                    <p class="cfg-status" data-pocsag-serial-status aria-live="polite"></p>
                </article>
            </div>
        `;
        this._devicesEl = this._root.querySelector('[data-pocsag-serial-devices]');

        this._root.querySelector('[data-pocsag-serial-add-device]')
            .addEventListener('click', () => this._addDeviceRow());
        this._root.querySelector('[data-pocsag-serial-save]')
            .addEventListener('click', () => this._saveDevices());
        this._root.querySelector('[data-pocsag-serial-rescan-usb]')
            .addEventListener('click', (e) => this._rescanUsb(e.currentTarget));
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

    render(config) {
        this._portUsage = this._buildPortUsageMap(config);
        this._refreshSerialPortsList();

        const cap = config.capture || {};
        const devices = Array.isArray(cap.pocsag_serial) ? cap.pocsag_serial : [];
        const sources = cap.sources || [];

        const enableEl = this._root.querySelector('[data-pocsag-serial-enable]');
        if (enableEl) enableEl.checked = sources.includes('pocsag_serial');

        this._devicesEl.innerHTML = '';
        const list = devices.length > 0
            ? devices
            : [{ label: '', serial_port: '', serial_baud: 115200, name: '' }];
        list.forEach((d) => this._addDeviceRow(d));
        this._syncAddBtn();
    }

    /** Maps every currently-configured serial_port value across ALL THREE
     * USB-companion protocols (Serial/Meshtastic, MeshCore, POCSAG -- the
     * same physical USB pool) to a human label, for the "already used
     * by ..." warning in the port picker below. */
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

    /** Shared GET /api/config/serial-ports endpoint (same one Serial/MeshCore
     * use) -- best-effort, silently no-ops if unavailable. */
    async _refreshSerialPortsList() {
        const list = this._root.querySelector('#pocsag-serial-ports-list');
        if (!list) return;
        const result = await this._api.get('/api/config/serial-ports');
        const ports = (result && Array.isArray(result.ports)) ? result.ports : [];
        this._enumeratedPorts = ports;
        const usage = this._portUsage || {};
        list.innerHTML = ports.map((p) => `
            <option value="${this._esc(p.stable_path)}" label="${this._esc(this._portOptionLabel(p, usage))}"></option>
        `).join('');
        this._devicesEl.querySelectorAll('[data-device-port]').forEach((input) => {
            this._updateResolvedPort(input);
        });
    }

    _updateResolvedPort(input) {
        const resolvedEl = input.parentElement.querySelector('[data-device-port-resolved]');
        if (!resolvedEl) return;
        const value = (input.value || '').trim();
        const match = value && (this._enumeratedPorts || []).find((p) =>
            p.stable_path === value || p.by_id === value || p.by_path === value || p.device === value,
        );
        resolvedEl.textContent = (match && match.device && match.device !== value) ? `→ ${match.device}` : '';
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

    _addDeviceRow(data = {}) {
        const idx = this._devicesEl.children.length;
        if (idx >= this._MAX_DEVICES) return;

        const label = this._esc(data.label || '');
        const port = this._esc(data.serial_port || '');
        const baud = data.serial_baud != null ? data.serial_baud : 115200;
        const name = this._esc(data.name || '');

        const div = document.createElement('div');
        div.className = 'cfg-companion';
        div.dataset.deviceIdx = idx;
        div.innerHTML = `
            <div class="cfg-companion__header">
                <span class="cfg-companion__num">Device ${idx + 1}</span>
                <label class="cfg-companion__label-wrap">
                    <span class="cfg-field__label">Label</span>
                    <input class="cfg-field__input cfg-companion__label-input"
                           type="text" maxlength="16"
                           placeholder="e.g. ttgo or heltec"
                           value="${label}" data-device-label>
                </label>
                <button class="cfg-companion__remove terminal-button terminal-button--danger"
                        type="button" title="Remove device">✕</button>
            </div>
            <label class="cfg-field">
                <span class="cfg-field__label">Serial port</span>
                <input class="cfg-field__input" type="text"
                       placeholder="/dev/ttyUSB0 (blank = auto-detect)" value="${port}"
                       list="pocsag-serial-ports-list"
                       data-device-port>
                <span class="cfg-field__resolved" data-device-port-resolved></span>
                <span class="cfg-field__hint">
                    Pick a connected device below, or type a path. Prefer the
                    /dev/serial/by-path/... entries over plain /dev/ttyUSBn --
                    those stay stable across reboots/replugs.
                </span>
            </label>
            <label class="cfg-field cfg-field--narrow">
                <span class="cfg-field__label">Baud rate</span>
                <input class="cfg-field__input" type="number"
                       value="${baud}" data-device-baud>
            </label>
            <label class="cfg-field">
                <span class="cfg-field__label">Name</span>
                <input class="cfg-field__input" type="text" maxlength="36"
                       placeholder="e.g. Attic POCSAG"
                       value="${name}" data-device-name>
            </label>
        `;

        div.querySelector('.cfg-companion__remove').addEventListener('click', () => {
            div.remove();
            this._reindexDevices();
            this._syncAddBtn();
        });

        const portInput = div.querySelector('[data-device-port]');
        if (portInput) {
            portInput.addEventListener('input', () => this._updateResolvedPort(portInput));
            this._updateResolvedPort(portInput);
        }

        this._devicesEl.appendChild(div);
        this._syncAddBtn();
    }

    _reindexDevices() {
        this._devicesEl.querySelectorAll('.cfg-companion').forEach((el, i) => {
            el.dataset.deviceIdx = i;
            const num = el.querySelector('.cfg-companion__num');
            if (num) num.textContent = `Device ${i + 1}`;
        });
    }

    _syncAddBtn() {
        const btn = this._root.querySelector('[data-pocsag-serial-add-device]');
        if (!btn) return;
        const count = this._devicesEl.children.length;
        btn.disabled = count >= this._MAX_DEVICES;
        btn.title = count >= this._MAX_DEVICES
            ? `Maximum ${this._MAX_DEVICES} devices`
            : '';
    }

    async _saveDevices() {
        const status = this._root.querySelector('[data-pocsag-serial-status]');
        status.dataset.kind = 'pending';
        status.textContent = 'Saving…';

        const devices = [];
        this._devicesEl.querySelectorAll('.cfg-companion').forEach((div) => {
            devices.push({
                label: (div.querySelector('[data-device-label]')?.value || '').trim(),
                serial_port: (div.querySelector('[data-device-port]')?.value || '').trim() || null,
                serial_baud: Number(div.querySelector('[data-device-baud]')?.value) || 115200,
                name: (div.querySelector('[data-device-name]')?.value || '').trim(),
            });
        });

        const result = await this._api.put('/api/config/capture/pocsag-serial-devices', {
            enable_source: this._root.querySelector('[data-pocsag-serial-enable]').checked,
            devices,
        });

        if (result) {
            status.dataset.kind = 'success';
            status.textContent = 'Saved.';
            this._api.signalRestart('POCSAG devices updated.');
            await this._api.refresh();
        } else {
            status.dataset.kind = 'error';
            status.textContent = 'Save failed.';
        }
    }

    _esc(str) {
        const el = document.createElement('span');
        el.textContent = str || '';
        return el.innerHTML;
    }
}

window.PocsagSerialConfigCard = PocsagSerialConfigCard;
