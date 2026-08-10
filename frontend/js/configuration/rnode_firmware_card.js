/**
 * Configuration → Firmware page: RNode card.
 *
 * Flashes "dumb modem" RNode firmware onto a connected board -- the
 * board rnsd/meshpoint's own Reticulum service then drives directly
 * over USB serial, same role as the RNode already plugged into this
 * deployment. Not the same thing as the Reticulum companion card
 * above (extra/heltec_v4_reticulum_bron) -- that one is a standalone
 * WiFi-bridging node with its own firmware; this one is the "real"
 * RNode firmware from https://github.com/markqvist/RNode_Firmware,
 * driven server-side via `rnodeconf` (see
 * src/api/routes/rnode_firmware_routes.py's own docstring for why
 * this is a server-side subprocess rather than a port of the
 * liamcottle/rnode-flasher Web Serial tool reticulum-meshchat itself
 * vendors -- that tool only reaches devices on the same machine as
 * the browser, which isn't true here).
 *
 * Simpler than the other firmware cards: rnodeconf's own --autoinstall
 * flow always fetches whatever firmware it needs itself and does
 * flash + EEPROM-provision + firmware-hash-set in one run, so there's
 * no separate Compile step, no version picker, no "erase everything"
 * toggle -- just Board + Device to flash + one Flash button.
 */

class RnodeFirmwareConfigCard {
    constructor(api) {
        this._api = api;
        this._root = null;
        this._enumeratedPorts = [];
        this._portUsage = {};
        this._boards = [];
    }

    mount(root) {
        this._root = root;
        this._root.innerHTML = `
            <div class="cfg-section" data-rnode-firmware-root>
                <article class="cfg-card">
                    <header class="cfg-card__head">
                        <h3 class="cfg-card__title">RNode firmware</h3>
                        <p class="cfg-card__hint">
                            Flash a supported board with real RNode firmware, then
                            provision its EEPROM and set its firmware hash -- all in one
                            step. The result is a "dumb modem" board that rnsd/meshpoint's
                            own Reticulum service drives directly over USB serial, same
                            role as any other RNode. Firmware is fetched live by
                            <code>rnodeconf</code> itself; the Pi needs internet access
                            at flash time.
                        </p>
                    </header>
                    <label class="cfg-field cfg-firmware-field">
                        <span class="cfg-field__label">Board</span>
                        <select class="cfg-field__input" data-rnode-firmware-board></select>
                    </label>
                    <label class="cfg-field cfg-firmware-field">
                        <span class="cfg-field__label">Device to flash</span>
                        <select class="cfg-field__input" data-rnode-firmware-device></select>
                        <button class="terminal-button cfg-firmware-rescan" type="button" data-rnode-rescan-usb
                                title="Re-scan connected USB devices">
                            ↻ Rescan USB
                        </button>
                    </label>
                    <div class="cfg-card__actions">
                        <button class="terminal-button terminal-button--primary"
                                type="button" data-rnode-firmware-flash>
                            Flash
                        </button>
                        <button class="terminal-button" type="button" data-rnode-firmware-toggle-output>
                            Show output
                        </button>
                    </div>
                    <pre class="cfg-firmware-output" data-rnode-firmware-output hidden></pre>
                    <p class="cfg-status" data-rnode-firmware-status aria-live="polite"></p>
                </article>
            </div>
        `;

        this._root.querySelector('[data-rnode-firmware-flash]')
            .addEventListener('click', () => this._flashRnodeFirmware());
        this._root.querySelector('[data-rnode-firmware-toggle-output]')
            .addEventListener('click', (e) => this._toggleOutput(e.currentTarget));
        this._root.querySelector('[data-rnode-rescan-usb]')
            .addEventListener('click', (e) => this._rescanUsb(e.currentTarget));

        this._loadBoards();
        this._refreshSerialPortsList();
    }

    render(config) {
        this._portUsage = this._buildPortUsageMap(config);
    }

    /** Same shared USB pool every other firmware card's picker draws
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

    async _loadBoards() {
        const select = this._root.querySelector('[data-rnode-firmware-board]');
        if (!select) return;
        const result = await this._api.get('/api/rnode/firmware/targets');
        const boards = (result && Array.isArray(result.boards)) ? result.boards : [];
        this._boards = boards;
        const previous = select.value;
        select.innerHTML = boards.map((b) => (
            `<option value="${this._esc(b.value)}">${this._esc(b.label)}</option>`
        )).join('');
        if (previous && boards.some((b) => b.value === previous)) select.value = previous;

        if (result && result.rnodeconf_available === false) {
            const status = this._root.querySelector('[data-rnode-firmware-status]');
            if (status) {
                status.dataset.kind = 'error';
                status.textContent = 'rnodeconf not found on this system -- check that rns is '
                    + 'installed in the meshpoint venv (it should be, via requirements.txt).';
            }
            this._root.querySelector('[data-rnode-firmware-flash]').disabled = true;
        }
    }

    async _refreshSerialPortsList() {
        const result = await this._api.get('/api/config/serial-ports');
        const ports = (result && Array.isArray(result.ports)) ? result.ports : [];
        this._enumeratedPorts = ports;
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
        const select = this._root.querySelector('[data-rnode-firmware-device]');
        if (!select) return;
        const ports = this._enumeratedPorts || [];
        const usage = this._portUsage || {};
        if (ports.length === 0) {
            select.innerHTML = '<option value="">No USB-serial devices detected</option>';
        } else {
            const previous = select.value;
            select.innerHTML = ports.map((p) => (
                `<option value="${this._esc(p.stable_path)}">${this._esc(this._portOptionLabel(p, usage))}</option>`
            )).join('');
            if (previous && ports.some((p) => p.stable_path === previous)) select.value = previous;
        }
    }

    _toggleOutput(button) {
        const pre = this._root.querySelector('[data-rnode-firmware-output]');
        if (!pre) return;
        pre.hidden = !pre.hidden;
        button.textContent = pre.hidden ? 'Show output' : 'Hide output';
    }

    _appendOutput(text) {
        const pre = this._root.querySelector('[data-rnode-firmware-output]');
        if (!pre || !text) return;
        pre.textContent = pre.textContent ? `${pre.textContent}\n${text}` : text;
        pre.scrollTop = pre.scrollHeight;
    }

    async _flashRnodeFirmware() {
        const boardSelect = this._root.querySelector('[data-rnode-firmware-board]');
        const deviceSelect = this._root.querySelector('[data-rnode-firmware-device]');
        const board = boardSelect?.value;
        const port = deviceSelect?.value;
        if (!board || !port) return;

        const status = this._root.querySelector('[data-rnode-firmware-status]');
        const boardLabel = boardSelect.options[boardSelect.selectedIndex]?.text || board;
        const deviceLabel = deviceSelect.options[deviceSelect.selectedIndex]?.text || port;

        const ok = await window.confirmModal({
            label: 'Flash RNode firmware',
            description: `Flash ${boardLabel} firmware onto "${deviceLabel}", provision its `
                + 'EEPROM, and set its firmware hash? This replaces whatever is currently on '
                + 'the board -- not reversible from here.',
        });
        if (!ok) return;

        const flashBtn = this._root.querySelector('[data-rnode-firmware-flash]');
        const outputPre = this._root.querySelector('[data-rnode-firmware-output]');

        flashBtn.disabled = true;
        status.dataset.kind = 'pending';
        status.textContent = `Flashing ${deviceLabel}…`;
        if (outputPre) outputPre.textContent = '';
        this._appendOutput(`# Flashing ${boardLabel} onto ${port}…`);

        let finalResult = null;
        try {
            finalResult = await window.UpdateStreamClient.postNdjson(
                '/api/rnode/firmware/flash/stream',
                { board, port },
                (event) => {
                    if (event.type === 'started' && Array.isArray(event.cmd)) {
                        this._appendOutput(`$ ${event.cmd.join(' ')}`);
                    } else if (event.type === 'line') {
                        this._appendOutput(event.text);
                    }
                },
            );
        } catch (err) {
            status.dataset.kind = 'error';
            status.textContent = `Request failed: ${err.message || err}`;
            this._appendOutput(`! ${err.message || err}`);
            flashBtn.disabled = false;
            return;
        }

        const success = !!(finalResult && finalResult.success);
        status.dataset.kind = success ? 'success' : 'error';
        status.textContent = success
            ? 'Flashed, provisioned, and firmware hash set.'
            : `Failed (exit code ${finalResult ? finalResult.returncode : '?'}). See output below.`;
        if (!success && outputPre) outputPre.hidden = false;
        const toggleBtn = this._root.querySelector('[data-rnode-firmware-toggle-output]');
        if (toggleBtn && outputPre) {
            toggleBtn.textContent = outputPre.hidden ? 'Show output' : 'Hide output';
        }

        flashBtn.disabled = false;
    }

    _esc(str) {
        const el = document.createElement('span');
        el.textContent = str == null ? '' : String(str);
        return el.innerHTML;
    }
}

window.RnodeFirmwareConfigCard = RnodeFirmwareConfigCard;
