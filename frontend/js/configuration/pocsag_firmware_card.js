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
 * list or a manifest. Device-to-flash is still limited to already-
 * configured POCSAG companions (only shown at all past one) -- unlike
 * the other two cards, not changed to accept any USB device here.
 */

class PocsagFirmwareConfigCard {
    constructor(api) {
        this._api = api;
        this._root = null;
    }

    mount(root) {
        this._root = root;
        this._root.innerHTML = `
            <div class="cfg-section" data-pocsag-firmware-root>
                <article class="cfg-card">
                    <header class="cfg-card__head">
                        <h3 class="cfg-card__title">Companion firmware</h3>
                        <p class="cfg-card__hint">
                            Build and flash extra/pocsag_companion straight from this
                            dashboard -- no Arduino IDE needed. Requires the arduino-cli
                            toolchain (installed automatically by scripts/install.sh).
                        </p>
                    </header>
                    <label class="cfg-field cfg-field--narrow cfg-firmware-board-field">
                        <span class="cfg-field__label">Board</span>
                        <select class="cfg-field__input" data-firmware-board></select>
                    </label>
                    <label class="cfg-field cfg-field--narrow" data-firmware-device-wrap hidden>
                        <span class="cfg-field__label">Companion to flash</span>
                        <select class="cfg-field__input" data-firmware-device></select>
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

        this._root.querySelector('[data-firmware-board]')
            .addEventListener('change', () => { this._firmwareBoardUserPicked = true; });
        this._root.querySelector('[data-firmware-device]')
            .addEventListener('change', () => {
                this._firmwareBoardUserPicked = false; // new device -- worth re-suggesting
                this._autoSelectFirmwareBoard();
            });

        this._loadFirmwareTargets();
    }

    render(config) {
        const cap = (config && config.capture) || {};
        const devices = Array.isArray(cap.pocsag_serial) ? cap.pocsag_serial : [];
        // Live per-device status (connected/board/...), keyed by `name` --
        // e.g. "dapnet_heltec" or bare "dapnet" -- same shape/convention
        // pocsag_serial_card.js's own devices card already reads.
        this._liveStatuses = Array.isArray(config.dapnet_status) ? config.dapnet_status : [];
        this._renderFirmwareDevicePicker(devices);
        this._autoSelectFirmwareBoard();
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

    /** Auto-selects the Board pulldown to match whichever companion is
     * currently relevant (the one picked in "Companion to flash", or the
     * sole configured device when there's only one) -- but only ever
     * nudges it automatically, never overriding a choice the user made
     * themselves (see the board <select>'s own 'change' listener, reset
     * whenever the device picker changes since that's a new context
     * worth re-suggesting for). No-ops silently if the board pulldown's
     * own options haven't loaded yet, or the companion isn't connected/
     * hasn't reported a board -- nothing to suggest either way. */
    _autoSelectFirmwareBoard() {
        if (this._firmwareBoardUserPicked) return;
        const boardSelect = this._root.querySelector('[data-firmware-board]');
        const deviceSelect = this._root.querySelector('[data-firmware-device]');
        if (!boardSelect || !boardSelect.options.length) return;

        const devices = this._firmwareDevices || [];
        if (!devices.length) return;
        const label = devices.length > 1 ? (deviceSelect?.value ?? '') : (devices[0].label || '');
        const device = devices.find((d) => (d.label || '') === label) || devices[0];

        const live = this._liveStatusFor(device.label || '');
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

    /** Populates the "Companion to flash" pulldown from the currently
     * configured POCSAG devices -- only shown at all when there's more
     * than one (a single configured device is used directly, no need to
     * ask). Options are keyed on `label` (empty string = the bare
     * "dapnet" source, same convention _resolve_dapnet_source uses
     * server-side); the flash route resolves the actual port from this
     * label, never trusting a raw path from the browser. */
    _renderFirmwareDevicePicker(devices) {
        const wrap = this._root.querySelector('[data-firmware-device-wrap]');
        const select = this._root.querySelector('[data-firmware-device]');
        const flashBtn = this._root.querySelector('[data-firmware-flash]');
        if (!wrap || !select || !flashBtn) return;

        const configured = devices.filter((d) => d.serial_port);
        this._firmwareDevices = configured;

        if (configured.length === 0) {
            wrap.hidden = true;
            flashBtn.disabled = true;
            flashBtn.title = 'No configured POCSAG companion with a serial port to flash.';
            return;
        }

        flashBtn.disabled = false;
        flashBtn.title = '';
        wrap.hidden = configured.length <= 1;
        select.innerHTML = configured.map((d) => {
            const name = d.name || d.label || d.serial_port;
            return `<option value="${this._esc(d.label || '')}">${this._esc(name)}</option>`;
        }).join('');
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
        if (!boardMacro) return;

        const devices = this._firmwareDevices || [];
        const label = devices.length > 1 ? (deviceSelect?.value ?? '') : (devices[0]?.label || '');
        const device = devices.find((d) => (d.label || '') === label) || devices[0];
        if (!device) return;

        const ok = await window.confirmModal({
            label: 'Flash companion firmware',
            description: `Write the compiled firmware to "${device.name || device.serial_port}" `
                + `over ${device.serial_port}? POCSAG capture on this device pauses during the `
                + 'flash and resumes automatically afterward.',
        });
        if (!ok) return;

        await this._runFirmwareStream(
            '/api/pocsag/firmware/flash/stream',
            { board_macro: boardMacro, label },
            `Flashing ${device.name || device.serial_port}…`,
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
