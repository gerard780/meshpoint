/**
 * Configuration → Firmware page: MeshCore card.
 *
 * Standalone home for "flash a spare board" actions -- previously each
 * protocol's own Configuration page carried its own firmware-flash card
 * buried among that protocol's actual settings, even though flashing a
 * board is a different kind of action (prep new/spare hardware) than
 * configuring an already-assigned companion. This is the first (and
 * top) card here, moved from meshcore_card.js, drives
 * src/api/routes/meshcore_firmware_routes.py. Meshtastic's card sits
 * below it (meshtastic_firmware_card.js, moved from serial_card.js),
 * Credit: javastraat/meshpoint 85fb576 (erase default OFF).
 */

class MeshcoreFirmwareConfigCard {
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
                            Flash official companion firmware from GitHub.
                            Leave erase off for upgrades; turn it on for a blank board.
                        </p>
                        <div class="cfg-firmware-installed" data-mc-firmware-installed aria-live="polite">
                            <span class="cfg-firmware-installed__label">Installed</span>
                            <span class="cfg-firmware-installed__version">Checking…</span>
                            <span class="cfg-firmware-installed__meta"></span>
                        </div>
                    </header>
                    <label class="cfg-field cfg-firmware-field">
                        <span class="cfg-field__label">Version</span>
                        <select class="cfg-field__input" data-mc-firmware-tag></select>
                        <button class="terminal-button cfg-firmware-rescan" type="button" data-mc-rescan-releases
                                title="Re-check MeshCore's GitHub releases for a newly-published version">
                            ↻ Refresh
                        </button>
                    </label>
                    <label class="cfg-field cfg-firmware-field">
                        <span class="cfg-field__label">Flavor</span>
                        <select class="cfg-field__input" data-mc-firmware-flavor>
                            <option value="usb">USB (dashboard)</option>
                            <option value="ble">BLE (phone app)</option>
                        </select>
                    </label>
                    <label class="cfg-field cfg-firmware-field">
                        <span class="cfg-field__label">Board</span>
                        <select class="cfg-field__input" data-mc-firmware-board>
                            <option value="">Loading boards…</option>
                        </select>
                    </label>
                    <label class="cfg-field cfg-firmware-field">
                        <span class="cfg-field__label">Device to flash</span>
                        <select class="cfg-field__input" data-mc-firmware-device></select>
                        <button class="terminal-button cfg-firmware-rescan" type="button" data-mc-rescan-usb
                                title="Re-scan connected USB devices">
                            ↻ Rescan USB
                        </button>
                    </label>
                    <label class="cfg-field cfg-field--toggle cfg-firmware-board-field" data-mc-erase-all-wrap>
                        <input type="checkbox" data-mc-erase-all>
                        <span class="cfg-field__label">Erase everything (wipes board settings)</span>
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
        // Board list depends on which release+flavor is selected (a real
        // difference -- companion-v1.16.0 has 29 esptool-flashable boards
        // for USB vs. 32 for BLE, not the same set), so re-fetch it
        // whenever either changes rather than only once at mount.
        this._root.querySelector('[data-mc-firmware-tag]')
            .addEventListener('change', () => this._loadMcFirmwareTargets());
        this._root.querySelector('[data-mc-firmware-flavor]')
            .addEventListener('change', () => this._loadMcFirmwareTargets());
        this._root.querySelector('[data-mc-firmware-board]')
            .addEventListener('change', () => this._updateFlashButtonState());
        this._root.querySelector('[data-mc-rescan-releases]')
            .addEventListener('click', (e) => this._rescanReleases(e.currentTarget));
        this._root.querySelector('[data-mc-rescan-usb]')
            .addEventListener('click', (e) => this._rescanUsb(e.currentTarget));

        this._loadMcFirmwareReleases();
        this._loadMcFirmwareTargets();
        this._refreshSerialPortsList();
        this._loadInstalledFirmware();
    }

    render(config) {
        this._portUsage = this._buildPortUsageMap(config);
    }

    async _loadInstalledFirmware() {
        const root = this._root?.querySelector('[data-mc-firmware-installed]');
        if (!root) return;
        const versionEl = root.querySelector('.cfg-firmware-installed__version');
        const metaEl = root.querySelector('.cfg-firmware-installed__meta');
        if (!versionEl || !metaEl) return;
        versionEl.textContent = 'Checking…';
        metaEl.textContent = '';
        // ConfigurationPanel._api.get returns the JSON body, or null on error.
        const data = await this._api.get('/api/config/meshcore/firmware/installed');
        if (!data) {
            versionEl.textContent = 'Unavailable';
            metaEl.textContent = 'Could not query companion';
            return;
        }
        if (!data.connected) {
            versionEl.textContent = 'Not connected';
            metaEl.textContent = '';
            return;
        }
        const version = (data.version || '').trim();
        const model = (data.model || '').trim();
        const build = (data.build || '').trim();
        const port = this._shortPortLabel(data.port);
        if (!version && !model) {
            versionEl.textContent = 'Connected';
            metaEl.textContent = port
                ? `${port} · version not reported`
                : 'Version not reported';
            return;
        }
        versionEl.textContent = version || model || 'Connected';
        const meta = [];
        if (version && model) meta.push(model);
        if (build) meta.push(`built ${build}`);
        if (port) meta.push(port);
        metaEl.textContent = meta.join(' · ');
    }

    _shortPortLabel(port) {
        if (!port) return '';
        const raw = String(port);
        const tty = raw.match(/tty(?:USB|ACM|AMA)\d+/i);
        if (tty) return tty[0];
        const base = raw.split('/').pop() || '';
        if (base.startsWith('tty')) return base;
        if (base.startsWith('platform-') || base.includes('pci-')) return 'USB';
        return base;
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
        const mcList = Array.isArray(cap.meshcore_usb)
            ? cap.meshcore_usb
            : (cap.meshcore_usb ? [cap.meshcore_usb] : []);
        mcList.forEach((c) => {
            if (c && c.serial_port) usage[c.serial_port] = c.label ? `MeshCore ${c.label}` : 'MeshCore';
        });
        (Array.isArray(cap.serial) ? cap.serial : []).forEach((d) => {
            if (d.serial_port) usage[d.serial_port] = d.label ? `Serial ${d.label}` : 'Serial';
        });
                return usage;
    }

    /** Live USB-serial enumeration for the device picker (same endpoint
     * meshcore_card.js's own companion port datalist uses). Re-fetched
     * whenever this page is mounted -- unlike meshcore_card.js's copy,
     * there's no periodic dashboard-poll render() driving this page to
     * naturally pick up newly-plugged devices, so the "↻ Rescan USB"
     * button below is what covers a device plugged in after landing on
     * this page instead of needing a full reload. */
    async _refreshSerialPortsList() {
        const result = await this._api.get('/api/config/serial-ports');
        const ports = (result && Array.isArray(result.ports)) ? result.ports : [];
        this._enumeratedPorts = ports;
        this._renderMcFirmwareDevicePicker();
    }

    /** "↻ Rescan USB" click handler -- same button/behavior as
     * meshcore_card.js's own copy (disable + "Scanning…" while in
     * flight), just re-running this page's own fetch instead. */
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

    /** Board choices for the Board dropdown, derived live from whichever
     * release+flavor is currently selected. Re-fetches on every
     * Version/Flavor change (USB vs BLE board sets differ). Plain
     * ``<select>`` (not datalist) so mobile and desktop both pick the
     * exact asset id (e.g. Heltec_v3) without case/underscore typos. */
    async _loadMcFirmwareTargets() {
        const select = this._root.querySelector('[data-mc-firmware-board]');
        if (!select) return;

        const previous = select.value;
        const tag = this._root.querySelector('[data-mc-firmware-tag]')?.value || '';
        const flavor = this._root.querySelector('[data-mc-firmware-flavor]')?.value || 'usb';
        const params = new URLSearchParams();
        if (tag) params.set('tag', tag);
        params.set('flavor', flavor);

        const result = await this._api.get(`/api/config/meshcore/firmware/targets?${params}`);
        const boards = (result && Array.isArray(result.boards)) ? result.boards : [];
        this._boards = boards;

        if (boards.length === 0) {
            select.innerHTML = '<option value="">No boards for this version/flavor</option>';
        } else {
            select.innerHTML = [
                '<option value="">Select a board…</option>',
                ...boards.map((b) => (
                    `<option value="${this._esc(b.board)}">${this._esc(b.label)}</option>`
                )),
            ].join('');
            if (previous && boards.some((b) => b.board === previous)) {
                select.value = previous;
            }
        }
        this._updateFlashButtonState();
    }

    /** Flash is only enabled once BOTH a real board and a real device are
     * selected -- board and device availability are checked by two
     * independent async loads (targets vs. serial-ports), so this is the
     * one place that reconciles them instead of each overwriting the
     * other's disabled/title state. */
    _updateFlashButtonState() {
        const flashBtn = this._root.querySelector('[data-mc-firmware-flash]');
        if (!flashBtn) return;
        const boardInput = this._root.querySelector('[data-mc-firmware-board]');
        const deviceSelect = this._root.querySelector('[data-mc-firmware-device]');
        const hasPorts = (this._enumeratedPorts || []).length > 0;
        const hasBoard = !!(boardInput && boardInput.value);
        if (!hasPorts) {
            flashBtn.disabled = true;
            flashBtn.title = 'No USB-serial device connected to flash.';
        } else if (!hasBoard) {
            flashBtn.disabled = true;
            flashBtn.title = 'Pick a board first.';
        } else {
            flashBtn.disabled = false;
            flashBtn.title = '';
        }
    }

    /** Looks up a board's friendly label from the last-loaded list, for
     * the confirm-modal/status text -- falls back to a lightly cleaned
     * version of the raw value if it's somehow not in that list (e.g. a
     * stale value left over from before a Version/Flavor change). */
    _boardLabel(board) {
        const match = (this._boards || []).find((b) => b.board === board);
        return match ? match.label : board.replace(/_/g, ' ');
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
        if (!select) return;

        const ports = (this._enumeratedPorts || []).filter((p) => p.vid);
        const usage = this._portUsage || {};

        if (ports.length === 0) {
            select.innerHTML = '<option value="">No USB-serial devices detected</option>';
        } else {
            const previous = select.value;
            select.innerHTML = ports.map((p) => (
                `<option value="${this._esc(p.stable_path || p.device)}">${this._esc(this._portOptionLabel(p, usage))}</option>`
            )).join('');
            if (previous && ports.some((p) => (p.stable_path || p.device) === previous)) {
                select.value = previous;
            }
        }
        this._updateFlashButtonState();
    }

    /** Version pulldown for the MeshCore firmware card, from the last 10
     * companion- tagged releases (GET .../releases), newest first.
     * "Latest" (empty tag, the default) covers routine flashing; this
     * is for the deliberate case -- pinning an older or specific
     * version, e.g. to match what another companion is already
     * running. Fetched once at mount; the "↻ Refresh" button below
     * covers a release published while already on this page. */
    async _loadMcFirmwareReleases() {
        const select = this._root.querySelector('[data-mc-firmware-tag]');
        if (!select) return;
        const result = await this._api.get('/api/config/meshcore/firmware/releases');
        const releases = (result && Array.isArray(result.releases)) ? result.releases : [];
        const previous = select.value;
        const options = ['<option value="">Latest</option>'];
        releases.forEach((r) => {
            options.push(`<option value="${this._esc(r.tag)}">${this._esc(r.tag)}</option>`);
        });
        select.innerHTML = options.join('');
        if (previous && releases.some((r) => r.tag === previous)) select.value = previous;
    }

    /** "↻ Refresh" click handler for Version -- re-checks GitHub for a
     * newly-published release (a one-time fetch at mount otherwise, per
     * _loadMcFirmwareReleases' own doc comment). Also re-runs the Board
     * fetch: if "Latest" is selected and a new release just landed, the
     * board list fetched at mount time is for the now-stale "latest",
     * not the one this just found. */
    async _rescanReleases(button) {
        const original = button.textContent;
        button.disabled = true;
        button.textContent = 'Checking…';
        try {
            await this._loadMcFirmwareReleases();
            await this._loadMcFirmwareTargets();
        } finally {
            button.textContent = original;
            button.disabled = false;
        }
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
        const boardInput = this._root.querySelector('[data-mc-firmware-board]');
        const deviceSelect = this._root.querySelector('[data-mc-firmware-device]');
        const tagSelect = this._root.querySelector('[data-mc-firmware-tag]');
        const flavorSelect = this._root.querySelector('[data-mc-firmware-flavor]');
        const eraseAllInput = this._root.querySelector('[data-mc-erase-all]');
        const board = (boardInput?.value || '').trim();
        const port = deviceSelect?.value;
        const eraseAll = eraseAllInput ? eraseAllInput.checked : false;
        if (!board || !port) return;

        const status = this._root.querySelector('[data-mc-firmware-status]');
        if (!(this._boards || []).some((b) => b.board === board)) {
            if (status) {
                status.dataset.kind = 'error';
                status.textContent = 'Pick a board from the list.';
            }
            return;
        }

        const boardLabel = this._boardLabel(board);
        const deviceLabel = deviceSelect.options[deviceSelect.selectedIndex]?.text || port;
        const tag = tagSelect?.value || '';
        const flavor = flavorSelect?.value || 'usb';
        const flavorLabel = flavor === 'ble' ? 'BLE' : 'USB';

        const ok = await window.confirmModal({
            label: 'Flash MeshCore firmware',
            description: eraseAll
                ? `Erase the ENTIRE flash on "${deviceLabel}" and write official MeshCore `
                    + `companion firmware (${flavorLabel}, ${tag || 'latest'}) for ${boardLabel}? `
                    + 'This replaces whatever is currently on the board -- not reversible from here.'
                : `Write official MeshCore companion firmware (${flavorLabel}, ${tag || 'latest'}) `
                    + `for ${boardLabel} to "${deviceLabel}", keeping its existing identity, `
                    + 'contacts, and channels? Only do this for a board already running MeshCore '
                    + '-- on anything else, the result is unpredictable.',
        });
        if (!ok) return;

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
                { board, port, tag, flavor, erase_all: eraseAll },
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
        if (success) {
            await this._api.refresh();
            await this._loadInstalledFirmware();
        }
    }

    _esc(str) {
        const el = document.createElement('span');
        el.textContent = str == null ? '' : String(str);
        return el.innerHTML;
    }
}

window.MeshcoreFirmwareConfigCard = MeshcoreFirmwareConfigCard;
