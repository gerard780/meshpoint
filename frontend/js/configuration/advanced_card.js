/**
 * Configuration → Advanced card.
 *
 * Storage retention only. Radio spectral-scan tuning moved to
 * Configuration → Radio (RadioAdvancedConfigCard); relay enable/rate
 * live on Transmit; MeshCore USB on Configuration → MeshCore.
 */

class AdvancedConfigCard {
    constructor(api) {
        this._api = api;
        this._root = null;
    }

    mount(root) {
        this._root = root;
        this._root.innerHTML = `
            <div class="cfg-section" data-adv-root>
                <article class="cfg-card">
                    <header class="cfg-card__head">
                        <h3 class="cfg-card__title">Storage</h3>
                        <p class="cfg-card__hint">Local SQLite retention on the SD card.</p>
                    </header>
                    <form class="cfg-form" data-storage-form>
                        <label class="cfg-field">
                            <span class="cfg-field__label">Max packets retained</span>
                            <input class="cfg-field__input" type="number" min="1000"
                                   max="10000000" data-storage-max>
                            <span class="cfg-field__hint">Raw captured RF packets (Meshtastic/MeshCore/LoRaWAN).</span>
                        </label>
                        <label class="cfg-field">
                            <span class="cfg-field__label">Max telemetry rows retained</span>
                            <input class="cfg-field__input" type="number" min="1000"
                                   max="10000000" data-storage-max-telemetry>
                            <span class="cfg-field__hint">Battery/voltage/temperature history (node drawer and Repeater Trends charts).</span>
                        </label>
                        <label class="cfg-field">
                            <span class="cfg-field__label">Cleanup interval (seconds)</span>
                            <input class="cfg-field__input" type="number" min="60" max="86400"
                                   data-storage-cleanup>
                        </label>
                        <div class="cfg-card__actions">
                            <button class="terminal-button terminal-button--primary"
                                    type="submit">Save storage</button>
                        </div>
                        <p class="cfg-status" data-storage-status aria-live="polite"></p>
                    </form>
                </article>
            </div>
        `;
        this._storageForm = this._root.querySelector('[data-storage-form]');
        this._storageForm.addEventListener('submit', (e) => this._saveStorage(e));
    }

    render(config) {
        const storage = config.storage || {};
        this._setVal('[data-storage-max]', storage.max_packets_retained);
        this._setVal('[data-storage-max-telemetry]', storage.max_telemetry_retained);
        this._setVal('[data-storage-cleanup]', storage.cleanup_interval_seconds);
    }

    _setVal(sel, v) {
        const el = this._root.querySelector(sel);
        if (el && v != null) el.value = v;
    }

    async _saveStorage(event) {
        event.preventDefault();
        const status = this._root.querySelector('[data-storage-status]');
        status.dataset.kind = 'pending';
        status.textContent = 'Saving…';
        const result = await this._api.put('/api/config/storage', {
            max_packets_retained: Number(
                this._root.querySelector('[data-storage-max]').value,
            ),
            max_telemetry_retained: Number(
                this._root.querySelector('[data-storage-max-telemetry]').value,
            ),
            cleanup_interval_seconds: Number(
                this._root.querySelector('[data-storage-cleanup]').value,
            ),
        });
        if (result) {
            status.dataset.kind = 'success';
            status.textContent = 'Saved.';
            if (result.restart_required) {
                this._api.signalRestart('Storage updated.');
            } else {
                this._api.toast('Storage updated.');
            }
            this._api.refresh();
        } else {
            status.dataset.kind = 'error';
            status.textContent = 'Save failed.';
        }
    }
}

window.AdvancedConfigCard = AdvancedConfigCard;
