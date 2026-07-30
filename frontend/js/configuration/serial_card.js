/**
 * Configuration → Serial (Meshtastic USB) card.
 *
 * Edits the list of Meshtastic USB serial devices (T5 multi-stick
 * support) so adding a second stick (e.g. one on 433 MHz, one on 868
 * MHz) doesn't need hand-editing local.yaml. Each device row also gets
 * its own live readouts plus editable long/short name + "Send advert
 * after save" -- these sticks have no Bluetooth, so this is the only
 * way to rename them without a laptop and a USB cable running the
 * official Meshtastic app. Mirrors MeshcoreConfigCard's "USB capture
 * sources" card -- same shape, minus the auto-detect toggle:
 * SerialDeviceConfig has no such field, an empty serial port already
 * means "let meshtastic-python auto-detect".
 *
 * The second card, "Meshtastic firmware", drives
 * src/api/routes/meshtastic_firmware_routes.py -- repurposes a spare
 * ESP32 board (e.g. one previously running extra/pocsag_companion) into
 * a Meshtastic USB stick by downloading Meshtastic's own official
 * prebuilt release and writing it with esptool, no compiling involved
 * (Meshtastic firmware is PlatformIO-built upstream, unlike the
 * Arduino-sketch pocsag_companion). Board choice is a curated pulldown
 * (populated from GET .../targets -- not Meshtastic's whole ~130-board
 * catalog, just this project's hardware lineup); which device to flash
 * is only asked when more than one Serial companion is configured, same
 * pattern as the POCSAG firmware card. A confirm-modal guard exists
 * because this is destructive in a way Compile/Flash on the POCSAG card
 * isn't -- --erase-all wipes the board's ENTIRE flash, not just the app
 * partition, since it may currently hold a completely different
 * firmware's partition layout.
 */

class SerialConfigCard {
    constructor(api) {
        this._api = api;
        this._root = null;
    }

    _MAX_DEVICES = 4;

    mount(root) {
        this._root = root;
        this._root.innerHTML = `
            <div class="cfg-section" data-serial-root>
                <article class="cfg-card">
                    <header class="cfg-card__head">
                        <h3 class="cfg-card__title">USB capture sources</h3>
                        <p class="cfg-card__hint">
                            One entry per Meshtastic USB stick (Heltec V3, T-Beam, etc.).
                            Up to ${this._MAX_DEVICES}. Requires a service restart after changes.
                        </p>
                    </header>
                    <label class="cfg-field cfg-field--toggle">
                        <input type="checkbox" data-serial-enable>
                        <span class="cfg-field__label">Include serial capture source</span>
                    </label>
                    <div class="cfg-companions" data-serial-devices></div>
                    <datalist id="serial-ports-list"></datalist>
                    <div class="cfg-companions__add-row">
                        <button class="terminal-button" type="button" data-serial-add-device>
                            + Add device
                        </button>
                        <button class="terminal-button" type="button" data-serial-rescan-usb
                                title="Re-scan connected USB devices for the port picker below">
                            ↻ Rescan USB
                        </button>
                    </div>
                    <div class="cfg-card__actions">
                        <button class="terminal-button terminal-button--primary"
                                type="button" data-serial-save>
                            Save USB sources
                        </button>
                    </div>
                    <p class="cfg-status" data-serial-status aria-live="polite"></p>
                </article>

                <article class="cfg-card">
                    <header class="cfg-card__head">
                        <h3 class="cfg-card__title">Meshtastic firmware</h3>
                        <p class="cfg-card__hint">
                            Flash a spare board with official Meshtastic firmware straight from
                            this dashboard -- downloads the latest release and writes it with
                            esptool, no compiling needed. Erases the ENTIRE flash first, so this
                            also works on a board currently running something else entirely
                            (e.g. extra/pocsag_companion).
                        </p>
                    </header>
                    <label class="cfg-field cfg-field--narrow cfg-firmware-board-field">
                        <span class="cfg-field__label">Board</span>
                        <select class="cfg-field__input" data-mt-firmware-board></select>
                    </label>
                    <label class="cfg-field cfg-field--narrow" data-mt-firmware-device-wrap hidden>
                        <span class="cfg-field__label">Device to flash</span>
                        <select class="cfg-field__input" data-mt-firmware-device></select>
                    </label>
                    <div class="cfg-card__actions">
                        <button class="terminal-button terminal-button--primary"
                                type="button" data-mt-firmware-flash>
                            Flash
                        </button>
                        <button class="terminal-button" type="button" data-mt-firmware-toggle-output>
                            Show output
                        </button>
                    </div>
                    <pre class="cfg-firmware-output" data-mt-firmware-output hidden></pre>
                    <p class="cfg-status" data-mt-firmware-status aria-live="polite"></p>
                </article>
            </div>
        `;
        this._devicesEl = this._root.querySelector('[data-serial-devices]');

        this._root.querySelector('[data-serial-add-device]')
            .addEventListener('click', () => this._addDeviceRow());
        this._root.querySelector('[data-serial-save]')
            .addEventListener('click', () => this._saveDevices());
        this._root.querySelector('[data-serial-rescan-usb]')
            .addEventListener('click', (e) => this._rescanUsb(e.currentTarget));

        this._root.querySelector('[data-mt-firmware-flash]')
            .addEventListener('click', () => this._flashMeshtasticFirmware());
        this._root.querySelector('[data-mt-firmware-toggle-output]')
            .addEventListener('click', (e) => this._toggleMtFirmwareOutput(e.currentTarget));

        this._loadMtFirmwareTargets();
    }

    /** Board pulldown options for the Meshtastic firmware card, from the
     * curated list GET .../targets returns (see
     * meshtastic_firmware_routes.py's _CURATED_BOARDS) -- NOT
     * auto-discovered from a local file the way the POCSAG card's board
     * list is, since Meshtastic firmware isn't built from anything in
     * this repo. */
    async _loadMtFirmwareTargets() {
        const select = this._root.querySelector('[data-mt-firmware-board]');
        if (!select) return;
        const result = await this._api.get('/api/config/serial/firmware/targets');
        const boards = (result && Array.isArray(result.boards)) ? result.boards : [];
        select.innerHTML = boards.map((b) => (
            `<option value="${this._esc(b.board)}">${this._esc(b.label)}</option>`
        )).join('');
    }

    /** Manual re-scan for the port-picker datalist -- lets a user unplug
     * one device, plug in another, and immediately see it in the
     * dropdown without waiting for the next automatic dashboard poll or
     * reloading the page. */
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
        const devices = Array.isArray(cap.serial) ? cap.serial : [];
        const sources = cap.sources || [];
        // Top-level config.serial is the LIVE status array (one entry per
        // running SerialCaptureSource, keyed by `name` -- e.g. "serial_433"
        // or bare "serial" with no label) -- a completely different thing
        // from cap.serial (config.capture.serial) above despite the
        // similar path, matching the API's own existing naming.
        this._liveStatuses = Array.isArray(config.serial) ? config.serial : [];

        const enableEl = this._root.querySelector('[data-serial-enable]');
        if (enableEl) enableEl.checked = sources.includes('serial');

        this._devicesEl.innerHTML = '';
        const list = devices.length > 0
            ? devices
            : [{ label: '', serial_port: '', serial_baud: 115200 }];
        list.forEach((d) => this._addDeviceRow(d));
        this._syncAddBtn();
        this._renderMtFirmwareDevicePicker(devices);
    }

    /** Populates the "Device to flash" pulldown on the Meshtastic
     * firmware card from currently configured Serial devices -- only
     * shown when there's more than one (matches the same pattern on the
     * POCSAG firmware card: nothing to choose between otherwise). Keyed
     * on `label`, resolved server-side to a port -- never a raw path
     * trusted from the browser. */
    _renderMtFirmwareDevicePicker(devices) {
        const wrap = this._root.querySelector('[data-mt-firmware-device-wrap]');
        const select = this._root.querySelector('[data-mt-firmware-device]');
        const flashBtn = this._root.querySelector('[data-mt-firmware-flash]');
        if (!wrap || !select || !flashBtn) return;

        const configured = devices.filter((d) => d.serial_port);
        this._mtFirmwareDevices = configured;

        if (configured.length === 0) {
            wrap.hidden = true;
            flashBtn.disabled = true;
            flashBtn.title = 'No configured Serial device with a serial port to flash.';
            return;
        }

        flashBtn.disabled = false;
        flashBtn.title = '';
        wrap.hidden = configured.length <= 1;
        select.innerHTML = configured.map((d) => {
            const name = d.label || d.serial_port;
            return `<option value="${this._esc(d.label || '')}">${this._esc(name)}</option>`;
        }).join('');
    }

    _toggleMtFirmwareOutput(button) {
        const pre = this._root.querySelector('[data-mt-firmware-output]');
        if (!pre) return;
        pre.hidden = !pre.hidden;
        button.textContent = pre.hidden ? 'Show output' : 'Hide output';
    }

    _appendMtFirmwareOutput(text) {
        const pre = this._root.querySelector('[data-mt-firmware-output]');
        if (!pre || !text) return;
        pre.textContent = pre.textContent ? `${pre.textContent}\n${text}` : text;
        pre.scrollTop = pre.scrollHeight;
    }

    async _flashMeshtasticFirmware() {
        const boardSelect = this._root.querySelector('[data-mt-firmware-board]');
        const deviceSelect = this._root.querySelector('[data-mt-firmware-device]');
        const board = boardSelect?.value;
        if (!board) return;
        const boardLabel = boardSelect.options[boardSelect.selectedIndex]?.text || board;

        const devices = this._mtFirmwareDevices || [];
        const label = devices.length > 1 ? (deviceSelect?.value ?? '') : (devices[0]?.label || '');
        const device = devices.find((d) => (d.label || '') === label) || devices[0];
        if (!device) return;

        const ok = await window.confirmModal({
            label: 'Flash Meshtastic firmware',
            description: `Erase the ENTIRE flash on "${device.label || device.serial_port}" `
                + `(${device.serial_port}) and write official Meshtastic firmware for `
                + `${boardLabel}? This replaces whatever is currently on the board -- `
                + 'not reversible from here.',
        });
        if (!ok) return;

        const status = this._root.querySelector('[data-mt-firmware-status]');
        const flashBtn = this._root.querySelector('[data-mt-firmware-flash]');
        const outputPre = this._root.querySelector('[data-mt-firmware-output]');

        flashBtn.disabled = true;
        status.dataset.kind = 'pending';
        status.textContent = `Flashing ${device.label || device.serial_port}…`;
        if (outputPre) outputPre.textContent = '';
        this._appendMtFirmwareOutput(`# Flashing ${boardLabel} onto ${device.serial_port}…`);

        let finalResult = null;
        try {
            finalResult = await window.UpdateStreamClient.postNdjson(
                '/api/config/serial/firmware/flash/stream',
                { board, label },
                (event) => {
                    if (event.type === 'started' && Array.isArray(event.cmd)) {
                        this._appendMtFirmwareOutput(`$ ${event.cmd.join(' ')}`);
                    } else if (event.type === 'line') {
                        this._appendMtFirmwareOutput(event.text);
                    }
                },
            );
        } catch (err) {
            status.dataset.kind = 'error';
            status.textContent = `Request failed: ${err.message || err}`;
            this._appendMtFirmwareOutput(`! ${err.message || err}`);
            flashBtn.disabled = false;
            return;
        }

        const success = !!(finalResult && finalResult.success);
        status.dataset.kind = success ? 'success' : 'error';
        status.textContent = success
            ? 'Flashed.'
            : `Failed (exit code ${finalResult ? finalResult.returncode : '?'}). See output below.`;
        if (!success && outputPre) outputPre.hidden = false;
        const toggleBtn = this._root.querySelector('[data-mt-firmware-toggle-output]');
        if (toggleBtn && outputPre) {
            toggleBtn.textContent = outputPre.hidden ? 'Show output' : 'Hide output';
        }

        flashBtn.disabled = false;
        if (success) await this._api.refresh();
    }

    _liveStatusFor(label) {
        const name = label ? `serial_${label}` : 'serial';
        return (this._liveStatuses || []).find((s) => s.name === name) || null;
    }

    /** Maps every currently-configured serial_port value (across BOTH
     * Serial devices AND MeshCore companions -- the same physical USB
     * pool, so a port pinned by one protocol is just as "in use" from
     * the other's perspective) to a human label, for the "already used
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

    /** Populates the shared <datalist> so every "Serial port" input can
     * suggest currently-connected USB devices -- refreshed on every
     * render() (each dashboard poll) and via the "Rescan USB" button.
     * Shared with MeshcoreConfigCard's identical method/endpoint
     * (GET /api/config/serial-ports lists ALL USB-serial devices
     * regardless of protocol, since both cards pin from the same
     * physical pool). Any option already claimed by a configured
     * companion/device (matched across all 3 possible name forms: raw
     * device, by-id, by-path) gets an "already used by ..." suffix --
     * still selectable (no way to disable one <option> in a native
     * datalist, nor would we want to: the row showing its OWN
     * currently-pinned port will also see this label, which is
     * accurate, not a bug), just informative. Best-effort: silently
     * no-ops if the enumeration endpoint is unavailable, leaving the
     * field as a plain free-text input (the existing behavior). */
    async _refreshSerialPortsList() {
        const list = this._root.querySelector('#serial-ports-list');
        if (!list) return;
        const result = await this._api.get('/api/config/serial-ports');
        const ports = (result && Array.isArray(result.ports)) ? result.ports : [];
        this._enumeratedPorts = ports;
        const usage = this._portUsage || {};
        list.innerHTML = ports.map((p) => `
            <option value="${this._esc(p.stable_path)}" label="${this._esc(this._portOptionLabel(p, usage))}"></option>
        `).join('');
        // Ports arrive asynchronously, after rows may have already been
        // built with no enumeration data yet -- refresh every row's
        // "resolved to ttyUSBn" hint now that it's available.
        this._devicesEl.querySelectorAll('[data-device-port]').forEach((input) => {
            this._updateResolvedPort(input);
        });
    }

    /** A pinned by-path/by-id value is long and not something a user can
     * eyeball as "which physical ttyUSBn is that" -- shows the
     * underlying /dev/ttyUSBn next to the field once it's resolvable
     * (matched against the enumerated ports' stable_path/by_id/by_path/
     * device, whichever form the pinned value happens to be in), and
     * clears it when the value doesn't currently resolve to anything
     * connected (nothing to show, not a stale/wrong hint). */
    _updateResolvedPort(input) {
        const resolvedEl = input.parentElement.querySelector('[data-device-port-resolved]');
        if (!resolvedEl) return;
        const value = (input.value || '').trim();
        const match = value && (this._enumeratedPorts || []).find((p) =>
            p.stable_path === value || p.by_id === value || p.by_path === value || p.device === value,
        );
        resolvedEl.textContent = (match && match.device && match.device !== value) ? `→ ${match.device}` : '';
    }

    /** Native <datalist> popups truncate long labels with no CSS control
     * over wrapping/width -- the important "used by ..." warning was
     * getting cut off entirely when it came after a full USB descriptor
     * string like "Silicon Labs CP2102 USB to UART Bridge Controller".
     * Puts the short/critical bits first and drops the boilerplate
     * "Silicon Labs .../USB to UART Bridge Controller" wording that's
     * identical (and uninformative) across every CP210x device anyway. */
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
                           placeholder="e.g. 433 or 868"
                           value="${label}" data-device-label>
                </label>
                <button class="cfg-companion__remove terminal-button terminal-button--danger"
                        type="button" title="Remove device">✕</button>
            </div>
            <label class="cfg-field">
                <span class="cfg-field__label">Serial port</span>
                <input class="cfg-field__input" type="text"
                       placeholder="/dev/ttyUSB0 (blank = auto-detect)" value="${port}"
                       list="serial-ports-list"
                       data-device-port>
                <span class="cfg-field__resolved" data-device-port-resolved></span>
                <span class="cfg-field__hint">
                    Pick a connected device below, or type a path. Prefer the
                    /dev/serial/by-path/... entries over plain /dev/ttyUSBn --
                    those stay stable across reboots/replugs even when two
                    boards share an identical USB serial number.
                </span>
            </label>
            <label class="cfg-field cfg-field--narrow">
                <span class="cfg-field__label">Baud rate</span>
                <input class="cfg-field__input" type="number"
                       value="${baud}" data-device-baud>
            </label>
            ${this._identityHtml(data, live)}
            ${this._radioControlsHtml(live)}
            ${this._readoutsHtml(live)}
        `;

        div.querySelector('.cfg-companion__remove').addEventListener('click', () => {
            div.remove();
            this._reindexDevices();
            this._syncAddBtn();
        });

        const firmwareCheck = div.querySelector('[data-serial-firmware-check]');
        if (firmwareCheck) {
            firmwareCheck.addEventListener('click', () => {
                this._checkFirmwareUpdate(div, live.firmware_version);
            });
        }

        const saveNameBtn = div.querySelector('[data-device-name-save]');
        if (saveNameBtn) {
            saveNameBtn.addEventListener('click', () => {
                this._saveDeviceIdentity(div, data.label || '');
            });
        }

        const saveRegionBtn = div.querySelector('[data-device-region-save]');
        if (saveRegionBtn) {
            saveRegionBtn.addEventListener('click', () => {
                this._saveDeviceRegion(div, data.label || '');
            });
        }

        const savePresetBtn = div.querySelector('[data-device-preset-save]');
        if (savePresetBtn) {
            savePresetBtn.addEventListener('click', () => {
                this._saveDeviceModemPreset(div, data.label || '');
            });
        }

        const saveIntervalsBtn = div.querySelector('[data-device-intervals-save]');
        if (saveIntervalsBtn) {
            saveIntervalsBtn.addEventListener('click', () => {
                this._saveDeviceBroadcastIntervals(div, data.label || '');
            });
        }

        const saveBtBtn = div.querySelector('[data-device-bt-save]');
        if (saveBtBtn) {
            saveBtBtn.addEventListener('click', () => {
                this._saveDeviceBluetooth(div, data.label || '');
            });
        }

        const btEnabledEl = div.querySelector('[data-device-bt-enabled]');
        const btModeWrap = div.querySelector('[data-device-bt-mode-wrap]');
        const btModeEl = div.querySelector('[data-device-bt-mode]');
        const btPinWrap = div.querySelector('[data-device-bt-pin-wrap]');
        const syncBtVisibility = () => {
            if (btModeWrap) btModeWrap.hidden = !btEnabledEl?.checked;
            if (btPinWrap) {
                btPinWrap.hidden = !(btEnabledEl?.checked && btModeEl?.value === 'FIXED_PIN');
            }
        };
        if (btEnabledEl) btEnabledEl.addEventListener('change', syncBtVisibility);
        if (btModeEl) btModeEl.addEventListener('change', syncBtVisibility);

        this._wireRadioControls(div, live);

        const portInput = div.querySelector('[data-device-port]');
        if (portInput) {
            portInput.addEventListener('input', () => this._updateResolvedPort(portInput));
            this._updateResolvedPort(portInput);
        }

        this._devicesEl.appendChild(div);
        this._syncAddBtn();
    }

    /** Every Config.LoRaConfig.RegionCode value except UNSET (0) --
     * that one's Meshtastic's own factory-default "not configured yet"
     * state, not something you'd deliberately pick from this dropdown.
     * Straight from meshtastic/protobufs' config.proto, not a curated
     * subset like the Meshtastic-firmware-flash board list -- this is a
     * small, genuinely complete enum, not a sprawling hardware catalog. */
    static _REGION_CODES = [
        'US', 'EU_433', 'EU_868', 'CN', 'JP', 'ANZ', 'KR', 'TW', 'RU', 'IN',
        'NZ_865', 'TH', 'LORA_24', 'UA_433', 'MY_433', 'MY_919', 'SG_923',
        'PH_433', 'PH_868', 'PH_915', 'ANZ_433', 'KZ_433', 'KZ_863', 'NP_865',
        'BR_902', 'ITU1_2M', 'ITU2_2M', 'EU_866', 'EU_874', 'EU_917', 'EU_N_868',
        'ITU3_2M', 'ITU1_70CM', 'ITU2_70CM', 'ITU3_70CM', 'ITU2_125CM',
    ];

    /** Named ModemPreset values this control exposes -- matches the
     * same preset list Configuration -> Radio's own concentrator page
     * shows (LongFast/LongTurbo/.../ShortTurbo), not the full modern
     * Meshtastic enum (which also has Lite/Narrow/Tiny/MediumTurbo
     * variants not offered there either). "Custom" is deliberately not
     * included -- that's a fully custom spread-factor/bandwidth/coding-
     * rate config, not a named preset, and isn't exposed from here. */
    static _MODEM_PRESETS = [
        { value: 'LONG_FAST', label: 'LongFast' },
        { value: 'LONG_TURBO', label: 'LongTurbo' },
        { value: 'LONG_MODERATE', label: 'LongModerate' },
        { value: 'LONG_SLOW', label: 'LongSlow' },
        { value: 'VERY_LONG_SLOW', label: 'VeryLongSlow' },
        { value: 'MEDIUM_FAST', label: 'MediumFast' },
        { value: 'MEDIUM_SLOW', label: 'MediumSlow' },
        { value: 'SHORT_FAST', label: 'ShortFast' },
        { value: 'SHORT_SLOW', label: 'ShortSlow' },
        { value: 'SHORT_TURBO', label: 'ShortTurbo' },
    ];

    /** Same preset-minutes list as NodeInfoConfigCard/TelemetryBroadcastCard
     * (Configuration -> Radio's own broadcast-interval cards) -- reused
     * verbatim so a device row's chip-row looks and behaves identically
     * to those, not a different-looking control for the same idea. */
    static _INTERVAL_PRESETS = [
        { minutes: 0, label: 'Off', off: true },
        { minutes: 5, label: '5m' },
        { minutes: 30, label: '30m' },
        { minutes: 60, label: '1h' },
        { minutes: 180, label: '3h' },
        { minutes: 360, label: '6h' },
        { minutes: 720, label: '12h' },
        { minutes: 1440, label: '24h' },
    ];

    /** This stick's radio/security config -- LoRa region, modem preset
     * (chip row), NodeInfo/telemetry broadcast intervals (chip row +
     * custom-minutes fallback, exactly the same pattern Configuration ->
     * Radio's own NodeInfoConfigCard/TelemetryBroadcastCard use), and
     * Bluetooth. Deliberately rendered as PLAIN .cfg-field elements with
     * no extra bordered wrapper (earlier draft nested these in their own
     * `.cfg-mc-identity` box(es), which looked inconsistent with every
     * other settings page in the app -- .cfg-companion itself already
     * provides the one border a device row needs). Always shown when
     * connected (not just while unconfigured), so this also serves as a
     * way to change any of these later. None of these persist to
     * local.yaml -- all live durably in the device's own NVS, and
     * re-applying them to a swapped-in blank replacement is a much
     * rarer need than re-applying the name (which does persist, see
     * _identityHtml). */
    _radioControlsHtml(live) {
        if (!live || !live.connected) return '';
        const region = live.region && live.region !== 'UNSET' ? live.region : '';
        const regionOptions = SerialConfigCard._REGION_CODES.map((r) => (
            `<option value="${r}" ${r === region ? 'selected' : ''}>${r.replace(/_/g, ' ')}</option>`
        )).join('');

        const btEnabled = live.bluetooth_enabled !== false; // default checked if unknown
        const btMode = live.bluetooth_mode || 'RANDOM_PIN';
        const btModeOptions = [
            ['RANDOM_PIN', 'Random PIN (shown on device)'],
            ['FIXED_PIN', 'Fixed PIN (set your own)'],
            ['NO_PIN', 'No PIN'],
        ].map(([value, label]) => (
            `<option value="${value}" ${value === btMode ? 'selected' : ''}>${label}</option>`
        )).join('');

        return `
            <label class="cfg-field cfg-field--narrow">
                <span class="cfg-field__label">LoRa region</span>
                <select class="cfg-field__input" data-device-region-input>
                    <option value="" disabled ${region ? '' : 'selected'}>-- select --</option>
                    ${regionOptions}
                </select>
            </label>
            ${live.region === 'UNSET' ? `
                <p class="cfg-field__hint">
                    Region is UNSET -- this stick will not transmit at all until
                    a region is set (Meshtastic's factory default on a fresh flash).
                </p>
            ` : ''}
            <div class="cfg-card__actions">
                <button class="terminal-button terminal-button--primary"
                        type="button" data-device-region-save>
                    Set Region
                </button>
            </div>
            <p class="cfg-status" data-device-region-status aria-live="polite"></p>

            <div class="cfg-field">
                <span class="cfg-field__label">Modem preset</span>
                <div class="cfg-chip-row" data-device-preset-chips></div>
            </div>
            <div class="cfg-card__actions">
                <button class="terminal-button terminal-button--primary"
                        type="button" data-device-preset-save>
                    Set Preset
                </button>
            </div>
            <p class="cfg-status" data-device-preset-status aria-live="polite"></p>

            <div class="cfg-field">
                <span class="cfg-field__label">NodeInfo broadcast interval</span>
                <div class="cfg-chip-row" data-device-ni-chips></div>
            </div>
            <label class="cfg-field cfg-field--narrow">
                <span class="cfg-field__label">Custom (minutes)</span>
                <input class="cfg-field__input" type="number" min="0" max="1440"
                       data-device-ni-input>
            </label>

            <div class="cfg-field">
                <span class="cfg-field__label">Telemetry broadcast interval</span>
                <div class="cfg-chip-row" data-device-tel-chips></div>
            </div>
            <label class="cfg-field cfg-field--narrow">
                <span class="cfg-field__label">Custom (minutes)</span>
                <input class="cfg-field__input" type="number" min="0" max="1440"
                       data-device-tel-input>
            </label>
            <div class="cfg-card__actions">
                <button class="terminal-button terminal-button--primary"
                        type="button" data-device-intervals-save>
                    Set Intervals
                </button>
            </div>
            <p class="cfg-status" data-device-intervals-status aria-live="polite"></p>

            <label class="cfg-field cfg-field--toggle">
                <input type="checkbox" data-device-bt-enabled ${btEnabled ? 'checked' : ''}>
                <span class="cfg-field__label">Bluetooth enabled</span>
            </label>
            <label class="cfg-field cfg-field--narrow"
                   data-device-bt-mode-wrap ${btEnabled ? '' : 'hidden'}>
                <span class="cfg-field__label">Pairing mode</span>
                <select class="cfg-field__input" data-device-bt-mode>
                    ${btModeOptions}
                </select>
            </label>
            <label class="cfg-field cfg-field--narrow"
                   data-device-bt-pin-wrap ${(btEnabled && btMode === 'FIXED_PIN') ? '' : 'hidden'}>
                <span class="cfg-field__label">Fixed PIN</span>
                <input class="cfg-field__input" type="number" min="0" max="999999"
                       placeholder="e.g. 123456" data-device-bt-pin>
            </label>
            <div class="cfg-card__actions">
                <button class="terminal-button terminal-button--primary"
                        type="button" data-device-bt-save>
                    Set Bluetooth
                </button>
            </div>
            <p class="cfg-status" data-device-bt-status aria-live="polite"></p>
        `;
    }

    /** Wires up the modem-preset and both interval chip-rows for one
     * device row -- called once per row from _addDeviceRow, mirroring
     * NodeInfoConfigCard's own _renderChips/_setActiveChip pattern
     * (click a chip -> highlight it + populate the paired custom-minutes
     * input; typing in the custom input directly highlights a matching
     * chip if any, clears selection otherwise). */
    _wireRadioControls(div, live) {
        const presetChips = div.querySelector('[data-device-preset-chips]');
        if (presetChips) {
            presetChips.innerHTML = SerialConfigCard._MODEM_PRESETS.map((p) => (
                `<button type="button" class="cfg-chip" data-preset="${p.value}">${p.label}</button>`
            )).join('');
            const current = live?.modem_preset;
            presetChips.querySelectorAll('[data-preset]').forEach((chip) => {
                chip.classList.toggle('cfg-chip--selected', chip.dataset.preset === current);
                chip.addEventListener('click', () => {
                    presetChips.querySelectorAll('[data-preset]').forEach((c) => (
                        c.classList.toggle('cfg-chip--selected', c === chip)
                    ));
                });
            });
        }

        this._wireIntervalChips(
            div, '[data-device-ni-chips]', '[data-device-ni-input]',
            live?.node_info_broadcast_secs,
        );
        this._wireIntervalChips(
            div, '[data-device-tel-chips]', '[data-device-tel-input]',
            live?.telemetry_device_update_interval,
        );
    }

    _wireIntervalChips(div, chipsSelector, inputSelector, currentSecs) {
        const chipsEl = div.querySelector(chipsSelector);
        const inputEl = div.querySelector(inputSelector);
        if (!chipsEl || !inputEl) return;

        chipsEl.innerHTML = SerialConfigCard._INTERVAL_PRESETS.map((p) => {
            const offCls = p.off ? ' cfg-chip--off' : '';
            return `<button type="button" class="cfg-chip${offCls}"
                    data-minutes="${p.minutes}">${p.label}</button>`;
        }).join('');

        const currentMinutes = currentSecs != null ? Math.round(currentSecs / 60) : null;
        inputEl.value = currentMinutes != null ? String(currentMinutes) : '';

        const setActive = (minutes) => {
            chipsEl.querySelectorAll('[data-minutes]').forEach((chip) => {
                chip.classList.toggle(
                    'cfg-chip--selected', parseInt(chip.dataset.minutes, 10) === minutes,
                );
            });
        };
        setActive(currentMinutes);

        chipsEl.querySelectorAll('[data-minutes]').forEach((chip) => {
            chip.addEventListener('click', () => {
                const minutes = parseInt(chip.dataset.minutes, 10);
                inputEl.value = String(minutes);
                setActive(minutes);
            });
        });
        inputEl.addEventListener('input', () => {
            const minutes = parseInt(inputEl.value, 10);
            setActive(isNaN(minutes) ? null : minutes);
        });
    }

    async _saveDeviceRegion(deviceDiv, label) {
        const input = deviceDiv.querySelector('[data-device-region-input]');
        const status = deviceDiv.querySelector('[data-device-region-status]');
        const button = deviceDiv.querySelector('[data-device-region-save]');
        if (!input || !status) return;

        const region = input.value;
        if (!region) {
            status.dataset.kind = 'error';
            status.textContent = 'Pick a region.';
            return;
        }

        button.disabled = true;
        status.dataset.kind = 'pending';
        status.textContent = 'Setting region…';

        const result = await this._api.put('/api/config/serial/region', { label, region });

        if (result) {
            status.dataset.kind = 'success';
            status.textContent = `Region set to ${result.region}.`;
            this._api.toast('LoRa region updated');
            await this._api.refresh();
        } else {
            status.dataset.kind = 'error';
            status.textContent = 'Save failed.';
        }
        button.disabled = false;
    }

    async _saveDeviceModemPreset(deviceDiv, label) {
        const chipsEl = deviceDiv.querySelector('[data-device-preset-chips]');
        const status = deviceDiv.querySelector('[data-device-preset-status]');
        const button = deviceDiv.querySelector('[data-device-preset-save]');
        if (!chipsEl || !status) return;

        const selected = chipsEl.querySelector('.cfg-chip--selected');
        if (!selected) {
            status.dataset.kind = 'error';
            status.textContent = 'Pick a preset.';
            return;
        }

        button.disabled = true;
        status.dataset.kind = 'pending';
        status.textContent = 'Setting modem preset…';

        const result = await this._api.put('/api/config/serial/modem-preset', {
            label, modem_preset: selected.dataset.preset,
        });

        if (result) {
            status.dataset.kind = 'success';
            status.textContent = `Preset set to ${result.modem_preset}.`;
            this._api.toast('Modem preset updated');
            await this._api.refresh();
        } else {
            status.dataset.kind = 'error';
            status.textContent = 'Save failed.';
        }
        button.disabled = false;
    }

    async _saveDeviceBluetooth(deviceDiv, label) {
        const enabledEl = deviceDiv.querySelector('[data-device-bt-enabled]');
        const modeEl = deviceDiv.querySelector('[data-device-bt-mode]');
        const pinEl = deviceDiv.querySelector('[data-device-bt-pin]');
        const status = deviceDiv.querySelector('[data-device-bt-status]');
        const button = deviceDiv.querySelector('[data-device-bt-save]');
        if (!enabledEl || !status) return;

        const enabled = enabledEl.checked;
        const mode = enabled ? modeEl?.value : null;
        let fixedPin = null;
        if (enabled && mode === 'FIXED_PIN') {
            const pinValue = (pinEl?.value || '').trim();
            if (!pinValue) {
                status.dataset.kind = 'error';
                status.textContent = 'Enter a PIN.';
                return;
            }
            fixedPin = Number(pinValue);
        }

        button.disabled = true;
        status.dataset.kind = 'pending';
        status.textContent = 'Setting Bluetooth…';

        const result = await this._api.put('/api/config/serial/bluetooth', {
            label, enabled, mode, fixed_pin: fixedPin,
        });

        if (result) {
            status.dataset.kind = 'success';
            status.textContent = enabled ? 'Bluetooth updated.' : 'Bluetooth disabled.';
            this._api.toast('Bluetooth config updated');
            await this._api.refresh();
        } else {
            status.dataset.kind = 'error';
            status.textContent = 'Save failed.';
        }
        button.disabled = false;
    }

    async _saveDeviceBroadcastIntervals(deviceDiv, label) {
        const nodeInfoEl = deviceDiv.querySelector('[data-device-ni-input]');
        const telemetryEl = deviceDiv.querySelector('[data-device-tel-input]');
        const status = deviceDiv.querySelector('[data-device-intervals-status]');
        const button = deviceDiv.querySelector('[data-device-intervals-save]');
        if (!status) return;

        const nodeInfoMin = (nodeInfoEl?.value || '').trim();
        const telemetryMin = (telemetryEl?.value || '').trim();
        if (!nodeInfoMin && !telemetryMin) {
            status.dataset.kind = 'error';
            status.textContent = 'Enter at least one interval.';
            return;
        }

        button.disabled = true;
        status.dataset.kind = 'pending';
        status.textContent = 'Setting intervals…';

        const result = await this._api.put('/api/config/serial/broadcast-intervals', {
            label,
            node_info_broadcast_secs: nodeInfoMin ? Number(nodeInfoMin) * 60 : null,
            telemetry_device_update_interval: telemetryMin ? Number(telemetryMin) * 60 : null,
        });

        if (result) {
            status.dataset.kind = 'success';
            status.textContent = 'Intervals updated.';
            this._api.toast('Broadcast intervals updated');
            await this._api.refresh();
        } else {
            status.dataset.kind = 'error';
            status.textContent = 'Save failed.';
        }
        button.disabled = false;
    }

    _identityHtml(data, live) {
        const longValue = this._esc(data.long_name || (live && live.long_name) || '');
        const shortValue = this._esc(data.short_name || (live && live.short_name) || '');
        return `
            <div class="cfg-mc-identity" data-device-identity>
                <label class="cfg-field">
                    <span class="cfg-field__label">Long name</span>
                    <input class="cfg-field__input" type="text"
                           data-device-long-name maxlength="36"
                           value="${longValue}"
                           placeholder="My Meshpoint 433">
                </label>
                <label class="cfg-field">
                    <span class="cfg-field__label">Short name</span>
                    <input class="cfg-field__input" type="text"
                           data-device-short-name maxlength="4"
                           value="${shortValue}"
                           placeholder="M433">
                </label>
                <label class="cfg-field cfg-field--toggle">
                    <input type="checkbox" data-device-advert checked>
                    <span class="cfg-field__label">
                        Send advert after save
                    </span>
                </label>
                <div class="cfg-card__actions">
                    <button class="terminal-button terminal-button--primary"
                            type="button" data-device-name-save>
                        Save Name
                    </button>
                </div>
                <p class="cfg-status" data-device-name-status aria-live="polite"></p>
            </div>
        `;
    }

    async _saveDeviceIdentity(deviceDiv, label) {
        const longInput = deviceDiv.querySelector('[data-device-long-name]');
        const shortInput = deviceDiv.querySelector('[data-device-short-name]');
        const advertEl = deviceDiv.querySelector('[data-device-advert]');
        const status = deviceDiv.querySelector('[data-device-name-status]');
        const button = deviceDiv.querySelector('[data-device-name-save]');
        if (!longInput || !shortInput || !status) return;

        const longValue = (longInput.value || '').trim();
        const shortValue = (shortInput.value || '').trim();
        if (!longValue && !shortValue) {
            status.dataset.kind = 'error';
            status.textContent = 'Enter a long name or short name.';
            return;
        }

        button.disabled = true;
        status.dataset.kind = 'pending';
        status.textContent = 'Renaming device…';

        // null (not empty string) for a blank field -- matches the
        // backend's set_owner() "None means leave unchanged" semantics,
        // so renaming just the long name doesn't force retyping short.
        const result = await this._api.put('/api/config/serial/identity', {
            label,
            long_name: longValue || null,
            short_name: shortValue || null,
        });

        if (!result) {
            status.dataset.kind = 'error';
            status.textContent = 'Save failed.';
            button.disabled = false;
            return;
        }

        status.dataset.kind = 'success';
        status.textContent = 'Renamed.';
        this._api.toast('Device renamed');

        if (advertEl && advertEl.checked) {
            try {
                const advertRes = await this._api.post('/api/config/serial/advert', { label });
                if (advertRes && advertRes.success) {
                    this._api.toast('Advert sent');
                } else if (advertRes) {
                    this._api.toast(
                        'Advert failed' + (advertRes.error ? `: ${advertRes.error}` : ''),
                    );
                }
            } catch (_e) {
                // Rename already applied live; advert failure is a soft error.
            }
        }

        await this._api.refresh();
        button.disabled = false;
    }

    async _checkFirmwareUpdate(deviceDiv, currentVersion) {
        const button = deviceDiv.querySelector('[data-serial-firmware-check]');
        const status = deviceDiv.querySelector('[data-serial-firmware-status]');
        if (!button || !status || !currentVersion) return;
        button.disabled = true;
        status.dataset.kind = '';
        status.textContent = 'Checking…';
        try {
            const result = await this._api.get(
                `/api/config/serial/firmware-check?current_version=${encodeURIComponent(currentVersion)}`,
            );
            if (!result) {
                status.dataset.kind = 'error';
                status.textContent = 'Check failed';
            } else if (result.error) {
                status.dataset.kind = 'error';
                status.textContent = result.error;
            } else if (result.update_available) {
                status.dataset.kind = 'warn';
                // release_url always comes from GitHub's own API response, not
                // user input -- but only allow http(s) schemes defensively,
                // since HTML-escaping the text doesn't stop a javascript: URI
                // from executing when the link is clicked.
                const isSafeUrl = typeof result.release_url === 'string'
                    && /^https?:\/\//i.test(result.release_url);
                const link = isSafeUrl
                    ? ` — <a href="${this._esc(result.release_url)}" target="_blank" rel="noopener">release notes</a>`
                    : '';
                status.innerHTML = `Update available: ${this._esc(result.latest_version || '?')}${link}`;
            } else {
                status.dataset.kind = 'ok';
                status.textContent = 'Up to date';
            }
        } finally {
            button.disabled = false;
        }
    }

    _reindexDevices() {
        this._devicesEl.querySelectorAll('.cfg-companion').forEach((el, i) => {
            el.dataset.deviceIdx = i;
            const num = el.querySelector('.cfg-companion__num');
            if (num) num.textContent = `Device ${i + 1}`;
        });
    }

    _syncAddBtn() {
        const btn = this._root.querySelector('[data-serial-add-device]');
        if (!btn) return;
        const count = this._devicesEl.children.length;
        btn.disabled = count >= this._MAX_DEVICES;
        btn.title = count >= this._MAX_DEVICES
            ? `Maximum ${this._MAX_DEVICES} devices`
            : '';
    }

    async _saveDevices() {
        const status = this._root.querySelector('[data-serial-status]');
        status.dataset.kind = 'pending';
        status.textContent = 'Saving…';

        const devices = [];
        this._devicesEl.querySelectorAll('.cfg-companion').forEach((div) => {
            devices.push({
                label: (div.querySelector('[data-device-label]')?.value || '').trim(),
                serial_port: (div.querySelector('[data-device-port]')?.value || '').trim() || null,
                serial_baud: Number(div.querySelector('[data-device-baud]')?.value) || 115200,
            });
        });

        const result = await this._api.put('/api/config/capture/serial-devices', {
            enable_source: this._root.querySelector('[data-serial-enable]').checked,
            devices,
        });

        if (result) {
            status.dataset.kind = 'success';
            status.textContent = 'Saved.';
            this._api.signalRestart('Serial USB devices updated.');
            await this._api.refresh();
        } else {
            status.dataset.kind = 'error';
            status.textContent = 'Save failed.';
        }
    }

    _readoutsHtml(live) {
        if (!live || !live.connected) {
            return `<p class="cfg-companion__offline-hint">Not connected.</p>`;
        }
        const nodeId = live.own_node_id_hex ? `!${live.own_node_id_hex}` : '--';
        const name = live.long_name || live.short_name || '--';
        const sf = live.spreading_factor ? `SF${live.spreading_factor}` : '--';
        const bw = live.bandwidth_khz ? `${live.bandwidth_khz} kHz` : '--';
        const freq = live.frequency_mhz ? `${live.frequency_mhz} MHz` : '--';
        const txPower = (live.tx_power || live.tx_power === 0) ? `${live.tx_power} dBm` : '--';
        return `
            <div class="cfg-mc-readouts">
                <div class="cfg-mc-readout">
                    <span class="cfg-mc-readout__label">Node ID</span>
                    <span class="cfg-mc-readout__value">${this._esc(nodeId)}</span>
                </div>
                <div class="cfg-mc-readout">
                    <span class="cfg-mc-readout__label">Name</span>
                    <span class="cfg-mc-readout__value">${this._esc(name)}</span>
                </div>
                <div class="cfg-mc-readout">
                    <span class="cfg-mc-readout__label">Frequency</span>
                    <span class="cfg-mc-readout__value">${this._esc(freq)}</span>
                </div>
                <div class="cfg-mc-readout">
                    <span class="cfg-mc-readout__label">Region</span>
                    <span class="cfg-mc-readout__value">${this._esc(live.region || '--')}</span>
                </div>
                <div class="cfg-mc-readout">
                    <span class="cfg-mc-readout__label">SF</span>
                    <span class="cfg-mc-readout__value">${sf}</span>
                </div>
                <div class="cfg-mc-readout">
                    <span class="cfg-mc-readout__label">Bandwidth</span>
                    <span class="cfg-mc-readout__value">${bw}</span>
                </div>
                <div class="cfg-mc-readout">
                    <span class="cfg-mc-readout__label">TX Power</span>
                    <span class="cfg-mc-readout__value">${this._esc(txPower)}</span>
                </div>
                <div class="cfg-mc-readout" data-firmware-readout>
                    <span class="cfg-mc-readout__label">Firmware</span>
                    <span class="cfg-mc-readout__value">${this._esc(live.firmware_version || '--')}</span>
                    ${live.firmware_version ? `
                        <button class="cfg-mc-readout__check" type="button" data-serial-firmware-check>
                            Check for updates
                        </button>
                        <span class="cfg-mc-readout__update-status" data-serial-firmware-status></span>
                    ` : ''}
                </div>
                <div class="cfg-mc-readout">
                    <span class="cfg-mc-readout__label">Hardware</span>
                    <span class="cfg-mc-readout__value">${this._esc(this._fmtHwModel(live.hw_model))}</span>
                </div>
            </div>
        `;
    }

    _fmtHwModel(v) {
        if (!v) return '--';
        return v.split('_')
            .map((w) => (w.length <= 2 ? w : w[0] + w.slice(1).toLowerCase()))
            .join(' ');
    }

    _esc(str) {
        const el = document.createElement('span');
        el.textContent = str || '';
        return el.innerHTML;
    }
}

window.SerialConfigCard = SerialConfigCard;
