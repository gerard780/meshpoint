/**
 * Configuration → Firmware page: Reticulum companion card.
 *
 * Drives src/api/routes/reticulum_companion_firmware_routes.py's
 * compile/flash-stream endpoints -- same streamed-NDJSON shape as every
 * other firmware card, but wraps PlatformIO (`pio`) instead of
 * arduino-cli: extra/heltec_v4_reticulum_bron/microReticulum_Firmware's
 * own platformio.ini needs per-environment custom_variant/littlefs/
 * symlinked lib_deps config arduino-cli's boards.txt system can't
 * express. Single fixed board/environment (Heltec V4, the only one this
 * deployment owns, out of 32 the firmware's own platformio.ini defines)
 * -- no board picker.
 *
 * Unlike the arduino-cli cards, "Compile" here also provisions: WiFi
 * SSID/password and the Reticulum backbone host/port are this firmware's
 * only run-time-configurable settings, and they're compile-time #defines
 * (node_config.h) -- there's no serial/NVS provisioning path like
 * POCSAG/RF-Env's Live Device Commands, so every credential change means
 * an actual rebuild. No device-picker "used by a configured companion"
 * release logic either -- this is a standalone WiFi device, Meshpoint
 * never holds an open serial connection to it.
 */

class ReticulumCompanionFirmwareConfigCard {
    constructor(api) {
        this._api = api;
        this._root = null;
        this._enumeratedPorts = [];
        this._portUsage = {};
        this._maxCredLen = 32;
        this._defaultsPrefilled = false;
    }

    mount(root) {
        this._root = root;
        this._root.innerHTML = `
            <div class="cfg-section" data-reticulum-firmware-root>
                <article class="cfg-card">
                    <header class="cfg-card__head">
                        <h3 class="cfg-card__title">Reticulum companion firmware</h3>
                        <p class="cfg-card__hint">
                            Provision and flash extra/heltec_v4_reticulum_bron straight
                            from this dashboard -- no Arduino IDE or PlatformIO IDE needed.
                            Requires the PlatformIO toolchain (installed automatically by
                            scripts/install.sh). Heltec V4 only, standalone: it bridges
                            local LoRa to the Reticulum network over WiFi, with no USB link
                            back to this box once flashed.
                        </p>
                        <p class="cfg-status" data-kind="error" data-firmware-cli-warning hidden>
                            PlatformIO isn't installed on this Pi, so Compile/Flash won't
                            work yet -- re-run <code>scripts/install.sh</code> (without
                            <code>--skip-platformio</code>) to add it, then reload this page.
                        </p>
                    </header>
                    <label class="cfg-field">
                        <span class="cfg-field__label">WiFi SSID</span>
                        <input class="cfg-field__input" type="text" data-firmware-ssid
                               placeholder="Network name" maxlength="32">
                    </label>
                    <label class="cfg-field">
                        <span class="cfg-field__label">WiFi password</span>
                        <input class="cfg-field__input" type="password"
                               autocomplete="new-password" data-firmware-password
                               placeholder="Leave blank for an open network" maxlength="32">
                        <p class="cfg-field__hint" data-firmware-cred-hint>
                            This firmware's own buffer truncates SSID and password at 32
                            characters each -- longer than that will silently fail to
                            connect on the device, so it's capped here too.
                        </p>
                    </label>
                    <label class="cfg-field">
                        <span class="cfg-field__label">Reticulum backbone host</span>
                        <input class="cfg-field__input" type="text" data-firmware-vps-host
                               placeholder="node.reticulumnet.nl">
                    </label>
                    <label class="cfg-field">
                        <span class="cfg-field__label">Backbone port</span>
                        <input class="cfg-field__input" type="number" data-firmware-vps-port
                               placeholder="4242" min="1" max="65535">
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

    /** Single fixed board/environment -- what this card actually needs
     * from GET .../targets is platformio_available plus the backbone
     * host/port defaults to pre-fill (see reticulum_companion_firmware_
     * routes.py's firmware_targets()). */
    async _loadFirmwareTargets() {
        const result = await this._api.get('/api/reticulum-companion/firmware/targets');
        // Defaults true (don't warn before we actually know) -- flipped
        // to false only once this confirms PlatformIO is missing (e.g.
        // scripts/install.sh was run with --skip-platformio).
        this._platformioAvailable = result ? !!result.platformio_available : true;
        if (result) {
            this._maxCredLen = result.max_cred_len || 32;
            this._prefillDefaults(result.default_vps_host, result.default_vps_port);
        }
        this._updateCliAvailabilityUI();
    }

    /** Pre-fills the backbone host/port fields once, only if still empty
     * -- same "don't fight a value the user's actively typing" idea as
     * the RF Environment card's frequency pre-fill. */
    _prefillDefaults(host, port) {
        if (this._defaultsPrefilled) return;
        const hostInput = this._root.querySelector('[data-firmware-vps-host]');
        const portInput = this._root.querySelector('[data-firmware-vps-port]');
        if (hostInput && !hostInput.value && host) hostInput.value = host;
        if (portInput && !portInput.value && port) portInput.value = String(port);
        this._defaultsPrefilled = true;
    }

    /** Shows/hides the "PlatformIO isn't installed" warning and disables
     * Compile (always) -- Flash's own enabled state is decided together
     * with port availability in _renderFirmwareDevicePicker(). */
    _updateCliAvailabilityUI() {
        const warning = this._root.querySelector('[data-firmware-cli-warning]');
        const compileBtn = this._root.querySelector('[data-firmware-compile]');
        if (warning) warning.hidden = this._platformioAvailable !== false;
        if (compileBtn) compileBtn.disabled = this._platformioAvailable === false;
        this._renderFirmwareDevicePicker();
    }

    render(config) {
        this._portUsage = this._buildPortUsageMap(config);
        this._renderFirmwareDevicePicker();
    }

    /** Maps every currently-configured serial_port value (across Serial,
     * MeshCore, POCSAG, and RF Env -- one shared USB pool) to a human
     * label, for the "already used by ..." hint in the device picker.
     * This companion has no config entry of its own (standalone WiFi
     * device, nothing to add here) -- same convention every other
     * firmware card's copy uses otherwise. */
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

        if (this._platformioAvailable === false) {
            flashBtn.disabled = true;
            flashBtn.title = 'PlatformIO is not installed -- see the warning above.';
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
        const ssidInput = this._root.querySelector('[data-firmware-ssid]');
        const passwordInput = this._root.querySelector('[data-firmware-password]');
        const hostInput = this._root.querySelector('[data-firmware-vps-host]');
        const portInput = this._root.querySelector('[data-firmware-vps-port]');
        const status = this._root.querySelector('[data-firmware-status]');

        const ssid = (ssidInput?.value || '').trim();
        const password = passwordInput?.value || '';
        const vpsHost = (hostInput?.value || '').trim();
        const vpsPortRaw = (portInput?.value || '').trim();

        if (!ssid) {
            status.dataset.kind = 'error';
            status.textContent = 'Enter a WiFi SSID.';
            return;
        }
        if (ssid.length > this._maxCredLen || password.length > this._maxCredLen) {
            status.dataset.kind = 'error';
            status.textContent = `SSID and password are each capped at ${this._maxCredLen} characters on this firmware.`;
            return;
        }
        const vpsPort = vpsPortRaw ? Number(vpsPortRaw) : undefined;
        if (vpsPort !== undefined && (!Number.isInteger(vpsPort) || vpsPort < 1 || vpsPort > 65535)) {
            status.dataset.kind = 'error';
            status.textContent = 'Backbone port must be a whole number between 1 and 65535.';
            return;
        }

        const body = { ssid, password, vps_host: vpsHost };
        if (vpsPort !== undefined) body.vps_port = vpsPort;

        await this._runFirmwareStream(
            '/api/reticulum-companion/firmware/compile/stream',
            body,
            `Provisioning for "${ssid}"…`,
            'Compiled',
        );
        // Never leave a password sitting in the DOM longer than needed,
        // success or not.
        if (passwordInput) passwordInput.value = '';
    }

    async _flashFirmware() {
        const deviceSelect = this._root.querySelector('[data-firmware-device]');
        const port = deviceSelect?.value;
        if (!port) return;

        const deviceLabel = deviceSelect.options[deviceSelect.selectedIndex]?.text || port;

        const ok = await window.confirmModal({
            label: 'Flash Reticulum companion firmware',
            description: `Write the compiled firmware to "${deviceLabel}"?`,
        });
        if (!ok) return;

        await this._runFirmwareStream(
            '/api/reticulum-companion/firmware/flash/stream',
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

window.ReticulumCompanionFirmwareConfigCard = ReticulumCompanionFirmwareConfigCard;
