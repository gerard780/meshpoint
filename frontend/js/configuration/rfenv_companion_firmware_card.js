/**
 * Configuration → Firmware page: RF Environment companion card.
 *
 * Drives src/api/routes/rfenv_companion_firmware_routes.py's
 * compile/flash-stream endpoints -- same arduino-cli mechanism as the
 * Pager/POCSAG cards. Single board (Heltec V3, no board picker -- the
 * sketch has no BOARD_* toggle) but DOES have one compile-time choice:
 * RF band (BAND_EU868 vs BAND_70CM, see rfenv_companion.ino's own "BAND
 * SELECT" block) -- same auto-discovered-pulldown pattern
 * pocsag_firmware_card.js uses for its Board picker, just for a Band
 * picker instead. A 70cm-flashed board is a standalone handheld
 * scanner -- it can't usefully feed a 868/915-band Meshpoint's own RF
 * Environment page, so this is a second physical board's firmware, not
 * an alternate mode for the one already configured as a companion.
 */

class RfenvCompanionFirmwareConfigCard {
    constructor(api) {
        this._api = api;
        this._root = null;
        this._enumeratedPorts = [];
        this._portUsage = {};
        this._bandTargets = [];
    }

    mount(root) {
        this._root = root;
        this._root.innerHTML = `
            <div class="cfg-section" data-rfenv-firmware-root>
                <article class="cfg-card">
                    <header class="cfg-card__head">
                        <h3 class="cfg-card__title">RF Environment companion firmware</h3>
                        <p class="cfg-card__hint">
                            Build and flash extra/rfenv_companion straight from this
                            dashboard -- no Arduino IDE needed. Requires the arduino-cli
                            toolchain (installed automatically by scripts/install.sh).
                            Heltec V3 only. Pick 70cm to build a standalone handheld
                            scanner on a second board -- it won't feed this box's own
                            RF Environment page.
                        </p>
                    </header>
                    <label class="cfg-field cfg-firmware-field">
                        <span class="cfg-field__label">Band</span>
                        <select class="cfg-field__input" data-firmware-band></select>
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

        this._loadFirmwareTargets();
        this._refreshSerialPortsList();
    }

    /** Band pulldown options, auto-populated from GET .../targets --
     * whatever BAND_* toggles rfenv_companion.ino's own "BAND SELECT"
     * block actually lists (see rfenv_companion_firmware_routes.py's
     * _discover_band_targets()). Same pattern pocsag_firmware_card.js
     * uses for its Board pulldown. */
    async _loadFirmwareTargets() {
        const select = this._root.querySelector('[data-firmware-band]');
        if (!select) return;
        const result = await this._api.get('/api/rfenv-companion/firmware/targets');
        const bands = (result && Array.isArray(result.bands)) ? result.bands : [];
        this._bandTargets = bands;
        if (bands.length === 0) {
            select.innerHTML = '<option value="">No bands found</option>';
            return;
        }
        select.innerHTML = bands.map((b) => (
            `<option value="${this._esc(b.macro)}">${this._esc(b.label)}</option>`
        )).join('');
    }

    render(config) {
        this._portUsage = this._buildPortUsageMap(config);
        this._renderFirmwareDevicePicker();
    }

    /** Maps every currently-configured serial_port value (across Serial,
     * MeshCore, POCSAG, and this companion -- one shared USB pool) to a
     * human label, for the "already used by ..." hint in the device
     * picker. Same convention every other firmware card's copy uses. */
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
        (Array.isArray(cap.rfenv_companion) ? cap.rfenv_companion : []).forEach((d) => {
            if (d.serial_port) usage[d.serial_port] = d.label ? `RF Env ${d.label}` : 'RF Env';
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
        const bandSelect = this._root.querySelector('[data-firmware-band]');
        const bandMacro = bandSelect?.value;
        const status = this._root.querySelector('[data-firmware-status]');
        if (!bandMacro) {
            status.dataset.kind = 'error';
            status.textContent = 'No band selected -- rescan or reload the page.';
            return;
        }
        const bandLabel = bandSelect.options[bandSelect.selectedIndex]?.text || bandMacro;

        await this._runFirmwareStream(
            '/api/rfenv-companion/firmware/compile/stream',
            { band_macro: bandMacro },
            `Compiling for ${bandLabel}…`,
            'Compiled',
        );
    }

    async _flashFirmware() {
        const deviceSelect = this._root.querySelector('[data-firmware-device]');
        const port = deviceSelect?.value;
        if (!port) return;

        const deviceLabel = deviceSelect.options[deviceSelect.selectedIndex]?.text || port;

        const ok = await window.confirmModal({
            label: 'Flash RF Environment companion firmware',
            description: `Write the compiled firmware to "${deviceLabel}"? If this port is `
                + `the currently-configured companion, it will be briefly disconnected `
                + `and reconnected automatically.`,
        });
        if (!ok) return;

        await this._runFirmwareStream(
            '/api/rfenv-companion/firmware/flash/stream',
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

window.RfenvCompanionFirmwareConfigCard = RfenvCompanionFirmwareConfigCard;
