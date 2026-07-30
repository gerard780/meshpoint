/**
 * Configuration → POCSAG page: two cards.
 *
 * "POCSAG companions" edits the list of companion boards
 * (extra/pocsag_companion, an ESP32 + SX1276/SX1262 sketch talking JSON
 * over USB serial). Deliberately minimal compared to
 * SerialConfigCard/MeshcoreConfigCard: no identity sub-block, no "send
 * advert" -- the board has no mesh identity to rename, and its own
 * protocol settings (callsign, screen timeout, etc.) live on the
 * device's own WiFi web dashboard at pocsag-companion.local, not here.
 * This card only owns connection info: which USB port, what baud, and
 * a free-text display name/label. It DOES show live readouts (same
 * `cfg-mc-readout` tiles as Serial/MeshCore), sourced from
 * `config.dapnet_status` -- the same per-device connected/board/
 * callsign/frequency_mhz/hostname/wifi_ssid/wifi_ip data the topbar's
 * DAPNET chip partly consumes too (DapnetSerialSource's periodic
 * {"cmd":"status"} query). hostname/wifi_ssid/wifi_ip (the last as a
 * clickable link to the companion's own web UI) only show here, not
 * on the topbar chip -- kept that one compact.
 * There's no bandwidth/SF/TX-power/firmware equivalent here (POCSAG is
 * fixed-frequency FSK, not LoRa, and the sketch's status reply doesn't
 * report a firmware version), so the tile set is deliberately smaller
 * than MeshCore's -- only fields that actually exist are shown.
 *
 * "DAPNET capcode filters" is unrelated to the connection above -- it
 * edits DapnetConfig's two dashboard-side capcode tiers (see
 * coordinator.py's _dapnet_capcode_tier): blacklist (shown live on the
 * DAPNET page, never written to the packets table) and ignore (neither
 * shown nor stored). Both apply to already-decoded pages, regardless
 * of which companion board or serial port they came from.
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

                <article class="cfg-card">
                    <header class="cfg-card__head">
                        <h3 class="cfg-card__title">DAPNET settings</h3>
                        <p class="cfg-card__hint">
                            Neither of the two lists below is a serial-connection setting --
                            both are capcode filters on the decoded DAPNET/POCSAG page feed,
                            and take effect immediately (no restart needed).
                        </p>
                    </header>
                    <label class="cfg-field">
                        <span class="cfg-field__label">Blacklist -- shown live, never stored (comma-separated)</span>
                        <input class="cfg-field__input" type="text"
                               placeholder="e.g. 200, 208, 216, 224"
                               data-dapnet-blacklist>
                        <span class="cfg-field__hint">
                            DAPNET's own network housekeeping/time-sync beacons repeat every
                            couple of minutes on a handful of fixed, well-known capcodes -- worth
                            confirming they're still ticking, not worth persisting.
                        </span>
                    </label>
                    <label class="cfg-field">
                        <span class="cfg-field__label">Ignore -- never shown, never stored (comma-separated)</span>
                        <input class="cfg-field__input" type="text"
                               placeholder="e.g. 4512, 4520"
                               data-dapnet-ignore>
                        <span class="cfg-field__hint">
                            Pure noise you never want to see at all.
                        </span>
                    </label>
                    <label class="cfg-field cfg-field--narrow">
                        <span class="cfg-field__label">Status poll interval (seconds)</span>
                        <input class="cfg-field__input" type="number" min="10" max="3600"
                               data-dapnet-poll-interval>
                        <span class="cfg-field__hint">
                            How often each connected companion is re-asked for its status
                            (TX count, uptime, etc.) -- default 60s. Unlike the two lists
                            above, this needs a service restart to take effect.
                        </span>
                    </label>
                    <div class="cfg-card__actions">
                        <button class="terminal-button terminal-button--primary"
                                type="button" data-dapnet-save>
                            Save DAPNET settings
                        </button>
                    </div>
                    <p class="cfg-status" data-dapnet-status aria-live="polite"></p>
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
        this._root.querySelector('[data-dapnet-save]')
            .addEventListener('click', () => this._saveDapnetBlacklist());
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
        // Live per-device status (connected/board/callsign/frequency_mhz),
        // keyed by `name` -- e.g. "dapnet_heltec" or bare "dapnet" -- same
        // shape/convention the topbar's DAPNET chip already reads.
        this._liveStatuses = Array.isArray(config.dapnet_status) ? config.dapnet_status : [];

        const enableEl = this._root.querySelector('[data-pocsag-serial-enable]');
        if (enableEl) enableEl.checked = sources.includes('pocsag_serial');

        this._devicesEl.innerHTML = '';
        const list = devices.length > 0
            ? devices
            : [{ label: '', serial_port: '', serial_baud: 115200, name: '' }];
        list.forEach((d) => this._addDeviceRow(d));
        this._syncAddBtn();

        const dapnet = config.dapnet || {};
        const blacklistEl = this._root.querySelector('[data-dapnet-blacklist]');
        if (blacklistEl) {
            blacklistEl.value = (Array.isArray(dapnet.blacklist_capcodes) ? dapnet.blacklist_capcodes : []).join(', ');
        }
        const ignoreEl = this._root.querySelector('[data-dapnet-ignore]');
        if (ignoreEl) {
            ignoreEl.value = (Array.isArray(dapnet.ignore_capcodes) ? dapnet.ignore_capcodes : []).join(', ');
        }
        const pollIntervalEl = this._root.querySelector('[data-dapnet-poll-interval]');
        if (pollIntervalEl) {
            pollIntervalEl.value = dapnet.status_poll_interval_s ?? 60;
        }
    }

    /** Parses "200, 208, 216" into [200, 208, 216], dropping anything
     * that isn't a plain integer -- silently, since a typo here should
     * just not-match a capcode rather than block the whole save. */
    _parseCapcodeList(value) {
        return (value || '')
            .split(',')
            .map((s) => s.trim())
            .filter(Boolean)
            .map((s) => parseInt(s, 10))
            .filter((n) => Number.isInteger(n));
    }

    async _saveDapnetBlacklist() {
        const status = this._root.querySelector('[data-dapnet-status]');
        status.dataset.kind = 'pending';
        status.textContent = 'Saving…';

        const blacklistEl = this._root.querySelector('[data-dapnet-blacklist]');
        const ignoreEl = this._root.querySelector('[data-dapnet-ignore]');
        const pollIntervalEl = this._root.querySelector('[data-dapnet-poll-interval]');

        const result = await this._api.put('/api/config/dapnet', {
            blacklist_capcodes: this._parseCapcodeList(blacklistEl?.value),
            ignore_capcodes: this._parseCapcodeList(ignoreEl?.value),
            status_poll_interval_s: Number(pollIntervalEl?.value) || 60,
        });

        if (result) {
            status.dataset.kind = 'success';
            status.textContent = result.restart_required
                ? 'Saved. Restart the service from Settings → System for the new poll interval to apply.'
                : 'Saved.';
            await this._api.refresh();
        } else {
            status.dataset.kind = 'error';
            status.textContent = 'Save failed.';
        }
    }

    _liveStatusFor(label) {
        const name = label ? `dapnet_${label}` : 'dapnet';
        return (this._liveStatuses || []).find((s) => s.name === name) || null;
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
        const live = this._liveStatusFor(data.label || '');

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
            ${this._deviceReadoutsHtml(live)}
            ${this._callsignEditHtml(live)}
            ${this._webPasswordEditHtml(live)}
            ${this._wifiEditHtml(live)}
            ${this._resetCredentialsHtml(live)}
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

        const callsignSaveBtn = div.querySelector('[data-callsign-save]');
        if (callsignSaveBtn) {
            callsignSaveBtn.addEventListener('click', () => {
                this._saveCallsign(div, data.label || '');
            });
        }

        const webPasswordSaveBtn = div.querySelector('[data-web-password-save]');
        if (webPasswordSaveBtn) {
            webPasswordSaveBtn.addEventListener('click', () => {
                this._saveWebPassword(div, data.label || '');
            });
        }

        const wifiSaveBtn = div.querySelector('[data-wifi-save]');
        if (wifiSaveBtn) {
            wifiSaveBtn.addEventListener('click', () => {
                this._saveWifi(div, data.label || '');
            });
        }

        const resetCredentialsBtn = div.querySelector('[data-reset-credentials]');
        if (resetCredentialsBtn) {
            resetCredentialsBtn.addEventListener('click', () => {
                this._resetCredentials(div, data.label || '');
            });
        }

        this._devicesEl.appendChild(div);
        this._syncAddBtn();
    }

    /** Live connection/board readouts for one row -- same `cfg-mc-readout`
     * tiles Serial/MeshCore use, but only the fields DAPNET actually has:
     * no LoRa params (POCSAG is fixed-frequency FSK, not LoRa) and no
     * firmware version. tx_count/last_tx_ok/uptime_ms only stay current
     * because the status query now repeats periodically -- see
     * DapnetSerialSource's own docstring. */
    _deviceReadoutsHtml(live) {
        if (!live || !live.connected) {
            return `<p class="cfg-companion__offline-hint">Not connected.</p>`;
        }
        return `
            <div class="cfg-mc-readouts">
                <div class="cfg-mc-readout">
                    <span class="cfg-mc-readout__label">Callsign</span>
                    <span class="cfg-mc-readout__value">${this._esc(live.callsign || '--')}</span>
                </div>
                <div class="cfg-mc-readout">
                    <span class="cfg-mc-readout__label">Frequency</span>
                    <span class="cfg-mc-readout__value">${this._fmtFreq(live.frequency_mhz)}</span>
                </div>
                <div class="cfg-mc-readout">
                    <span class="cfg-mc-readout__label">Hardware</span>
                    <span class="cfg-mc-readout__value">${this._fmtBoard(live.board)}</span>
                </div>
                <div class="cfg-mc-readout">
                    <span class="cfg-mc-readout__label">Web UI</span>
                    <span class="cfg-mc-readout__value">${this._webUiHtml(live)}</span>
                </div>
                <div class="cfg-mc-readout">
                    <span class="cfg-mc-readout__label">WiFi SSID</span>
                    <span class="cfg-mc-readout__value">${this._esc(live.wifi_ssid || '--')}</span>
                </div>
                <div class="cfg-mc-readout">
                    <span class="cfg-mc-readout__label">TX Count</span>
                    <span class="cfg-mc-readout__value">${live.tx_count ?? '--'}</span>
                </div>
                <div class="cfg-mc-readout">
                    <span class="cfg-mc-readout__label">Last TX</span>
                    <span class="cfg-mc-readout__value">${this._fmtLastTx(live)}</span>
                </div>
                <div class="cfg-mc-readout">
                    <span class="cfg-mc-readout__label">Uptime</span>
                    <span class="cfg-mc-readout__value">${this._fmtUptime(live.uptime_ms)}</span>
                </div>
            </div>
        `;
    }

    /** Links to the companion's OWN web dashboard (pocsag-companion.local
     * by default -- callsign/screen-timeout live there, not here). Prefers
     * the IP for the actual link target (mDNS resolution isn't always
     * reliable client-side) but labels it with the hostname when known,
     * since that's what stays stable across a DHCP lease renewal. */
    _webUiHtml(live) {
        const ip = (live.wifi_ip || '').trim();
        const hostname = (live.hostname || '').trim();
        if (!ip && !hostname) return '--';
        const href = ip ? `http://${ip}/` : `http://${hostname}.local/`;
        const label = hostname ? `${hostname}.local` : ip;
        return `<a href="${this._esc(href)}" target="_blank" rel="noopener">${this._esc(label)}</a>`;
    }

    /** Editable callsign, set over the companion's live serial connection
     * (PUT /api/config/dapnet/callsign) -- unlike everything else on this
     * card, there's nothing to persist in local.yaml afterward, since the
     * callsign lives entirely in the companion's own NVS. Only rendered
     * when connected; there's no serial link to send the command over
     * otherwise. */
    _callsignEditHtml(live) {
        if (!live || !live.connected) return '';
        return `
            <div class="cfg-mc-identity" data-callsign-edit>
                <label class="cfg-field cfg-field--inline">
                    <span class="cfg-field__label">Set callsign (required before TX)</span>
                    <input class="cfg-field__input" type="text" maxlength="8"
                           placeholder="e.g. AB1CDE"
                           data-callsign-input>
                </label>
                <div class="cfg-card__actions">
                    <button class="terminal-button terminal-button--primary"
                            type="button" data-callsign-save>
                        Set Callsign
                    </button>
                </div>
                <p class="cfg-status" data-callsign-status aria-live="polite"></p>
            </div>
        `;
    }

    async _saveCallsign(deviceDiv, label) {
        const input = deviceDiv.querySelector('[data-callsign-input]');
        const status = deviceDiv.querySelector('[data-callsign-status]');
        const button = deviceDiv.querySelector('[data-callsign-save]');
        if (!input || !status) return;

        const callsign = (input.value || '').trim();
        if (!callsign) {
            status.dataset.kind = 'error';
            status.textContent = 'Enter a callsign.';
            return;
        }

        button.disabled = true;
        status.dataset.kind = 'pending';
        status.textContent = 'Sending to companion…';

        const result = await this._api.put('/api/config/dapnet/callsign', { label, callsign });

        if (result) {
            status.dataset.kind = 'success';
            status.textContent = `Callsign set to ${result.callsign}.`;
            this._api.toast('Callsign updated on the companion');
            input.value = '';
            await this._api.refresh();
        } else {
            status.dataset.kind = 'error';
            status.textContent = 'Save failed.';
        }
        button.disabled = false;
    }

    /** Editable web dashboard login password, set the same way as the
     * callsign (PUT /api/config/dapnet/web-password) -- but the value
     * is never cached/echoed anywhere on this side (unlike callsign,
     * there's no readout tile showing it, and the save response never
     * carries it back either). type="password" so it doesn't render in
     * plain text, and the field is cleared immediately after a send
     * (success or failure) rather than left sitting in the DOM. */
    _webPasswordEditHtml(live) {
        if (!live || !live.connected) return '';
        return `
            <div class="cfg-mc-identity" data-web-password-edit>
                <label class="cfg-field cfg-field--inline">
                    <span class="cfg-field__label">Set web dashboard password</span>
                    <input class="cfg-field__input" type="password"
                           autocomplete="new-password"
                           placeholder="New password"
                           data-web-password-input>
                </label>
                <div class="cfg-card__actions">
                    <button class="terminal-button terminal-button--primary"
                            type="button" data-web-password-save>
                        Set Password
                    </button>
                </div>
                <p class="cfg-status" data-web-password-status aria-live="polite"></p>
            </div>
        `;
    }

    async _saveWebPassword(deviceDiv, label) {
        const input = deviceDiv.querySelector('[data-web-password-input]');
        const status = deviceDiv.querySelector('[data-web-password-status]');
        const button = deviceDiv.querySelector('[data-web-password-save]');
        if (!input || !status) return;

        const password = input.value || '';
        input.value = ''; // never leave it sitting in the DOM, success or not
        if (!password) {
            status.dataset.kind = 'error';
            status.textContent = 'Enter a password.';
            return;
        }

        button.disabled = true;
        status.dataset.kind = 'pending';
        status.textContent = 'Sending to companion…';

        const result = await this._api.put('/api/config/dapnet/web-password', { label, password });

        if (result) {
            status.dataset.kind = 'success';
            status.textContent = 'Password updated on the companion.';
            this._api.toast('Web dashboard password updated');
        } else {
            status.dataset.kind = 'error';
            status.textContent = 'Save failed.';
        }
        button.disabled = false;
    }

    /** Resets callsign + web dashboard password back to defaults, over
     * the same serial connection (POST /api/config/dapnet/reset-
     * credentials) -- deliberately narrower than the companion's own
     * "Clear Settings" button, which also resets screen timeout; this
     * one only touches the two credentials, matching what was asked
     * for. Destructive enough to warrant a confirm() guard, same
     * pattern the companion's own web dashboard uses for its button. */
    _resetCredentialsHtml(live) {
        if (!live || !live.connected) return '';
        return `
            <div class="cfg-card__actions" data-reset-credentials-edit>
                <button class="terminal-button terminal-button--danger"
                        type="button" data-reset-credentials>
                    Reset Callsign &amp; Password
                </button>
            </div>
            <p class="cfg-status" data-reset-credentials-status aria-live="polite"></p>
        `;
    }

    async _resetCredentials(deviceDiv, label) {
        const status = deviceDiv.querySelector('[data-reset-credentials-status]');
        const button = deviceDiv.querySelector('[data-reset-credentials]');
        if (!status) return;

        const ok = await window.confirmModal({
            label: 'Reset callsign & password',
            description: 'Reset this companion\'s callsign and web dashboard password '
                + 'back to defaults? TX will be blocked again until a new callsign is set.',
        });
        if (!ok) return;

        button.disabled = true;
        status.dataset.kind = 'pending';
        status.textContent = 'Sending to companion…';

        const result = await this._api.post('/api/config/dapnet/reset-credentials', { label });

        if (result) {
            status.dataset.kind = 'success';
            status.textContent = 'Callsign and password reset to defaults.';
            this._api.toast('Companion credentials reset');
            await this._api.refresh();
        } else {
            status.dataset.kind = 'error';
            status.textContent = 'Reset failed.';
        }
        button.disabled = false;
    }

    /** WiFi SSID/password, deliberately its OWN separate control (not
     * folded into the callsign/password edit blocks above, and not the
     * reset button either) -- unlike everything else on this row, this
     * one takes the companion off its current network until it reboots
     * with the new credentials, so it gets its own explicit confirm
     * step plus a save-then-optionally-reboot flow rather than sharing
     * a button with lower-stakes actions. Password field cleared
     * immediately on send, success or not, same as the web password
     * control. */
    _wifiEditHtml(live) {
        if (!live || !live.connected) return '';
        return `
            <div class="cfg-mc-identity" data-wifi-edit>
                <label class="cfg-field cfg-field--inline">
                    <span class="cfg-field__label">WiFi SSID</span>
                    <input class="cfg-field__input" type="text"
                           placeholder="Network name"
                           data-wifi-ssid-input>
                </label>
                <label class="cfg-field cfg-field--inline">
                    <span class="cfg-field__label">WiFi password</span>
                    <input class="cfg-field__input" type="password"
                           autocomplete="new-password"
                           placeholder="Leave blank for an open network"
                           data-wifi-password-input>
                </label>
                <div class="cfg-card__actions">
                    <button class="terminal-button terminal-button--primary"
                            type="button" data-wifi-save>
                        Save WiFi Credentials
                    </button>
                </div>
                <p class="cfg-field__hint">
                    Takes effect on the companion's next reboot, not immediately --
                    it stays connected to its CURRENT WiFi (or none) until then.
                </p>
                <p class="cfg-status" data-wifi-status aria-live="polite"></p>
            </div>
        `;
    }

    async _saveWifi(deviceDiv, label) {
        const ssidInput = deviceDiv.querySelector('[data-wifi-ssid-input]');
        const passwordInput = deviceDiv.querySelector('[data-wifi-password-input]');
        const status = deviceDiv.querySelector('[data-wifi-status]');
        const button = deviceDiv.querySelector('[data-wifi-save]');
        if (!ssidInput || !status) return;

        const ssid = (ssidInput.value || '').trim();
        const password = passwordInput.value || '';
        passwordInput.value = ''; // never leave it sitting in the DOM, success or not
        if (!ssid) {
            status.dataset.kind = 'error';
            status.textContent = 'Enter an SSID.';
            return;
        }

        const ok = await window.confirmModal({
            label: 'Save new WiFi credentials',
            description: `Save "${ssid}" as this companion's WiFi network? It will `
                + 'stay on its CURRENT network (or offline) until you reboot it -- '
                + 'you\'ll be offered that as a next step.',
        });
        if (!ok) return;

        button.disabled = true;
        status.dataset.kind = 'pending';
        status.textContent = 'Sending to companion…';

        const result = await this._api.put('/api/config/dapnet/wifi', { label, ssid, password });

        if (result) {
            status.dataset.kind = 'success';
            status.textContent = `Saved. Reboot now to connect to "${result.ssid}"?`;
            ssidInput.value = '';
            button.disabled = false;
            const rebootNow = await window.confirmModal({
                label: 'Reboot companion now?',
                description: 'Apply the new WiFi credentials immediately? The companion '
                    + 'will restart -- POCSAG decode pauses briefly, and Meshpoint may need '
                    + 'a service restart afterward if its serial connection doesn\'t survive '
                    + 'the reboot.',
            });
            if (rebootNow) {
                await this._rebootCompanion(deviceDiv, label);
            }
        } else {
            status.dataset.kind = 'error';
            status.textContent = 'Save failed.';
            button.disabled = false;
        }
    }

    async _rebootCompanion(deviceDiv, label) {
        const status = deviceDiv.querySelector('[data-wifi-status]');
        const result = await this._api.post('/api/config/dapnet/reboot', { label });
        if (result) {
            status.dataset.kind = 'success';
            status.textContent = 'Rebooting…';
            this._api.toast('Companion rebooting with new WiFi credentials');
        } else {
            status.dataset.kind = 'error';
            status.textContent = 'Reboot command failed -- saved credentials will still '
                + 'apply next time it reboots some other way.';
        }
    }

    _fmtFreq(mhz) {
        const n = Number(mhz);
        if (!n || Number.isNaN(n)) return '--';
        return `${n.toFixed(4)} MHz`;
    }

    _fmtBoard(board) {
        const labels = { ttgo: 'TTGO LoRa32', heltec: 'Heltec V3' };
        return labels[board] || board || '--';
    }

    _fmtLastTx(live) {
        if (!live.tx_count) return 'Never';
        return live.last_tx_ok ? 'OK' : 'Failed';
    }

    /** uptime_ms wraps to a small number every ~49.7 days (ESP32
     * millis() overflow) -- a real device limitation, not a display
     * bug, if it ever shows a suspiciously small value on a
     * long-running companion. */
    _fmtUptime(ms) {
        const n = Number(ms);
        if (!Number.isFinite(n) || n < 0) return '--';
        const totalSec = Math.floor(n / 1000);
        const days = Math.floor(totalSec / 86400);
        const hours = Math.floor((totalSec % 86400) / 3600);
        const mins = Math.floor((totalSec % 3600) / 60);
        if (days > 0) return `${days}d ${hours}h`;
        if (hours > 0) return `${hours}h ${mins}m`;
        if (mins > 0) return `${mins}m`;
        return `${totalSec}s`;
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
