/**
 * Configuration → Firmware page.
 *
 * Standalone home for "flash a spare board" actions -- previously each
 * protocol's own Configuration page (MeshCore, and eventually Serial/
 * POCSAG) carried its own firmware-flash card buried among that
 * protocol's actual settings, even though flashing a board is a
 * different kind of action (prep new/spare hardware) than configuring
 * an already-assigned companion. First card here is MeshCore's (moved
 * verbatim from meshcore_card.js, drives
 * src/api/routes/meshcore_firmware_routes.py); Serial/POCSAG firmware
 * cards are expected to join it here later, not built yet.
 */

class FirmwareConfigCard {
    constructor(api) {
        this._api = api;
        this._root = null;
        this._enumeratedPorts = [];
        this._portUsage = {};
    }

    mount(root) {
        this._root = root;
        this._root.innerHTML = `
            <div class="cfg-section" data-firmware-root>
                <article class="cfg-card">
                    <header class="cfg-card__head">
                        <h3 class="cfg-card__title">MeshCore firmware</h3>
                        <p class="cfg-card__hint">
                            Flash any connected USB-serial device with official MeshCore
                            companion firmware straight from this dashboard -- no compiling
                            needed, and no need to add it as a configured companion first.
                            Erases the ENTIRE flash first, so this also works on a board
                            currently running something else entirely (e.g. Meshtastic or
                            extra/pocsag_companion).
                        </p>
                    </header>
                    <label class="cfg-field cfg-field--narrow cfg-firmware-board-field">
                        <span class="cfg-field__label">Board</span>
                        <select class="cfg-field__input" data-mc-firmware-board></select>
                    </label>
                    <label class="cfg-field cfg-field--narrow">
                        <span class="cfg-field__label">Device to flash</span>
                        <select class="cfg-field__input" data-mc-firmware-device></select>
                    </label>
                    <label class="cfg-field cfg-field--narrow">
                        <span class="cfg-field__label">Version</span>
                        <select class="cfg-field__input" data-mc-firmware-tag></select>
                    </label>
                    <label class="cfg-field cfg-field--narrow">
                        <span class="cfg-field__label">Flavor</span>
                        <select class="cfg-field__input" data-mc-firmware-flavor>
                            <option value="usb">USB (connects to this dashboard)</option>
                            <option value="ble">BLE (Bluetooth, for the MeshCore phone app)</option>
                        </select>
                    </label>
                    <div class="cfg-card__actions">
                        <button class="terminal-button terminal-button--primary"
                                type="button" data-mc-firmware-flash>
                            Flash
                        </button>
                        <button class="terminal-button" type="button" data-mc-firmware-toggle-output>
                            Show output
                        </button>
                    </div>
                    <pre class="cfg-firmware-output" data-mc-firmware-output hidden></pre>
                    <p class="cfg-status" data-mc-firmware-status aria-live="polite"></p>
                </article>
            </div>
        `;

        this._root.querySelector('[data-mc-firmware-flash]')
            .addEventListener('click', () => this._flashMeshcoreFirmware());
        this._root.querySelector('[data-mc-firmware-toggle-output]')
            .addEventListener('click', (e) => this._toggleMcFirmwareOutput(e.currentTarget));

        this._loadMcFirmwareTargets();
        this._loadMcFirmwareReleases();
        this._refreshSerialPortsList();
    }

    render(config) {
        this._portUsage = this._buildPortUsageMap(config);
    }

    /** Maps every currently-configured serial_port value (across MeshCore
     * companions, Serial devices, and POCSAG companions -- one shared USB
     * pool, so a port pinned by any of them is "in use" from a flash
     * card's perspective) to a human label, for the "already used by ..."
     * hint in the device picker. Same logic as meshcore_card.js's own
     * copy -- duplicated rather than shared, this file is otherwise
     * independent of that one. */
    _buildPortUsageMap(config) {
        const usage = {};
        const cap = (config && config.capture) || {};
        (Array.isArray(cap.meshcore_usb) ? cap.meshcore_usb : []).forEach((c) => {
            if (c.serial_port) usage[c.serial_port] = c.label ? `MeshCore ${c.label}` : 'MeshCore';
        });
        (Array.isArray(cap.serial) ? cap.serial : []).forEach((d) => {
            if (d.serial_port) usage[d.serial_port] = d.label ? `Serial ${d.label}` : 'Serial';
        });
        (Array.isArray(cap.pocsag_serial) ? cap.pocsag_serial : []).forEach((d) => {
            if (d.serial_port) usage[d.serial_port] = d.label ? `POCSAG ${d.label}` : 'POCSAG';
        });
        return usage;
    }

    /** Live USB-serial enumeration for the device picker (same endpoint
     * meshcore_card.js's own companion port datalist uses). Re-fetched
     * whenever this page is mounted -- unlike meshcore_card.js's copy,
     * there's no periodic dashboard-poll render() driving this page to
     * naturally pick up newly-plugged devices, so a manual re-scan isn't
     * offered either; reopening the page re-fetches. */
    async _refreshSerialPortsList() {
        const result = await this._api.get('/api/config/serial-ports');
        const ports = (result && Array.isArray(result.ports)) ? result.ports : [];
        this._enumeratedPorts = ports;
        this._renderMcFirmwareDevicePicker();
    }

    /** Native <datalist>-truncation-avoiding label, identical to
     * meshcore_card.js's own _portOptionLabel. */
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

    /** Board pulldown options for the MeshCore firmware card, from the
     * curated list GET .../targets returns (see
     * meshcore_firmware_routes.py's _CURATED_BOARDS) -- not auto-
     * discovered from anything in this repo, since MeshCore firmware
     * isn't built from anything here either. */
    async _loadMcFirmwareTargets() {
        const select = this._root.querySelector('[data-mc-firmware-board]');
        if (!select) return;
        const result = await this._api.get('/api/config/meshcore/firmware/targets');
        const boards = (result && Array.isArray(result.boards)) ? result.boards : [];
        select.innerHTML = boards.map((b) => (
            `<option value="${this._esc(b.board)}">${this._esc(b.label)}</option>`
        )).join('');
    }

    /** Populates the "Device to flash" pulldown from every currently
     * enumerated USB-serial device -- deliberately NOT limited to
     * already-configured companions, so a spare board (or a friend's,
     * just passing through) can be flashed without adding-then-removing
     * a permanent companion entry first. Options carry the same "used
     * by ..." hint as meshcore_card.js's own companion port field. The
     * selected value is a stable_path, re-validated against the live
     * enumeration server-side -- never trusted as a raw path from the
     * browser. */
    _renderMcFirmwareDevicePicker() {
        const select = this._root.querySelector('[data-mc-firmware-device]');
        const flashBtn = this._root.querySelector('[data-mc-firmware-flash]');
        if (!select || !flashBtn) return;

        const ports = this._enumeratedPorts || [];
        const usage = this._portUsage || {};

        if (ports.length === 0) {
            select.innerHTML = '<option value="">No USB-serial devices detected</option>';
            flashBtn.disabled = true;
            flashBtn.title = 'No USB-serial device connected to flash.';
            return;
        }

        flashBtn.disabled = false;
        flashBtn.title = '';
        const previous = select.value;
        select.innerHTML = ports.map((p) => (
            `<option value="${this._esc(p.stable_path)}">${this._esc(this._portOptionLabel(p, usage))}</option>`
        )).join('');
        if (previous && ports.some((p) => p.stable_path === previous)) select.value = previous;
    }

    /** Version pulldown for the MeshCore firmware card, from the last 10
     * companion- tagged releases (GET .../releases), newest first.
     * "Latest" (empty tag, the default) covers routine flashing; this
     * is for the deliberate case -- pinning an older or specific
     * version, e.g. to match what another companion is already
     * running. */
    async _loadMcFirmwareReleases() {
        const select = this._root.querySelector('[data-mc-firmware-tag]');
        if (!select) return;
        const result = await this._api.get('/api/config/meshcore/firmware/releases');
        const releases = (result && Array.isArray(result.releases)) ? result.releases : [];
        const options = ['<option value="">Latest</option>'];
        releases.forEach((r) => {
            options.push(`<option value="${this._esc(r.tag)}">${this._esc(r.tag)}</option>`);
        });
        select.innerHTML = options.join('');
    }

    _toggleMcFirmwareOutput(button) {
        const pre = this._root.querySelector('[data-mc-firmware-output]');
        if (!pre) return;
        pre.hidden = !pre.hidden;
        button.textContent = pre.hidden ? 'Show output' : 'Hide output';
    }

    _appendMcFirmwareOutput(text) {
        const pre = this._root.querySelector('[data-mc-firmware-output]');
        if (!pre || !text) return;
        pre.textContent = pre.textContent ? `${pre.textContent}\n${text}` : text;
        pre.scrollTop = pre.scrollHeight;
    }

    async _flashMeshcoreFirmware() {
        const boardSelect = this._root.querySelector('[data-mc-firmware-board]');
        const deviceSelect = this._root.querySelector('[data-mc-firmware-device]');
        const tagSelect = this._root.querySelector('[data-mc-firmware-tag]');
        const flavorSelect = this._root.querySelector('[data-mc-firmware-flavor]');
        const board = boardSelect?.value;
        const port = deviceSelect?.value;
        if (!board || !port) return;
        const boardLabel = boardSelect.options[boardSelect.selectedIndex]?.text || board;
        const deviceLabel = deviceSelect.options[deviceSelect.selectedIndex]?.text || port;
        const tag = tagSelect?.value || '';
        const flavor = flavorSelect?.value || 'usb';
        const flavorLabel = flavor === 'ble' ? 'BLE' : 'USB';

        const ok = await window.confirmModal({
            label: 'Flash MeshCore firmware',
            description: `Erase the ENTIRE flash on "${deviceLabel}" and write official `
                + `MeshCore companion firmware (${flavorLabel}, ${tag || 'latest'}) for `
                + `${boardLabel}? This replaces whatever is currently on the board -- `
                + 'not reversible from here.',
        });
        if (!ok) return;

        const status = this._root.querySelector('[data-mc-firmware-status]');
        const flashBtn = this._root.querySelector('[data-mc-firmware-flash]');
        const outputPre = this._root.querySelector('[data-mc-firmware-output]');

        flashBtn.disabled = true;
        status.dataset.kind = 'pending';
        status.textContent = `Flashing ${deviceLabel}…`;
        if (outputPre) outputPre.textContent = '';
        this._appendMcFirmwareOutput(`# Flashing ${boardLabel} (${flavorLabel}, ${tag || 'latest'}) onto ${port}…`);

        let finalResult = null;
        try {
            finalResult = await window.UpdateStreamClient.postNdjson(
                '/api/config/meshcore/firmware/flash/stream',
                { board, port, tag, flavor },
                (event) => {
                    if (event.type === 'started' && Array.isArray(event.cmd)) {
                        this._appendMcFirmwareOutput(`$ ${event.cmd.join(' ')}`);
                    } else if (event.type === 'line') {
                        this._appendMcFirmwareOutput(event.text);
                    }
                },
            );
        } catch (err) {
            status.dataset.kind = 'error';
            status.textContent = `Request failed: ${err.message || err}`;
            this._appendMcFirmwareOutput(`! ${err.message || err}`);
            flashBtn.disabled = false;
            return;
        }

        const success = !!(finalResult && finalResult.success);
        status.dataset.kind = success ? 'success' : 'error';
        status.textContent = success
            ? 'Flashed.'
            : `Failed (exit code ${finalResult ? finalResult.returncode : '?'}). See output below.`;
        if (!success && outputPre) outputPre.hidden = false;
        const toggleBtn = this._root.querySelector('[data-mc-firmware-toggle-output]');
        if (toggleBtn && outputPre) {
            toggleBtn.textContent = outputPre.hidden ? 'Show output' : 'Hide output';
        }

        flashBtn.disabled = false;
        if (success) await this._api.refresh();
    }

    _esc(str) {
        const el = document.createElement('span');
        el.textContent = str == null ? '' : String(str);
        return el.innerHTML;
    }
}

window.FirmwareConfigCard = FirmwareConfigCard;
