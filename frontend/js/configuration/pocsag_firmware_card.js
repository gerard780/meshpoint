/**
 * Configuration → Firmware page: POCSAG companion card.
 *
 * Third card on the shared Firmware page (order: Meshtastic, MeshCore,
 * POCSAG) -- moved out of Configuration → POCSAG for the same reason
 * the other two were: flashing reads as its own action, not settings
 * for an already-assigned companion. Drives
 * src/api/routes/pocsag_firmware_routes.py's compile/flash-stream
 * endpoints.
 *
 * Genuinely different mechanism from the MeshCore/Meshtastic cards, so
 * this is a straight move, not a re-shape to match their shape: this
 * one COMPILES extra/pocsag_companion from source via arduino-cli
 * (that's this project's own sketch, not an external release), so
 * there's no GitHub release/version concept, no flavor, and Compile is
 * a separate step from Flash. Board list is auto-discovered from the
 * sketch's own BOARD_* #define lines (GET .../targets), not a curated
 * list or a manifest.
 *
 * Device-to-flash now matches the other two cards' shape: the picker
 * lists every currently-enumerated USB-serial device (GET
 * /api/config/serial-ports), not just already-configured POCSAG
 * companions, with a "↻ Rescan USB" button for one plugged in after
 * landing on this page. Previously this defaulted straight to the
 * sole configured companion whenever there was only one -- meaning
 * "Flash" silently targeted whatever board was already deployed unless
 * the user noticed and switched it, exactly the footgun the other two
 * cards' any-device pickers were built to avoid.
 */

class PocsagFirmwareConfigCard {
    constructor(api) {
        this._api = api;
        this._root = null;
        this._enumeratedPorts = [];
        this._portUsage = {};
        this._configuredDevices = [];
    }

    mount(root) {
        this._root = root;
        this._root.innerHTML = `
            <div class="cfg-section" data-pocsag-firmware-root>
                <article class="cfg-card">
                    <header class="cfg-card__head">
                        <h3 class="cfg-card__title">Pocsag (DAPNET) Companion firmware</h3>
                        <p class="cfg-card__hint">
                            Build and flash extra/pocsag_companion straight from this
                            dashboard -- no Arduino IDE needed. Requires the arduino-cli
                            toolchain (installed automatically by scripts/install.sh).
                        </p>
                        <p class="cfg-status" data-kind="error" data-firmware-cli-warning hidden>
                            arduino-cli isn't installed on this Pi, so Compile/Flash won't
                            work yet -- re-run <code>scripts/install.sh</code> (without
                            <code>--skip-arduino</code>) to add it, then reload this page.
                        </p>
                    </header>
                    <label class="cfg-field cfg-field--narrow">
                        <span class="cfg-field__label">Board</span>
                        <select class="cfg-field__input" data-firmware-board></select>
                    </label>
                    <label class="cfg-field cfg-firmware-field cfg-firmware-board-field">
                        <span class="cfg-field__label">Device to flash</span>
                        <select class="cfg-field__input" data-firmware-device></select>
                        <button class="terminal-button cfg-firmware-rescan" type="button" data-firmware-rescan-usb
                                title="Re-scan connected USB devices">
                            ↻ Rescan USB
                        </button>
                    </label>
                    <div class="cfg-card__actions">
                        <button class="terminal-button" type="button" data-firmware-compile>
                            Compile
                        </button>
                        <button class="terminal-button terminal-button--primary"
                                type="button" data-firmware-flash>
                            Flash
                        </button>
                        <button class="terminal-button" type="button" data-firmware-toggle-output>
                            Show output
                        </button>
                    </div>
                    <pre class="cfg-firmware-output" data-firmware-output hidden></pre>
                    <p class="cfg-status" data-firmware-status aria-live="polite"></p>
                </article>
            </div>
        `;

        this._root.querySelector('[data-firmware-compile]')
            .addEventListener('click', () => this._compileFirmware());
        this._root.querySelector('[data-firmware-flash]')
            .addEventListener('click', () => this._flashFirmware());
        this._root.querySelector('[data-firmware-toggle-output]')
            .addEventListener('click', (e) => this._toggleFirmwareOutput(e.currentTarget));
        this._root.querySelector('[data-firmware-rescan-usb]')
            .addEventListener('click', (e) => this._rescanUsb(e.currentTarget));

        this._root.querySelector('[data-firmware-board]')
            .addEventListener('change', () => { this._firmwareBoardUserPicked = true; });
        this._root.querySelector('[data-firmware-device]')
            .addEventListener('change', () => {
                this._firmwareBoardUserPicked = false; // new device -- worth re-suggesting
                this._autoSelectFirmwareBoard();
            });

        this._loadFirmwareTargets();
        this._refreshSerialPortsList();
    }

    render(config) {
        const cap = (config && config.capture) || {};
        this._configuredDevices = (Array.isArray(cap.pocsag_serial) ? cap.pocsag_serial : [])
            .filter((d) => d.serial_port);
        this._portUsage = this._buildPortUsageMap(config);
        // Live per-device status (connected/board/...), keyed by `name` --
        // e.g. "dapnet_heltec" or bare "dapnet" -- same shape/convention
        // pocsag_serial_card.js's own devices card already reads.
        this._liveStatuses = Array.isArray(config.dapnet_status) ? config.dapnet_status : [];
        this._renderFirmwareDevicePicker();
        this._autoSelectFirmwareBoard();
    }

    /** Maps every currently-configured serial_port value (across Serial
     * devices, MeshCore companions, and POCSAG companions -- one shared
     * USB pool) to a human label, for the "already used by ..." hint in
     * the device picker. Same logic as meshcore_firmware_card.js's and
     * meshtastic_firmware_card.js's own copies -- duplicated rather than
     * shared, this file is otherwise independent of those. */
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

    /** Live USB-serial enumeration for the device picker. Re-fetched
     * whenever this page is mounted; the "↻ Rescan USB" button covers a
     * device plugged in after landing on this page instead of needing a
     * full reload. */
    async _refreshSerialPortsList() {
        const result = await this._api.get('/api/config/serial-ports');
        const ports = (result && Array.isArray(result.ports)) ? result.ports : [];
        this._enumeratedPorts = ports;
        this._renderFirmwareDevicePicker();
        this._autoSelectFirmwareBoard();
    }

    /** "↻ Rescan USB" click handler -- disable + "Scanning…" while in
     * flight, same as the other two firmware cards' own copy. */
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

    /** Native <datalist>-truncation-avoiding label, identical to the
     * other two firmware cards' own _portOptionLabel. */
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

    /** Board pulldown options, auto-populated from GET .../targets
     * (whatever BOARD_* the sketch's own #define lines actually list --
     * see pocsag_firmware_routes.py's _discover_board_targets). */
    async _loadFirmwareTargets() {
        const select = this._root.querySelector('[data-firmware-board]');
        if (!select) return;
        const result = await this._api.get('/api/pocsag/firmware/targets');
        const boards = (result && Array.isArray(result.boards)) ? result.boards : [];
        this._firmwareBoards = boards;
        select.innerHTML = boards.map((b) => (
            `<option value="${this._esc(b.macro)}">${this._esc(b.label)}</option>`
        )).join('');
        this._autoSelectFirmwareBoard();
        // Defaults true (don't warn before we actually know) -- flipped
        // to false only once GET .../targets confirms arduino-cli is
        // missing (e.g. scripts/install.sh was run with --skip-arduino).
        this._arduinoCliAvailable = result ? !!result.arduino_cli_available : true;
        this._updateCliAvailabilityUI();
    }

    /** Shows/hides the "arduino-cli isn't installed" warning and
     * disables Compile (always) -- Flash's own enabled state is decided
     * together with port availability in _renderFirmwareDevicePicker(). */
    _updateCliAvailabilityUI() {
        const warning = this._root.querySelector('[data-firmware-cli-warning]');
        const compileBtn = this._root.querySelector('[data-firmware-compile]');
        if (warning) warning.hidden = this._arduinoCliAvailable !== false;
        if (compileBtn) compileBtn.disabled = this._arduinoCliAvailable === false;
        this._renderFirmwareDevicePicker();
    }

    /** Maps the companion's own reported `board` string (from its live
     * {"cmd":"status"} reply) to the matching BOARD_* macro -- the
     * reverse of pocsag_firmware_routes.py's _KNOWN_BOARDS, small enough
     * to just duplicate here rather than round-trip through another
     * endpoint. */
    static _LIVE_BOARD_TO_MACRO = {
        heltec: 'BOARD_HELTEC_WIFI_LORA32_V3',
        ttgo: 'BOARD_TTGO_LORA32',
    };

    /** Auto-selects the Board pulldown to match whichever device is
     * currently picked in "Device to flash" -- but only when that port
     * matches an already-configured POCSAG companion that has reported a
     * live board (nothing to suggest for a blank/unconfigured board).
     * Only ever nudges the pulldown automatically, never overriding a
     * choice the user made themselves (see the board <select>'s own
     * 'change' listener, reset whenever the device picker changes since
     * that's a new context worth re-suggesting for). No-ops silently if
     * the board pulldown's own options haven't loaded yet. */
    _autoSelectFirmwareBoard() {
        if (this._firmwareBoardUserPicked) return;
        const boardSelect = this._root.querySelector('[data-firmware-board]');
        const deviceSelect = this._root.querySelector('[data-firmware-device]');
        if (!boardSelect || !boardSelect.options.length) return;
        if (!deviceSelect || !deviceSelect.value) return;

        const port = (this._enumeratedPorts || []).find((p) => p.stable_path === deviceSelect.value);
        if (!port) return;
        const aliases = [port.device, port.stable_path, port.by_id, port.by_path].filter(Boolean);
        const configured = (this._configuredDevices || [])
            .find((d) => d.serial_port && aliases.includes(d.serial_port));
        if (!configured) return;

        const live = this._liveStatusFor(configured.label || '');
        const macro = live && live.board
            ? PocsagFirmwareConfigCard._LIVE_BOARD_TO_MACRO[live.board]
            : null;
        if (!macro) return;

        const hasOption = Array.from(boardSelect.options).some((o) => o.value === macro);
        if (hasOption) boardSelect.value = macro;
    }

    _liveStatusFor(label) {
        const name = label ? `dapnet_${label}` : 'dapnet';
        return (this._liveStatuses || []).find((s) => s.name === name) || null;
    }

    /** Populates the "Device to flash" pulldown from every currently
     * enumerated USB-serial device -- deliberately NOT limited to
     * already-configured POCSAG companions, so a spare board (or a
     * friend's, just passing through) can be flashed without adding-
     * then-removing a permanent device entry first, and so flashing a
     * board that already IS a configured companion always requires an
     * explicit pick rather than defaulting to it. Options carry the same
     * "used by ..." hint as the other firmware cards' device pickers.
     * The selected value is a stable_path, re-validated against the live
     * enumeration server-side -- never trusted as a raw path from the
     * browser. */
    _renderFirmwareDevicePicker() {
        const select = this._root.querySelector('[data-firmware-device]');
        const flashBtn = this._root.querySelector('[data-firmware-flash]');
        if (!select || !flashBtn) return;

        const ports = this._enumeratedPorts || [];
        const usage = this._portUsage || {};

        if (ports.length === 0) {
            select.innerHTML = '<option value="">No USB-serial devices detected</option>';
            flashBtn.disabled = true;
            flashBtn.title = 'No USB-serial device connected to flash.';
            return;
        }

        const previous = select.value;
        select.innerHTML = ports.map((p) => (
            `<option value="${this._esc(p.stable_path)}">${this._esc(this._portOptionLabel(p, usage))}</option>`
        )).join('');
        if (previous && ports.some((p) => p.stable_path === previous)) select.value = previous;

        if (this._arduinoCliAvailable === false) {
            flashBtn.disabled = true;
            flashBtn.title = 'arduino-cli is not installed -- see the warning above.';
            return;
        }
        flashBtn.disabled = false;
        flashBtn.title = '';
    }

    _toggleFirmwareOutput(button) {
        const pre = this._root.querySelector('[data-firmware-output]');
        if (!pre) return;
        pre.hidden = !pre.hidden;
        button.textContent = pre.hidden ? 'Show output' : 'Hide output';
    }

    _appendFirmwareOutput(text) {
        const pre = this._root.querySelector('[data-firmware-output]');
        if (!pre || !text) return;
        pre.textContent = pre.textContent ? `${pre.textContent}\n${text}` : text;
        pre.scrollTop = pre.scrollHeight;
    }

    async _compileFirmware() {
        const boardSelect = this._root.querySelector('[data-firmware-board]');
        const boardMacro = boardSelect?.value;
        if (!boardMacro) return;
        const boardLabel = boardSelect.options[boardSelect.selectedIndex]?.text || boardMacro;

        await this._runFirmwareStream(
            '/api/pocsag/firmware/compile/stream',
            { board_macro: boardMacro },
            `Compiling for ${boardLabel}…`,
            'Compiled',
        );
    }

    async _flashFirmware() {
        const boardSelect = this._root.querySelector('[data-firmware-board]');
        const deviceSelect = this._root.querySelector('[data-firmware-device]');
        const boardMacro = boardSelect?.value;
        const port = deviceSelect?.value;
        if (!boardMacro || !port) return;

        const deviceLabel = deviceSelect.options[deviceSelect.selectedIndex]?.text || port;

        const ok = await window.confirmModal({
            label: 'Flash companion firmware',
            description: `Write the compiled firmware to "${deviceLabel}"? If a configured `
                + 'POCSAG companion is currently using that port, capture on it pauses during '
                + 'the flash and resumes automatically afterward.',
        });
        if (!ok) return;

        await this._runFirmwareStream(
            '/api/pocsag/firmware/flash/stream',
            { board_macro: boardMacro, port },
            `Flashing ${deviceLabel}…`,
            'Flashed',
        );
    }

    /** Shared streaming runner for Compile/Flash -- both hit an NDJSON
     * endpoint shaped {"type":"line"|"result",...} (see
     * pocsag_firmware_routes.py's _stream_subprocess), rendered into the
     * same collapsed-by-default output panel. Disables BOTH action
     * buttons while either is running since compile and flash share the
     * one sketch/board-define state on disk -- running them concurrently
     * would race. */
    async _runFirmwareStream(url, body, startMessage, verbPast) {
        const status = this._root.querySelector('[data-firmware-status]');
        const compileBtn = this._root.querySelector('[data-firmware-compile]');
        const flashBtn = this._root.querySelector('[data-firmware-flash]');
        const outputPre = this._root.querySelector('[data-firmware-output]');

        compileBtn.disabled = true;
        flashBtn.disabled = true;
        status.dataset.kind = 'pending';
        status.textContent = startMessage;
        if (outputPre) outputPre.textContent = '';
        this._appendFirmwareOutput(`# ${startMessage}`);

        let finalResult = null;
        try {
            finalResult = await window.UpdateStreamClient.postNdjson(url, body, (event) => {
                if (event.type === 'started' && Array.isArray(event.cmd)) {
                    this._appendFirmwareOutput(`$ ${event.cmd.join(' ')}`);
                } else if (event.type === 'line') {
                    this._appendFirmwareOutput(event.text);
                }
            });
        } catch (err) {
            status.dataset.kind = 'error';
            status.textContent = `Request failed: ${err.message || err}`;
            this._appendFirmwareOutput(`! ${err.message || err}`);
            compileBtn.disabled = false;
            flashBtn.disabled = false;
            return;
        }

        const success = !!(finalResult && finalResult.success);
        status.dataset.kind = success ? 'success' : 'error';
        status.textContent = success
            ? `${verbPast}.`
            : `Failed (exit code ${finalResult ? finalResult.returncode : '?'}). See output below.`;
        if (!success && outputPre) outputPre.hidden = false;
        const toggleBtn = this._root.querySelector('[data-firmware-toggle-output]');
        if (toggleBtn && outputPre) {
            toggleBtn.textContent = outputPre.hidden ? 'Show output' : 'Hide output';
        }

        compileBtn.disabled = false;
        flashBtn.disabled = false;
        if (success) await this._api.refresh();
    }

    _esc(str) {
        const el = document.createElement('span');
        el.textContent = str || '';
        return el.innerHTML;
    }
}

window.PocsagFirmwareConfigCard = PocsagFirmwareConfigCard;
