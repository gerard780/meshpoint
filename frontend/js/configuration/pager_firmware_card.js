/**
 * Configuration → Firmware page: Pager client card.
 *
 * Fourth card on the shared Firmware page (order: Meshtastic, MeshCore,
 * POCSAG, Pager). Drives src/api/routes/pager_firmware_routes.py's
 * compile/flash-stream endpoints -- same arduino-cli mechanism as the
 * POCSAG card (pocsag_firmware_card.js), simplified since pager_client.ino
 * has only one board (Heltec V3, no BOARD_* toggle) and no USB-serial link
 * to Meshpoint to release/reconnect around a flash (it's a standalone
 * over-the-air device, not a companion) -- so there's no board picker and
 * no "used by a configured companion" release logic, just a device-to-flash
 * picker (any currently-enumerated USB-serial device) plus Compile/Flash.
 */

class PagerFirmwareConfigCard {
    constructor(api) {
        this._api = api;
        this._root = null;
        this._enumeratedPorts = [];
        this._portUsage = {};
    }

    mount(root) {
        this._root = root;
        this._root.innerHTML = `
            <div class="cfg-section" data-pager-firmware-root>
                <article class="cfg-card">
                    <header class="cfg-card__head">
                        <h3 class="cfg-card__title">Pager client firmware</h3>
                        <p class="cfg-card__hint">
                            Build and flash extra/pager_client straight from this
                            dashboard -- no Arduino IDE needed. Requires the arduino-cli
                            toolchain (installed automatically by scripts/install.sh).
                            Heltec V3 only -- a standalone over-the-air pager, not a USB
                            companion.
                        </p>
                        <p class="cfg-status" data-kind="error" data-firmware-cli-warning hidden>
                            arduino-cli isn't installed on this Pi, so Compile/Flash won't
                            work yet -- re-run <code>scripts/install.sh</code> (without
                            <code>--skip-arduino</code>) to add it, then reload this page.
                        </p>
                    </header>
                    <label class="cfg-field">
                        <span class="cfg-field__label">Capcodes to program</span>
                        <input class="cfg-field__input" type="text" data-firmware-capcodes
                               placeholder="e.g. 123456, 654321">
                        <p class="cfg-field__hint">
                            Comma-separated. This unit will answer to all of these (its
                            personal number, plus any group/team addresses) as well as
                            911/112 emergency, in addition to always reporting to this
                            box's own configured pager capcode.
                        </p>
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

        this._refreshSerialPortsList();
        this._loadFirmwareTargets();
    }

    /** Single fixed board -- the only thing this card actually needs
     * from GET .../targets is arduino_cli_available (see
     * pager_firmware_routes.py's firmware_targets()). */
    async _loadFirmwareTargets() {
        const result = await this._api.get('/api/pager/firmware/targets');
        // Defaults true (don't warn before we actually know) -- flipped
        // to false only once this confirms arduino-cli is missing (e.g.
        // scripts/install.sh was run with --skip-arduino).
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

    render(config) {
        this._portUsage = this._buildPortUsageMap(config);
        this._renderFirmwareDevicePicker();
    }

    /** Maps every currently-configured serial_port value (across Serial,
     * MeshCore, and POCSAG companions -- one shared USB pool) to a human
     * label, for the "already used by ..." hint in the device picker.
     * Duplicated from pocsag_firmware_card.js's own copy, same convention
     * (each firmware card keeps its own copy rather than sharing one). */
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
        const ports = (result && Array.isArray(result.ports)) ? result.ports : [];
        this._enumeratedPorts = ports;
        this._renderFirmwareDevicePicker();
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
        const input = this._root.querySelector('[data-firmware-capcodes]');
        const status = this._root.querySelector('[data-firmware-status]');
        const raw = (input?.value || '').trim();

        const myCapcodes = raw
            .split(',')
            .map((s) => s.trim())
            .filter((s) => s.length > 0)
            .map((s) => Number(s));

        if (myCapcodes.length === 0 || myCapcodes.some((n) => !Number.isInteger(n) || n < 0)) {
            status.dataset.kind = 'error';
            status.textContent = 'Enter at least one valid capcode (comma-separated whole numbers).';
            return;
        }

        await this._runFirmwareStream(
            '/api/pager/firmware/compile/stream',
            { my_capcodes: myCapcodes },
            'Compiling for Heltec V3…',
            'Compiled',
        );
    }

    async _flashFirmware() {
        const deviceSelect = this._root.querySelector('[data-firmware-device]');
        const port = deviceSelect?.value;
        if (!port) return;

        const deviceLabel = deviceSelect.options[deviceSelect.selectedIndex]?.text || port;

        const ok = await window.confirmModal({
            label: 'Flash pager client firmware',
            description: `Write the compiled firmware to "${deviceLabel}"?`,
        });
        if (!ok) return;

        await this._runFirmwareStream(
            '/api/pager/firmware/flash/stream',
            { port },
            `Flashing ${deviceLabel}…`,
            'Flashed',
        );
    }

    /** Shared streaming runner for Compile/Flash, identical shape to the
     * other firmware cards' own copy. Disables both action buttons while
     * either runs, since compile and flash share the one build cache. */
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

window.PagerFirmwareConfigCard = PagerFirmwareConfigCard;
