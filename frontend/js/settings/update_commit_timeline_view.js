/**
 * Unified channel-tip commit timeline for Settings → Updates.
 *
 * One list: tip of origin/<branch>. Commits not yet on the install
 * are marked NEW so Apply feels like a clear next step.
 */

class UpdateCommitTimelineView {
    constructor(rootEl, listEl) {
        this.root = rootEl;
        this.list = listEl;
        this.titleEl = rootEl
            ? rootEl.querySelector('[data-update-commits-title]')
            : null;
        this.badgeEl = rootEl
            ? rootEl.querySelector('[data-update-commits-badge]')
            : null;
        this.footEl = rootEl
            ? rootEl.querySelector('[data-update-commits-foot]')
            : null;
    }

    clear() {
        if (this.list) this.list.textContent = '';
        if (this.badgeEl) {
            this.badgeEl.hidden = true;
            this.badgeEl.textContent = '';
        }
        if (this.footEl) {
            this.footEl.hidden = true;
            this.footEl.textContent = '';
        }
        if (this.root) {
            this.root.hidden = true;
            this.root.dataset.state = '';
        }
    }

    render(status) {
        if (!this.root || !this.list) return;
        const commits = (status && status.remote_commits) || [];
        this.list.textContent = '';
        if (!commits.length) {
            this.clear();
            return;
        }

        const behind = Number(status && status.commits_behind) || 0;
        const incomingShas = this._incomingShaSet(status);
        const shown = commits.slice(0, 5);
        let newCount = 0;

        shown.forEach((c, index) => {
            const isNew = this._isIncoming(c.sha, incomingShas);
            if (isNew) newCount += 1;
            this.list.appendChild(this._buildRow(c, isNew, index));
        });

        this._renderChrome(status, behind, newCount, shown.length);
        this.root.hidden = false;
        this.root.dataset.state = behind > 0 ? 'behind' : 'current';
    }

    _buildRow(commit, isNew, index) {
        const li = document.createElement('li');
        li.className = 'update-history__row';
        if (isNew) {
            li.classList.add('update-history__row--new');
            li.style.setProperty('--row-stagger', `${index * 45}ms`);
        } else {
            li.classList.add('update-history__row--seen');
        }

        const rail = document.createElement('span');
        rail.className = 'update-history__rail';
        rail.setAttribute('aria-hidden', 'true');
        li.appendChild(rail);

        const body = document.createElement('div');
        body.className = 'update-history__body';

        const top = document.createElement('div');
        top.className = 'update-history__topline';

        const sha = document.createElement('code');
        sha.className = 'update-history__sha';
        sha.textContent = commit.sha || '';
        top.appendChild(sha);

        if (isNew) {
            const pill = document.createElement('span');
            pill.className = 'update-history__pill';
            pill.textContent = 'NEW';
            top.appendChild(pill);
        }

        const when = document.createElement('span');
        when.className = 'update-history__when';
        when.textContent = this._formatCommitTime(commit.committed_at);
        top.appendChild(when);
        body.appendChild(top);

        const subject = document.createElement('p');
        subject.className = 'update-history__subject';
        subject.textContent = commit.subject || '';
        body.appendChild(subject);

        li.appendChild(body);
        return li;
    }

    _renderChrome(status, behind, newCount, shownCount) {
        if (this.titleEl) {
            this.titleEl.textContent = behind > 0
                ? 'Ready to land'
                : 'On this channel';
        }
        if (this.badgeEl) {
            if (behind > 0) {
                this.badgeEl.hidden = false;
                this.badgeEl.textContent = behind === 1
                    ? '1 commit waiting'
                    : `${behind} commits waiting`;
            } else {
                this.badgeEl.hidden = false;
                this.badgeEl.textContent = 'Up to date';
            }
        }
        if (this.footEl) {
            if (behind > shownCount) {
                this.footEl.hidden = false;
                const more = behind - shownCount;
                this.footEl.textContent =
                    `+${more} more on Apply · hit Apply update when ready.`;
            } else if (behind > 0) {
                this.footEl.hidden = false;
                this.footEl.textContent = newCount === 1
                    ? 'One fresh commit. Apply update to pull it in.'
                    : `${newCount || behind} fresh commits. Apply update to pull them in.`;
            } else {
                this.footEl.hidden = false;
                this.footEl.textContent =
                    'Tip of the selected channel. Nothing waiting.';
            }
        }
    }

    _incomingShaSet(status) {
        const set = new Set();
        const list = (status && status.incoming_commits) || [];
        list.forEach((c) => {
            const sha = (c && c.sha) ? String(c.sha).toLowerCase() : '';
            if (sha) set.add(sha);
        });
        return set;
    }

    _isIncoming(sha, incomingShas) {
        if (!sha || !incomingShas.size) return false;
        const needle = String(sha).toLowerCase();
        if (incomingShas.has(needle)) return true;
        for (const incoming of incomingShas) {
            if (incoming.startsWith(needle) || needle.startsWith(incoming)) {
                return true;
            }
        }
        return false;
    }

    _formatCommitTime(iso) {
        if (!iso) return '--';
        const d = new Date(iso);
        if (Number.isNaN(d.getTime())) return '--';
        try {
            return d.toLocaleString(undefined, {
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
            });
        } catch (_e) {
            return d.toISOString().slice(0, 16).replace('T', ' ');
        }
    }
}

window.UpdateCommitTimelineView = UpdateCommitTimelineView;
