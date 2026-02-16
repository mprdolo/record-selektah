/* ===========================
   Record Selektah — Frontend
   =========================== */

(function () {
    'use strict';

    // --- State ---
    let currentAlbum = null;
    let historyPage = 1;
    let historyTotal = 0;
    let historyPerPage = 20;

    // --- DOM refs ---
    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    const welcomeState = $('#welcome-state');
    const selectionArea = $('#selection-area');
    const selectionEmpty = $('#selection-empty');
    const selectionResult = $('#selection-result');

    const albumCover = $('#album-cover');
    const albumArtist = $('#album-artist');
    const albumTitle = $('#album-title');
    const albumMeta = $('#album-meta');
    const albumRank = $('#album-rank');
    const albumDiscogsLink = $('#album-discogs-link');

    const btnSelectFirst = $('#btn-select-first');
    const btnSelectNext = $('#btn-select-next');
    const btnPrevious = $('#btn-previous');
    const btnListened = $('#btn-listened');
    const btnSkipped = $('#btn-skipped');
    const btnExclude = $('#btn-exclude');

    const statsTotal = $('#stat-total');
    const statsRanked = $('#stat-ranked');
    const statsListened = $('#stat-listened');
    const statsExcluded = $('#stat-excluded');

    const historyList = $('#history-list');
    const historyEmpty = $('#history-empty');
    const btnLoadMore = $('#btn-load-more');

    const btnSync = $('#btn-sync');
    const syncModal = $('#sync-modal');
    const btnSyncClose = $('#btn-sync-close');
    const btnSyncDiscogs = $('#btn-sync-discogs');
    const btnSyncBigboard = $('#btn-sync-bigboard');
    const btnSyncMasterYears = $('#btn-sync-master-years');
    const syncProgress = $('#sync-progress');
    const syncProgressFill = $('#sync-progress-fill');
    const syncMessage = $('#sync-message');

    const confirmModal = $('#confirm-modal');
    const confirmMessage = $('#confirm-message');
    const btnConfirmCancel = $('#btn-confirm-cancel');
    const btnConfirmOk = $('#btn-confirm-ok');

    const btnWelcomeSync = $('#btn-welcome-sync');

    const toastContainer = $('#toast-container');

    // --- API helpers ---

    async function api(url, method = 'GET', body = null) {
        try {
            const opts = { method };
            if (body !== null) {
                opts.headers = { 'Content-Type': 'application/json' };
                opts.body = JSON.stringify(body);
            }
            const resp = await fetch(url, opts);
            const data = await resp.json();
            if (!resp.ok || !data.success) {
                throw new Error(data.message || `Request failed (${resp.status})`);
            }
            return data;
        } catch (err) {
            if (err.message.includes('Failed to fetch')) {
                throw new Error('Could not connect to the server. Is it running?');
            }
            throw err;
        }
    }

    // --- Toast ---

    function showToast(message, type = 'info') {
        const el = document.createElement('div');
        el.className = 'toast' + (type === 'error' ? ' toast-error' : '');
        el.textContent = message;
        toastContainer.appendChild(el);
        setTimeout(() => {
            el.classList.add('toast-out');
            setTimeout(() => el.remove(), 300);
        }, 3000);
    }

    // --- Modal helpers ---

    function openModal(modal) {
        modal.classList.remove('hidden');
        // Trigger reflow then add visible for transition
        modal.offsetHeight;
        modal.classList.add('visible');
    }

    function closeModal(modal) {
        modal.classList.remove('visible');
        setTimeout(() => modal.classList.add('hidden'), 300);
    }

    // --- Stats ---

    async function loadStats() {
        try {
            const resp = await api('/api/stats');
            const s = resp.data;
            statsTotal.textContent = s.total_albums.toLocaleString();
            statsRanked.textContent = s.big_board_ranked.toLocaleString();
            statsListened.textContent = s.unique_listened.toLocaleString();
            statsExcluded.textContent = s.excluded.toLocaleString();

            // Show welcome if no albums
            if (s.total_albums === 0) {
                welcomeState.classList.remove('hidden');
                selectionArea.classList.add('hidden');
            } else {
                welcomeState.classList.add('hidden');
                selectionArea.classList.remove('hidden');
            }
        } catch (err) {
            console.error('Failed to load stats:', err);
        }
    }

    // --- Album selection ---

    async function selectNextAlbum() {
        btnSelectFirst.disabled = true;
        btnSelectNext.disabled = true;

        try {
            const resp = await api('/api/next');
            currentAlbum = resp.data;
            displayAlbum(currentAlbum);
        } catch (err) {
            showToast(err.message, 'error');
        } finally {
            btnSelectFirst.disabled = false;
            btnSelectNext.disabled = false;
        }
    }

    async function goToPrevious() {
        if (!currentAlbum || !currentAlbum.listen_id) return;
        btnPrevious.disabled = true;

        try {
            const resp = await api(`/api/previous?before_listen_id=${currentAlbum.listen_id}`);
            currentAlbum = resp.data;
            displayAlbum(currentAlbum);
        } catch (err) {
            showToast(err.message, 'error');
        } finally {
            btnPrevious.disabled = false;
        }
    }

    function displayAlbum(album) {
        selectionEmpty.classList.add('hidden');
        selectionResult.classList.remove('hidden');

        // Reset action button states
        btnListened.classList.remove('active');
        btnSkipped.classList.remove('active');
        btnListened.disabled = false;
        btnSkipped.disabled = false;
        btnExclude.disabled = false;

        // If this album already has a status (from Previous), reflect it
        if (album.did_listen) {
            btnListened.classList.add('active');
            btnListened.disabled = true;
            btnSkipped.disabled = true;
        } else if (album.skipped) {
            btnSkipped.classList.add('active');
            btnListened.disabled = true;
            btnSkipped.disabled = true;
        }

        // Cover image with fade-in
        albumCover.classList.remove('loaded');
        albumCover.src = '';
        if (album.cover_image_url) {
            albumCover.onload = () => albumCover.classList.add('loaded');
            albumCover.onerror = () => {
                albumCover.src = '';
                albumCover.classList.add('loaded');
            };
            albumCover.src = album.cover_image_url;
        }

        // Text
        albumArtist.textContent = album.artist;
        albumTitle.textContent = album.title;

        // Meta line: year · genres
        const parts = [];
        if (album.display_year) parts.push(album.display_year);
        if (album.genres && album.genres.length) parts.push(album.genres.join(', '));
        albumMeta.textContent = parts.join(' · ');

        // Big Board rank
        if (album.big_board_rank) {
            albumRank.textContent = 'Big Board: #' + album.big_board_rank;
            albumRank.classList.remove('hidden');
        } else {
            albumRank.classList.add('hidden');
        }

        // Discogs link
        if (album.discogs_url) {
            albumDiscogsLink.href = album.discogs_url;
            albumDiscogsLink.classList.remove('hidden');
        } else {
            albumDiscogsLink.classList.add('hidden');
        }
    }

    // --- Actions ---

    async function markListened() {
        if (!currentAlbum) return;
        btnListened.disabled = true;
        btnSkipped.disabled = true;
        try {
            await api(`/api/listened/${currentAlbum.album_id}`, 'POST');
            btnListened.classList.add('active');
            showToast('Marked as listened');
            loadStats();
            loadHistory(true);
        } catch (err) {
            showToast(err.message, 'error');
            btnListened.disabled = false;
            btnSkipped.disabled = false;
        }
    }

    async function markSkipped() {
        if (!currentAlbum) return;
        btnListened.disabled = true;
        btnSkipped.disabled = true;
        try {
            await api(`/api/skipped/${currentAlbum.album_id}`, 'POST');
            btnSkipped.classList.add('active');
            showToast('Marked as skipped');
            loadHistory(true);
        } catch (err) {
            showToast(err.message, 'error');
            btnListened.disabled = false;
            btnSkipped.disabled = false;
        }
    }

    function promptExclude() {
        if (!currentAlbum) return;
        confirmMessage.textContent =
            `Exclude "${currentAlbum.artist} — ${currentAlbum.title}" from future selections?`;
        openModal(confirmModal);
    }

    async function confirmExclude() {
        if (!currentAlbum) return;
        closeModal(confirmModal);
        try {
            await api(`/api/exclude/${currentAlbum.album_id}`, 'POST');
            showToast('Album excluded');
            loadStats();
            // Auto-select next
            selectNextAlbum();
        } catch (err) {
            showToast(err.message, 'error');
        }
    }

    // --- History ---

    async function loadHistory(reset = false) {
        if (reset) {
            historyPage = 1;
        }

        try {
            const resp = await api(`/api/history?page=${historyPage}&per_page=${historyPerPage}`);
            const data = resp.data;
            historyTotal = data.total;

            if (reset) {
                // Clear existing items (keep the empty message element)
                historyList.querySelectorAll('.history-item').forEach(el => el.remove());
            }

            if (data.history.length === 0 && historyPage === 1) {
                historyEmpty.classList.remove('hidden');
                btnLoadMore.classList.add('hidden');
                return;
            }

            historyEmpty.classList.add('hidden');

            data.history.forEach(item => {
                const el = createHistoryItem(item);
                historyList.appendChild(el);
            });

            // Show/hide load more
            const loaded = historyList.querySelectorAll('.history-item').length;
            if (loaded < historyTotal) {
                btnLoadMore.classList.remove('hidden');
            } else {
                btnLoadMore.classList.add('hidden');
            }
        } catch (err) {
            console.error('Failed to load history:', err);
        }
    }

    function createHistoryItem(item) {
        const el = document.createElement('div');
        el.className = 'history-item clickable';

        const date = new Date(item.selected_at + 'Z');
        const dateStr = date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });

        let statusClass = 'pending';
        let statusText = 'Pending';
        if (item.did_listen) {
            statusClass = 'listened';
            statusText = 'Listened';
        } else if (item.skipped) {
            statusClass = 'skipped';
            statusText = 'Skipped';
        }

        const yearStr = item.display_year ? ` (${item.display_year})` : '';

        el.innerHTML = `
            <img class="history-cover" src="${escapeAttr(item.cover_image_url || '')}" alt=""
                 onerror="this.style.visibility='hidden'">
            <div class="history-details">
                <div class="history-album">${esc(item.artist)} — ${esc(item.title)}</div>
                <div class="history-sub">${esc(dateStr)}${esc(yearStr)}</div>
            </div>
            <span class="history-status ${statusClass}">${statusText}</span>
        `;

        el.addEventListener('click', () => openDetailCard(item.album_id));

        return el;
    }

    // --- Sync ---

    let syncPollTimer = null;

    function openSyncModal() {
        openModal(syncModal);
    }

    function closeSyncModal() {
        closeModal(syncModal);
    }

    async function startSync(type) {
        const endpoints = {
            discogs: '/api/sync/discogs',
            bigboard: '/api/sync/bigboard',
            master_years: '/api/sync/master_years',
        };

        // Disable all sync buttons
        btnSyncDiscogs.disabled = true;
        btnSyncBigboard.disabled = true;
        btnSyncMasterYears.disabled = true;

        syncProgress.classList.remove('hidden');
        syncProgressFill.style.width = '0%';
        syncMessage.textContent = 'Starting...';

        try {
            await api(endpoints[type], 'POST');
            pollSyncStatus();
        } catch (err) {
            showToast(err.message, 'error');
            resetSyncUI();
        }
    }

    function pollSyncStatus() {
        if (syncPollTimer) clearInterval(syncPollTimer);

        syncPollTimer = setInterval(async () => {
            try {
                const resp = await api('/api/sync/status');
                const s = resp.data;

                syncMessage.textContent = s.message || 'Working...';

                if (s.total > 0) {
                    const pct = Math.round((s.current / s.total) * 100);
                    syncProgressFill.style.width = pct + '%';
                } else if (s.in_progress) {
                    // Indeterminate — pulse
                    syncProgressFill.style.width = '30%';
                }

                if (!s.in_progress) {
                    clearInterval(syncPollTimer);
                    syncPollTimer = null;
                    syncProgressFill.style.width = '100%';

                    // Refresh data
                    loadStats();
                    loadHistory(true);

                    // Re-enable buttons after a short delay
                    setTimeout(resetSyncUI, 2000);
                }
            } catch (err) {
                clearInterval(syncPollTimer);
                syncPollTimer = null;
                resetSyncUI();
            }
        }, 1500);
    }

    function resetSyncUI() {
        btnSyncDiscogs.disabled = false;
        btnSyncBigboard.disabled = false;
        btnSyncMasterYears.disabled = false;
    }

    // --- Excluded Section ---

    const btnExcludedOpen = $('#btn-excluded');
    const btnExcludedBack = $('#btn-excluded-back');
    const excludedList = $('#excluded-list');
    const excludedEmpty = $('#excluded-empty');
    const excludedCount = $('#excluded-count');
    const excludedSortSelect = $('#excluded-sort-select');
    const excludedSearchInput = $('#excluded-search');

    let excludedData = [];
    let excludedSort = 'artist';
    let excludedSearch = '';

    function openExcluded() {
        mainContent.classList.add('hidden');
        bigboardSection.classList.add('hidden');
        librarySection.classList.add('hidden');
        lstatsSection.classList.add('hidden');
        helpSection.classList.add('hidden');
        excludedSection.classList.remove('hidden');
        loadExcludedAlbums();
    }

    function closeExcluded() {
        excludedSection.classList.add('hidden');
        mainContent.classList.remove('hidden');
    }

    async function loadExcludedAlbums() {
        try {
            const resp = await api('/api/excluded');
            excludedData = resp.data;
            excludedCount.textContent = `${excludedData.length} entries`;
            renderExcluded();
        } catch (err) {
            showToast('Failed to load excluded albums', 'error');
        }
    }

    function renderExcluded() {
        excludedList.querySelectorAll('.excluded-item').forEach(el => el.remove());

        let albums = [...excludedData];

        // Sort
        if (excludedSort === 'title') {
            albums.sort((a, b) => stripArticle(a.title).toLowerCase().localeCompare(stripArticle(b.title).toLowerCase()));
        } else {
            albums.sort((a, b) => stripArticle(a.artist).toLowerCase().localeCompare(stripArticle(b.artist).toLowerCase()));
        }

        // Search filter
        if (excludedSearch) {
            const q = excludedSearch.toLowerCase();
            albums = albums.filter(a =>
                a.artist.toLowerCase().includes(q) || a.title.toLowerCase().includes(q)
            );
        }

        if (albums.length === 0) {
            excludedEmpty.textContent = excludedData.length === 0 ? 'No excluded albums.' : 'No matches found.';
            excludedEmpty.classList.remove('hidden');
            return;
        }
        excludedEmpty.classList.add('hidden');

        albums.forEach(album => {
            const el = document.createElement('div');
            el.className = 'excluded-item';
            const yearStr = album.display_year ? ` (${album.display_year})` : '';
            const genres = album.genres.length ? album.genres.join(', ') : '';
            el.innerHTML = `
                <img class="excluded-cover" src="${escapeAttr(album.cover_image_url || '')}" alt=""
                     onerror="this.style.visibility='hidden'">
                <div class="excluded-details">
                    <div class="excluded-album">${esc(album.artist)} — ${esc(album.title)}</div>
                    <div class="excluded-sub">${esc(yearStr)}${genres ? ' · ' + esc(genres) : ''}</div>
                </div>
                <button class="btn-unexclude" data-id="${album.album_id}">Un-exclude</button>
            `;
            el.querySelector('.btn-unexclude').addEventListener('click', async (e) => {
                const btn = e.currentTarget;
                btn.disabled = true;
                try {
                    await api(`/api/unexclude/${album.album_id}`, 'POST');
                    excludedData = excludedData.filter(a => a.album_id !== album.album_id);
                    showToast(`${album.artist} — ${album.title} re-included`);
                    loadStats();
                    excludedCount.textContent = `${excludedData.length} entries`;
                    renderExcluded();
                } catch (err) {
                    showToast(err.message, 'error');
                    btn.disabled = false;
                }
            });
            excludedList.appendChild(el);
        });
    }

    excludedSortSelect.addEventListener('change', () => {
        excludedSort = excludedSortSelect.value;
        renderExcluded();
    });

    excludedSearchInput.addEventListener('input', () => {
        excludedSearch = excludedSearchInput.value.trim();
        renderExcluded();
    });

    // --- Section DOM refs (shared across features) ---

    const mainContent = $('#main-content');
    const bigboardSection = $('#bigboard-section');
    const librarySection = $('#library-section');
    const lstatsSection = $('#lstats-section');
    const excludedSection = $('#excluded-section');
    const helpSection = $('#help-section');

    // --- Go Home (logo click) ---

    const logoEl = $('#logo');

    function goHome() {
        bigboardSection.classList.add('hidden');
        librarySection.classList.add('hidden');
        lstatsSection.classList.add('hidden');
        excludedSection.classList.add('hidden');
        helpSection.classList.add('hidden');
        mainContent.classList.remove('hidden');
    }

    logoEl.addEventListener('click', goHome);

    // --- Help Section ---

    const btnHelp = $('#btn-help');
    const btnHelpBack = $('#btn-help-back');

    function openHelp() {
        mainContent.classList.add('hidden');
        bigboardSection.classList.add('hidden');
        librarySection.classList.add('hidden');
        lstatsSection.classList.add('hidden');
        excludedSection.classList.add('hidden');
        helpSection.classList.remove('hidden');
    }

    function closeHelp() {
        helpSection.classList.add('hidden');
        mainContent.classList.remove('hidden');
    }

    btnHelp.addEventListener('click', (e) => {
        e.preventDefault();
        openHelp();
    });
    btnHelpBack.addEventListener('click', closeHelp);

    // --- Big Board Explorer ---

    const btnBigboard = $('#btn-bigboard');
    const btnBigboardBack = $('#btn-bigboard-back');
    const bigboardContent = $('#bigboard-content');
    const bigboardCount = $('#bigboard-count');
    const bigboardTabs = $$('.bigboard-tab');
    const bigboardFilters = $$('input[name="bb-filter"]');

    let bigboardData = [];
    let bigboardView = 'rank';
    let bigboardFilter = 'all';
    let bigboardSearch = '';
    const bigboardJump = $('#bigboard-jump');
    const bigboardSearchInput = $('#bigboard-search');

    function openBigBoard() {
        mainContent.classList.add('hidden');
        librarySection.classList.add('hidden');
        lstatsSection.classList.add('hidden');
        excludedSection.classList.add('hidden');
        helpSection.classList.add('hidden');
        bigboardSection.classList.remove('hidden');
        if (bigboardData.length === 0) {
            loadBigBoard();
        } else {
            renderBigBoard();
        }
    }

    function closeBigBoard() {
        bigboardSection.classList.add('hidden');
        mainContent.classList.remove('hidden');
    }

    async function loadBigBoard() {
        bigboardContent.innerHTML = '<p style="text-align:center;color:var(--charcoal-light);padding:40px 0;">Loading...</p>';
        try {
            const resp = await api('/api/bigboard');
            bigboardData = resp.data;
            renderBigBoard();
        } catch (err) {
            bigboardContent.innerHTML = '<p style="text-align:center;color:#c0392b;padding:40px 0;">Failed to load Big Board data.</p>';
            showToast(err.message, 'error');
        }
    }

    function getFilteredData() {
        let data = bigboardData;
        if (bigboardFilter === 'owned') data = data.filter(e => e.owned);
        if (bigboardFilter === 'unowned') data = data.filter(e => !e.owned);
        if (bigboardSearch) {
            const q = bigboardSearch.toLowerCase();
            data = data.filter(e =>
                e.artist.toLowerCase().includes(q) || e.title.toLowerCase().includes(q)
            );
        }
        return data;
    }

    function renderBigBoard() {
        const data = getFilteredData();
        const owned = bigboardData.filter(e => e.owned).length;
        bigboardCount.textContent = `${owned} owned / ${bigboardData.length} total`;

        if (bigboardView === 'rank') renderRankView(data);
        else if (bigboardView === 'decade') renderDecadeView(data);
        else if (bigboardView === 'genre') renderGenreView(data);
        else if (bigboardView === 'heatmap') renderHeatmap(data);
    }

    function getDecade(year) {
        if (!year) return 'Unknown';
        return Math.floor(year / 10) * 10 + 's';
    }

    function buildJumpNav(labels, idPrefix) {
        bigboardJump.innerHTML = '';
        bigboardJump.classList.remove('hidden');
        labels.forEach(label => {
            const btn = document.createElement('button');
            btn.className = 'bb-jump-btn';
            btn.textContent = label;
            btn.addEventListener('click', () => {
                const target = document.getElementById(idPrefix + label.replace(/[^a-zA-Z0-9]/g, '_'));
                if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
            });
            bigboardJump.appendChild(btn);
        });
    }

    function hideJumpNav() {
        bigboardJump.innerHTML = '';
        bigboardJump.classList.add('hidden');
    }

    function renderDecadeView(data) {
        const groups = {};
        data.forEach(e => {
            const decade = getDecade(e.year);
            if (!groups[decade]) groups[decade] = [];
            groups[decade].push(e);
        });

        const sortedDecades = Object.keys(groups).sort((a, b) => {
            if (a === 'Unknown') return 1;
            if (b === 'Unknown') return -1;
            return parseInt(a) - parseInt(b);
        });

        buildJumpNav(sortedDecades, 'bb-sec-');
        bigboardContent.innerHTML = '';
        sortedDecades.forEach(decade => {
            const group = groups[decade];
            group.sort((a, b) => a.rank - b.rank);
            const sectionId = 'bb-sec-' + decade.replace(/[^a-zA-Z0-9]/g, '_');
            bigboardContent.appendChild(createGroup(decade, group, sectionId));
        });
    }

    function renderGenreView(data) {
        const groups = {};
        data.forEach(e => {
            const genres = e.genres && e.genres.length ? e.genres : ['Uncategorized'];
            genres.forEach(g => {
                if (!groups[g]) groups[g] = [];
                groups[g].push(e);
            });
        });

        const sortedGenres = Object.keys(groups).sort((a, b) => {
            if (a === 'Uncategorized') return 1;
            if (b === 'Uncategorized') return -1;
            return groups[b].length - groups[a].length;
        });

        buildJumpNav(sortedGenres, 'bb-sec-');
        bigboardContent.innerHTML = '';
        sortedGenres.forEach(genre => {
            const group = groups[genre];
            group.sort((a, b) => a.rank - b.rank);
            const sectionId = 'bb-sec-' + genre.replace(/[^a-zA-Z0-9]/g, '_');
            bigboardContent.appendChild(createGroup(genre, group, sectionId));
        });
    }

    function createGroup(title, entries, sectionId) {
        const section = document.createElement('div');
        section.className = 'bb-group';
        if (sectionId) section.id = sectionId;
        section.innerHTML = `
            <h3 class="bb-group-title">${esc(title)} <span class="bb-group-count">(${entries.length})</span></h3>
            <div class="bb-grid"></div>
        `;
        const grid = section.querySelector('.bb-grid');
        entries.forEach(e => grid.appendChild(createCard(e)));
        return section;
    }

    function createCard(entry) {
        const el = document.createElement('div');
        el.className = 'bb-card clickable' + (entry.owned ? '' : ' unowned');
        if (entry.album_id) el.dataset.albumId = entry.album_id;

        const coverHtml = entry.cover_image_url
            ? `<img class="bb-cover" src="${escapeAttr(entry.cover_image_url)}" alt="" onerror="this.style.visibility='hidden'">`
            : `<div class="bb-cover-placeholder">?</div>`;

        const badgeHtml = entry.owned
            ? '<span class="bb-owned-badge">Owned</span>'
            : '';

        el.innerHTML = `
            <div class="bb-rank">${entry.rank}</div>
            ${coverHtml}
            <div class="bb-info">
                <div class="bb-artist">${esc(entry.artist)}</div>
                <div class="bb-album">${esc(entry.title)}</div>
                ${entry.year ? `<div class="bb-year">${entry.year}</div>` : ''}
            </div>
            ${badgeHtml}
        `;

        if (entry.album_id) {
            el.addEventListener('click', () => openDetailCard(entry.album_id));
        } else {
            el.addEventListener('click', () => openMatchModal(entry));
        }

        return el;
    }

    function renderHeatmap(data) {
        hideJumpNav();
        const decades = [];
        const decadeSet = new Set();
        data.forEach(e => {
            const d = getDecade(e.year);
            decadeSet.add(d);
        });

        const sortedDecades = Array.from(decadeSet).sort((a, b) => {
            if (a === 'Unknown') return 1;
            if (b === 'Unknown') return -1;
            return parseInt(a) - parseInt(b);
        });

        const tiers = ['1–100', '101–200', '201–300', '301–400', '401–500', '501–600'];
        const tierRanges = [[1,100],[101,200],[201,300],[301,400],[401,500],[501,600]];

        // Build count matrix
        const matrix = {};
        tiers.forEach(t => { matrix[t] = {}; sortedDecades.forEach(d => { matrix[t][d] = 0; }); });

        data.forEach(e => {
            const decade = getDecade(e.year);
            for (let i = 0; i < tierRanges.length; i++) {
                if (e.rank >= tierRanges[i][0] && e.rank <= tierRanges[i][1]) {
                    matrix[tiers[i]][decade]++;
                    break;
                }
            }
        });

        // Find max for color scaling
        let maxCount = 0;
        tiers.forEach(t => sortedDecades.forEach(d => {
            if (matrix[t][d] > maxCount) maxCount = matrix[t][d];
        }));

        let html = '<div class="heatmap-wrap"><table class="heatmap-table"><thead><tr><th></th>';
        sortedDecades.forEach(d => { html += `<th>${esc(d)}</th>`; });
        html += '</tr></thead><tbody>';

        tiers.forEach(tier => {
            html += `<tr><td class="heatmap-row-label">${esc(tier)}</td>`;
            sortedDecades.forEach(d => {
                const count = matrix[tier][d];
                const intensity = maxCount > 0 ? count / maxCount : 0;
                const bgColor = count === 0
                    ? 'var(--cream-dark)'
                    : `rgba(45, 90, 61, ${0.15 + intensity * 0.85})`;
                const textColor = count === 0 ? 'transparent' : '#fff';
                html += `<td class="heatmap-cell">
                    <div class="heatmap-box${count === 0 ? ' empty' : ''}"
                         style="background:${bgColor};color:${textColor}"
                         title="${count} album${count !== 1 ? 's' : ''} in ${d}, ranks ${tier}">
                        ${count}
                    </div>
                </td>`;
            });
            html += '</tr>';
        });

        html += '</tbody></table></div>';

        // Legend
        html += `<div class="heatmap-legend">
            <span>Fewer</span>
            <div class="heatmap-legend-swatch" style="background:rgba(45,90,61,0.15)"></div>
            <div class="heatmap-legend-swatch" style="background:rgba(45,90,61,0.45)"></div>
            <div class="heatmap-legend-swatch" style="background:rgba(45,90,61,0.75)"></div>
            <div class="heatmap-legend-swatch" style="background:rgba(45,90,61,1)"></div>
            <span>More</span>
        </div>`;

        bigboardContent.innerHTML = html;
    }

    // --- Album Detail Card ---

    const detailModal = $('#detail-modal');
    const detailCover = $('#detail-cover');
    const detailArtist = $('#detail-artist');
    const detailTitle = $('#detail-title');
    const detailYear = $('#detail-year');
    const detailFormat = $('#detail-format');
    const detailGenres = $('#detail-genres');
    const detailStyles = $('#detail-styles');
    const detailRank = $('#detail-rank');
    const detailPlayed = $('#detail-played');
    const detailSkipped = $('#detail-skipped');
    const detailDiscogsLink = $('#detail-discogs-link');
    const detailMasterLink = $('#detail-master-link');
    const detailNoMaster = $('#detail-no-master');
    const btnEditMaster = $('#btn-edit-master');
    const btnSetMaster = $('#btn-set-master');
    const detailMasterEdit = $('#detail-master-edit');
    const inputMasterId = $('#input-master-id');
    const btnSaveMaster = $('#btn-save-master');
    const btnCancelMaster = $('#btn-cancel-master');
    const btnRemoveMaster = $('#btn-remove-master');
    const btnDetailClose = $('#btn-detail-close');

    // Release edit refs
    const btnEditRelease = $('#btn-edit-release');
    const detailReleaseEdit = $('#detail-release-edit');
    const inputReleaseId = $('#input-release-id');
    const btnSaveRelease = $('#btn-save-release');
    const btnCancelRelease = $('#btn-cancel-release');

    let detailAlbumId = null;
    let detailCardDirty = false;

    async function openDetailCard(albumId) {
        detailAlbumId = albumId;
        detailCardDirty = false;
        detailMasterEdit.classList.add('hidden');
        detailReleaseEdit.classList.add('hidden');
        inputMasterId.value = '';
        inputReleaseId.value = '';

        try {
            const resp = await api(`/api/album/${albumId}`);
            const a = resp.data;
            populateDetailCard(a);
            openModal(detailModal);
        } catch (err) {
            showToast(err.message, 'error');
        }
    }

    function closeDetailCard() {
        closeModal(detailModal);
        if (detailCardDirty) {
            // Refresh main page album if it matches
            if (currentAlbum && currentAlbum.album_id === detailAlbumId) {
                api(`/api/album/${detailAlbumId}`).then(resp => {
                    const a = resp.data;
                    currentAlbum.cover_image_url = a.cover_image_url;
                    currentAlbum.artist = a.artist;
                    currentAlbum.title = a.title;
                    currentAlbum.display_year = a.display_year;
                    currentAlbum.genres = a.genres;
                    currentAlbum.big_board_rank = a.big_board_rank;
                    currentAlbum.discogs_url = a.discogs_url;
                    displayAlbum(currentAlbum);
                }).catch(() => {});
            }
            // Refresh history to pick up any cover/metadata changes
            loadHistory(true);
            detailCardDirty = false;
        }
    }

    function populateDetailCard(a) {
        // Force image reload by clearing src first, then setting with cache-bust
        detailCover.src = '';
        if (a.cover_image_url) {
            detailCover.src = a.cover_image_url;
        }
        detailArtist.textContent = a.artist;
        detailTitle.textContent = a.title;

        const yearParts = [];
        if (a.display_year) yearParts.push(a.display_year);
        if (a.release_year && a.release_year !== a.display_year) yearParts.push(`Release: ${a.release_year}`);
        if (a.master_year && a.master_year !== a.display_year) yearParts.push(`Master: ${a.master_year}`);
        detailYear.textContent = yearParts.join(' \u00B7 ');

        detailFormat.textContent = a.format || '';

        // Genre pills
        detailGenres.innerHTML = '';
        (a.genres || []).forEach(g => {
            const pill = document.createElement('span');
            pill.className = 'detail-pill';
            pill.textContent = g;
            detailGenres.appendChild(pill);
        });

        // Style pills
        detailStyles.innerHTML = '';
        (a.styles || []).forEach(s => {
            const pill = document.createElement('span');
            pill.className = 'detail-pill style-pill';
            pill.textContent = s;
            detailStyles.appendChild(pill);
        });

        // Rank
        if (a.big_board_rank) {
            detailRank.textContent = 'Big Board #' + a.big_board_rank;
            detailRank.classList.remove('hidden');
        } else {
            detailRank.classList.add('hidden');
        }

        // Stats
        detailPlayed.textContent = `Played: ${a.times_played}`;
        detailSkipped.textContent = `Skipped: ${a.times_skipped}`;

        // Discogs release link
        const releaseRow = detailDiscogsLink.closest('.detail-link-row');
        if (a.discogs_url) {
            detailDiscogsLink.href = a.discogs_url;
            if (releaseRow) releaseRow.style.display = '';
        } else {
            if (releaseRow) releaseRow.style.display = 'none';
        }

        // Master link
        const masterRow = detailMasterLink.closest('.detail-link-row');
        if (a.master_url) {
            detailMasterLink.href = a.master_url;
            if (masterRow) masterRow.style.display = '';
            detailNoMaster.classList.add('hidden');
            btnRemoveMaster.classList.remove('hidden');
        } else {
            if (masterRow) masterRow.style.display = 'none';
            detailNoMaster.classList.remove('hidden');
            btnRemoveMaster.classList.add('hidden');
        }
    }

    function showMasterEditForm() {
        detailMasterEdit.classList.remove('hidden');
        inputMasterId.focus();
    }

    function hideMasterEditForm() {
        detailMasterEdit.classList.add('hidden');
        inputMasterId.value = '';
    }

    function parseMasterId(input) {
        if (!input) return null;
        input = input.trim();
        // Numeric ID
        if (/^\d+$/.test(input)) return parseInt(input, 10);
        // URL: https://www.discogs.com/master/12345 or /master/12345-Artist-Title
        const match = input.match(/\/master\/(\d+)/);
        return match ? parseInt(match[1], 10) : null;
    }

    async function saveMasterOverride() {
        const raw = inputMasterId.value;
        const masterId = parseMasterId(raw);
        if (masterId === null) {
            showToast('Invalid master ID or URL', 'error');
            return;
        }
        btnSaveMaster.disabled = true;
        try {
            await api(`/api/album/${detailAlbumId}/master`, 'POST', { master_id: masterId });
            showToast('Master release updated');
            detailCardDirty = true;
            hideMasterEditForm();
            // Refresh card
            const resp = await api(`/api/album/${detailAlbumId}`);
            populateDetailCard(resp.data);
        } catch (err) {
            showToast(err.message, 'error');
        } finally {
            btnSaveMaster.disabled = false;
        }
    }

    async function removeMasterOverride() {
        btnRemoveMaster.disabled = true;
        try {
            await api(`/api/album/${detailAlbumId}/master`, 'POST', { master_id: null });
            showToast('Master release removed');
            detailCardDirty = true;
            hideMasterEditForm();
            const resp = await api(`/api/album/${detailAlbumId}`);
            populateDetailCard(resp.data);
        } catch (err) {
            showToast(err.message, 'error');
        } finally {
            btnRemoveMaster.disabled = false;
        }
    }

    // --- Release Edit ---

    function showReleaseEditForm() {
        detailReleaseEdit.classList.remove('hidden');
        detailMasterEdit.classList.add('hidden');
        inputReleaseId.focus();
    }

    function hideReleaseEditForm() {
        detailReleaseEdit.classList.add('hidden');
        inputReleaseId.value = '';
    }

    function parseReleaseId(input) {
        if (!input) return null;
        input = input.trim();
        if (/^\d+$/.test(input)) return parseInt(input, 10);
        const match = input.match(/\/release\/(\d+)/);
        return match ? parseInt(match[1], 10) : null;
    }

    async function saveReleaseOverride() {
        const raw = inputReleaseId.value;
        const releaseId = parseReleaseId(raw);
        if (releaseId === null) {
            showToast('Invalid release ID or URL', 'error');
            return;
        }
        btnSaveRelease.disabled = true;
        try {
            await api(`/api/album/${detailAlbumId}/release`, 'POST', { release_id: releaseId });
            showToast('Discogs release updated');
            detailCardDirty = true;
            hideReleaseEditForm();
            const resp = await api(`/api/album/${detailAlbumId}`);
            populateDetailCard(resp.data);
        } catch (err) {
            showToast(err.message, 'error');
        } finally {
            btnSaveRelease.disabled = false;
        }
    }

    // Detail card events
    btnDetailClose.addEventListener('click', closeDetailCard);
    detailModal.addEventListener('click', (e) => {
        if (e.target === detailModal) closeDetailCard();
    });
    btnEditMaster.addEventListener('click', () => {
        detailReleaseEdit.classList.add('hidden');
        showMasterEditForm();
    });
    btnSetMaster.addEventListener('click', showMasterEditForm);
    btnSaveMaster.addEventListener('click', saveMasterOverride);
    btnCancelMaster.addEventListener('click', hideMasterEditForm);
    btnRemoveMaster.addEventListener('click', removeMasterOverride);
    btnEditRelease.addEventListener('click', showReleaseEditForm);
    btnSaveRelease.addEventListener('click', saveReleaseOverride);
    btnCancelRelease.addEventListener('click', hideReleaseEditForm);

    // Click album cover on main page to open detail card
    albumCover.addEventListener('click', () => {
        if (currentAlbum && currentAlbum.album_id) {
            openDetailCard(currentAlbum.album_id);
        }
    });
    // Make cover look clickable
    albumCover.style.cursor = 'pointer';

    // --- Rank View ---

    function renderRankView(data) {
        const sorted = [...data].sort((a, b) => a.rank - b.rank);

        // Group into tiers of 100
        const tierSize = 100;
        const groups = {};
        sorted.forEach(e => {
            const tierStart = Math.floor((e.rank - 1) / tierSize) * tierSize + 1;
            const tierEnd = tierStart + tierSize - 1;
            const label = `${tierStart}\u2013${tierEnd}`;
            if (!groups[label]) groups[label] = [];
            groups[label].push(e);
        });

        const tierLabels = Object.keys(groups).sort((a, b) => {
            return parseInt(a) - parseInt(b);
        });

        buildJumpNav(tierLabels, 'bb-sec-');
        bigboardContent.innerHTML = '';

        const summary = document.createElement('p');
        summary.className = 'bb-rank-summary';
        summary.textContent = `Showing ${sorted.length} of ${bigboardData.length} entries`;
        bigboardContent.appendChild(summary);

        tierLabels.forEach(label => {
            const sectionId = 'bb-sec-' + label.replace(/[^a-zA-Z0-9]/g, '_');
            bigboardContent.appendChild(createGroup(label, groups[label], sectionId));
        });
    }

    // --- Big Board Match Modal ---

    const matchModal = $('#match-modal');
    const matchEntryInfo = $('#match-entry-info');
    const matchSearchInput = $('#match-search-input');
    const btnMatchSearch = $('#btn-match-search');
    const matchResults = $('#match-results');
    const btnMatchClose = $('#btn-match-close');
    let matchEntry = null;

    function openMatchModal(entry) {
        matchEntry = entry;
        matchEntryInfo.innerHTML = `
            <span class="match-rank">#${entry.rank}</span>
            <span class="match-artist-title">${esc(entry.artist)} — ${esc(entry.title)}</span>
            ${entry.year ? ` (${entry.year})` : ''}
        `;
        matchSearchInput.value = entry.artist.split(',')[0].trim();
        matchResults.innerHTML = '';
        openModal(matchModal);
        // Auto-search with the artist name
        searchForMatch();
    }

    function closeMatchModal() {
        closeModal(matchModal);
        matchEntry = null;
    }

    async function searchForMatch() {
        const q = matchSearchInput.value.trim();
        if (q.length < 2) {
            matchResults.innerHTML = '<p class="match-empty">Type at least 2 characters to search.</p>';
            return;
        }

        matchResults.innerHTML = '<p class="match-empty">Searching...</p>';

        try {
            const resp = await api(`/api/albums/search?q=${encodeURIComponent(q)}`);
            const albums = resp.data;

            if (albums.length === 0) {
                matchResults.innerHTML = '<p class="match-empty">No albums found. Try a different search.</p>';
                return;
            }

            matchResults.innerHTML = '';
            albums.forEach(album => {
                const item = document.createElement('div');
                item.className = 'match-result-item';

                const yearStr = album.display_year ? ` (${album.display_year})` : '';
                const rankStr = album.big_board_rank ? `Currently #${album.big_board_rank}` : '';

                item.innerHTML = `
                    <img class="match-result-cover" src="${escapeAttr(album.cover_image_url || '')}" alt=""
                         onerror="this.style.visibility='hidden'">
                    <div class="match-result-info">
                        <div class="match-result-name">${esc(album.artist)} — ${esc(album.title)}</div>
                        <div class="match-result-sub">${esc(yearStr)} ${rankStr ? ' · ' + esc(rankStr) : ''}</div>
                    </div>
                    <button class="btn-match-link">Link</button>
                `;

                item.querySelector('.btn-match-link').addEventListener('click', async (e) => {
                    e.stopPropagation();
                    const btn = e.currentTarget;
                    btn.disabled = true;
                    btn.textContent = '...';
                    try {
                        await api('/api/bigboard/match', 'POST', {
                            album_id: album.album_id,
                            rank: matchEntry.rank,
                            year: matchEntry.year,
                        });
                        showToast(`Matched to Big Board #${matchEntry.rank}`);
                        closeMatchModal();
                        // Reload Big Board data to reflect the change
                        bigboardData = [];
                        loadBigBoard();
                    } catch (err) {
                        showToast(err.message, 'error');
                        btn.disabled = false;
                        btn.textContent = 'Link';
                    }
                });

                matchResults.appendChild(item);
            });
        } catch (err) {
            matchResults.innerHTML = '<p class="match-empty">Search failed. Try again.</p>';
        }
    }

    btnMatchSearch.addEventListener('click', searchForMatch);
    matchSearchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') searchForMatch();
    });
    btnMatchClose.addEventListener('click', closeMatchModal);
    matchModal.addEventListener('click', (e) => {
        if (e.target === matchModal) closeMatchModal();
    });

    // --- The Library ---

    const btnLibrary = $('#btn-library');
    const btnLibraryBack = $('#btn-library-back');
    const libraryContent = $('#library-content');
    const libraryCount = $('#library-count');
    const librarySortSelect = $('#library-sort-select');
    const librarySortOrder = $('#library-sort-order');
    const libraryJump = $('#library-jump');
    const librarySearchInput = $('#library-search');

    let libraryData = [];
    let librarySort = 'artist';
    let libraryOrder = 'asc';
    let libraryGroupFilter = null; // null = show all groups, string = specific group key
    let libraryYearFilter = null;  // null = no year filter, number = specific year
    let librarySearch = '';

    function openLibrary() {
        mainContent.classList.add('hidden');
        bigboardSection.classList.add('hidden');
        lstatsSection.classList.add('hidden');
        excludedSection.classList.add('hidden');
        helpSection.classList.add('hidden');
        librarySection.classList.remove('hidden');
        loadLibrary();
    }

    function closeLibrary() {
        librarySection.classList.add('hidden');
        mainContent.classList.remove('hidden');
    }

    async function loadLibrary() {
        libraryContent.innerHTML = '<p style="text-align:center;color:var(--charcoal-light);padding:40px 0;">Loading...</p>';
        try {
            const resp = await api(`/api/library?sort=${librarySort}&order=${libraryOrder}`);
            libraryData = resp.data.albums;
            libraryCount.textContent = `${resp.data.total} entries`;
            renderLibrary();
        } catch (err) {
            libraryContent.innerHTML = '<p style="text-align:center;color:#c0392b;padding:40px 0;">Failed to load library.</p>';
            showToast(err.message, 'error');
        }
    }

    function getLibraryGroupKey(album) {
        const isYearSort = librarySort === 'master_year' || librarySort === 'release_year';
        if (isYearSort) {
            const year = librarySort === 'master_year'
                ? (album.master_year || album.release_year)
                : album.release_year;
            return year ? Math.floor(year / 10) * 10 + 's' : 'Unknown';
        } else if (librarySort === 'title') {
            const stripped = stripArticle(album.title);
            const ch = stripped.charAt(0).toUpperCase();
            return /[A-Z]/.test(ch) ? ch : '#';
        } else {
            const stripped = stripArticle(album.artist);
            const ch = stripped.charAt(0).toUpperCase();
            return /[A-Z]/.test(ch) ? ch : '#';
        }
    }

    function getLibraryGroups() {
        const groups = {};
        libraryData.forEach(album => {
            const key = getLibraryGroupKey(album);
            if (!groups[key]) groups[key] = [];
            groups[key].push(album);
        });
        return groups;
    }

    function getSortedGroupKeys(groups) {
        const isYearSort = librarySort === 'master_year' || librarySort === 'release_year';
        let sortedKeys;
        if (isYearSort) {
            sortedKeys = Object.keys(groups).sort((a, b) => {
                if (a === 'Unknown') return 1;
                if (b === 'Unknown') return -1;
                const diff = parseInt(a) - parseInt(b);
                return libraryOrder === 'desc' ? -diff : diff;
            });
        } else {
            sortedKeys = Object.keys(groups).sort((a, b) => {
                if (a === '#') return 1;
                if (b === '#') return -1;
                return a.localeCompare(b);
            });
            if (libraryOrder === 'desc') sortedKeys.reverse();
        }
        return sortedKeys;
    }

    function applyLibrarySearch(albums) {
        if (!librarySearch) return albums;
        const q = librarySearch.toLowerCase();
        return albums.filter(a =>
            a.artist.toLowerCase().includes(q) || a.title.toLowerCase().includes(q)
        );
    }

    function renderLibrary() {
        const isYearSort = librarySort === 'master_year' || librarySort === 'release_year';
        const groups = getLibraryGroups();
        const sortedKeys = getSortedGroupKeys(groups);

        // --- Filtered view: specific year selected ---
        if (isYearSort && libraryYearFilter !== null) {
            renderLibraryYearFiltered(groups, sortedKeys);
            return;
        }

        // --- Filtered view: specific group selected ---
        if (libraryGroupFilter !== null) {
            renderLibraryGroupFiltered(groups, sortedKeys);
            return;
        }

        // --- Full view: show jump nav with all groups ---
        libraryJump.innerHTML = '';
        libraryJump.classList.remove('hidden');
        sortedKeys.forEach(label => {
            const count = groups[label].length;
            const btn = document.createElement('button');
            btn.className = 'lib-jump-btn';
            btn.textContent = label;
            btn.title = `${count} entries`;
            btn.addEventListener('click', () => {
                if (isYearSort) {
                    // For year sorts, go to decade view first
                    libraryGroupFilter = label;
                } else {
                    libraryGroupFilter = label;
                }
                renderLibrary();
            });
            libraryJump.appendChild(btn);
        });

        // Apply search filter
        const searchFiltered = applyLibrarySearch(libraryData);
        if (librarySearch) {
            // When searching, show flat results
            libraryContent.innerHTML = '';
            if (searchFiltered.length === 0) {
                libraryContent.innerHTML = '<p style="text-align:center;color:var(--charcoal-light);padding:40px 0;">No matches found.</p>';
                return;
            }
            const grid = document.createElement('div');
            grid.className = 'lib-grid';
            searchFiltered.forEach(album => grid.appendChild(createLibraryCard(album)));
            libraryContent.appendChild(grid);
            return;
        }

        // Show all groups
        libraryContent.innerHTML = '';
        sortedKeys.forEach(label => {
            const group = groups[label];
            const section = document.createElement('div');
            section.className = 'lib-group';
            section.innerHTML = `
                <h3 class="lib-group-title">${esc(label)} <span class="lib-group-count">(${group.length})</span></h3>
                <div class="lib-grid"></div>
            `;
            const grid = section.querySelector('.lib-grid');
            group.forEach(album => grid.appendChild(createLibraryCard(album)));
            libraryContent.appendChild(section);
        });
    }

    function renderLibraryGroupFiltered(groups, sortedKeys) {
        const isYearSort = librarySort === 'master_year' || librarySort === 'release_year';
        const label = libraryGroupFilter;
        const groupAlbums = groups[label] || [];
        const filtered = applyLibrarySearch(groupAlbums);

        libraryJump.innerHTML = '';
        libraryJump.classList.remove('hidden');

        // Back button
        const backBtn = document.createElement('button');
        backBtn.className = 'lib-jump-btn lib-year-back';
        backBtn.innerHTML = '&larr; All';
        backBtn.addEventListener('click', () => {
            libraryGroupFilter = null;
            libraryYearFilter = null;
            renderLibrary();
        });
        libraryJump.appendChild(backBtn);

        // Current group label
        const groupLabel = document.createElement('span');
        groupLabel.className = 'lib-year-label';
        groupLabel.textContent = `${label} (${filtered.length} entries)`;
        libraryJump.appendChild(groupLabel);

        // For decade groups, add year sub-buttons
        if (isYearSort && label !== 'Unknown') {
            const subNav = document.createElement('div');
            subNav.className = 'lib-year-sub';

            const decadeStart = parseInt(label);
            const yearsInDecade = new Set();
            groupAlbums.forEach(album => {
                const year = librarySort === 'master_year'
                    ? (album.master_year || album.release_year)
                    : album.release_year;
                if (year && Math.floor(year / 10) * 10 === decadeStart) {
                    yearsInDecade.add(year);
                }
            });

            const sortedYears = Array.from(yearsInDecade).sort((a, b) =>
                libraryOrder === 'desc' ? b - a : a - b
            );

            sortedYears.forEach(year => {
                const btn = document.createElement('button');
                btn.className = 'lib-year-btn';
                btn.textContent = year;
                btn.addEventListener('click', () => {
                    libraryYearFilter = year;
                    renderLibrary();
                });
                subNav.appendChild(btn);
            });

            libraryJump.appendChild(subNav);
        }

        // Render the filtered grid
        libraryContent.innerHTML = '';
        if (filtered.length === 0) {
            libraryContent.innerHTML = '<p style="text-align:center;color:var(--charcoal-light);padding:40px 0;">No matches found.</p>';
            return;
        }
        const grid = document.createElement('div');
        grid.className = 'lib-grid';
        filtered.forEach(album => grid.appendChild(createLibraryCard(album)));
        libraryContent.appendChild(grid);
    }

    function renderLibraryYearFiltered(groups, sortedKeys) {
        const year = libraryYearFilter;
        const decadeLabel = libraryGroupFilter;
        const groupAlbums = decadeLabel && groups[decadeLabel] ? groups[decadeLabel] : libraryData;
        const filtered = applyLibrarySearch(groupAlbums.filter(album => {
            const albumYear = librarySort === 'master_year'
                ? (album.master_year || album.release_year)
                : album.release_year;
            return albumYear === year;
        }));

        libraryJump.innerHTML = '';
        libraryJump.classList.remove('hidden');

        // Back to decade
        const backBtn = document.createElement('button');
        backBtn.className = 'lib-jump-btn lib-year-back';
        backBtn.innerHTML = decadeLabel ? `&larr; ${esc(decadeLabel)}` : '&larr; All';
        backBtn.addEventListener('click', () => {
            libraryYearFilter = null;
            if (!decadeLabel) libraryGroupFilter = null;
            renderLibrary();
        });
        libraryJump.appendChild(backBtn);

        const yearLabel = document.createElement('span');
        yearLabel.className = 'lib-year-label';
        yearLabel.textContent = `${year} (${filtered.length} entries)`;
        libraryJump.appendChild(yearLabel);

        libraryContent.innerHTML = '';
        if (filtered.length === 0) {
            libraryContent.innerHTML = '<p style="text-align:center;color:var(--charcoal-light);padding:40px 0;">No matches found.</p>';
            return;
        }
        const grid = document.createElement('div');
        grid.className = 'lib-grid';
        filtered.forEach(album => grid.appendChild(createLibraryCard(album)));
        libraryContent.appendChild(grid);
    }

    function createLibraryCard(album) {
        const el = document.createElement('div');
        el.className = 'lib-card';

        const coverHtml = album.cover_image_url
            ? `<img class="lib-cover" src="${escapeAttr(album.cover_image_url)}" alt="" onerror="this.style.visibility='hidden'">`
            : `<div class="lib-cover"></div>`;

        const yearVal = album.display_year || '';
        const rankHtml = album.big_board_rank
            ? `<span class="lib-rank-badge">#${album.big_board_rank}</span>`
            : '';

        el.innerHTML = `
            ${coverHtml}
            <div class="lib-info">
                <div class="lib-artist">${esc(album.artist)}</div>
                <div class="lib-album">${esc(album.title)}</div>
                ${yearVal ? `<div class="lib-year">${yearVal}</div>` : ''}
            </div>
            ${rankHtml}
        `;

        el.addEventListener('click', () => openDetailCard(album.album_id));
        return el;
    }

    function stripArticle(name) {
        if (!name) return '';
        const lower = name.toLowerCase();
        if (lower.startsWith('the ')) return name.slice(4);
        if (lower.startsWith('a ')) return name.slice(2);
        return name;
    }

    btnLibrary.addEventListener('click', openLibrary);
    btnLibraryBack.addEventListener('click', closeLibrary);

    librarySortSelect.addEventListener('change', () => {
        librarySort = librarySortSelect.value;
        libraryGroupFilter = null;
        libraryYearFilter = null;
        librarySearch = '';
        librarySearchInput.value = '';
        loadLibrary();
    });

    librarySortOrder.addEventListener('click', () => {
        libraryOrder = libraryOrder === 'asc' ? 'desc' : 'asc';
        librarySortOrder.classList.toggle('desc', libraryOrder === 'desc');
        libraryGroupFilter = null;
        libraryYearFilter = null;
        loadLibrary();
    });

    librarySearchInput.addEventListener('input', () => {
        librarySearch = librarySearchInput.value.trim();
        renderLibrary();
    });

    // --- Listening Stats ---

    const btnLstats = $('#btn-lstats');
    const btnLstatsBack = $('#btn-lstats-back');
    const lstatsContent = $('#lstats-content');
    const lstatsCount = $('#lstats-count');
    const lstatsSearchInput = $('#lstats-search');

    let lstatsData = [];
    let lstatsSearch = '';

    function openListeningStats() {
        mainContent.classList.add('hidden');
        bigboardSection.classList.add('hidden');
        librarySection.classList.add('hidden');
        excludedSection.classList.add('hidden');
        helpSection.classList.add('hidden');
        lstatsSection.classList.remove('hidden');
        loadListeningStats();
    }

    function closeListeningStats() {
        lstatsSection.classList.add('hidden');
        mainContent.classList.remove('hidden');
    }

    async function loadListeningStats() {
        lstatsContent.innerHTML = '<p style="text-align:center;color:var(--charcoal-light);padding:40px 0;">Loading...</p>';
        try {
            const resp = await api('/api/listening-stats');
            lstatsData = resp.data.albums;
            lstatsCount.textContent = `${resp.data.total} albums played`;
            renderListeningStats();
        } catch (err) {
            lstatsContent.innerHTML = '<p style="text-align:center;color:#c0392b;padding:40px 0;">Failed to load stats.</p>';
            showToast(err.message, 'error');
        }
    }

    function renderListeningStats() {
        let data = lstatsData;
        if (lstatsSearch) {
            const q = lstatsSearch.toLowerCase();
            data = data.filter(a =>
                a.artist.toLowerCase().includes(q) || a.title.toLowerCase().includes(q)
            );
        }

        if (data.length === 0) {
            lstatsContent.innerHTML = lstatsData.length === 0
                ? '<p style="text-align:center;color:var(--charcoal-light);padding:40px 0;">No listening data yet. Play some records!</p>'
                : '<p style="text-align:center;color:var(--charcoal-light);padding:40px 0;">No matches found.</p>';
            return;
        }

        const grid = document.createElement('div');
        grid.className = 'lstats-grid';

        data.forEach((album, idx) => {
            const el = document.createElement('div');
            el.className = 'lstats-card';

            const coverHtml = album.cover_image_url
                ? `<img class="lstats-cover" src="${escapeAttr(album.cover_image_url)}" alt="" onerror="this.style.visibility='hidden'">`
                : `<div class="lstats-cover"></div>`;

            el.innerHTML = `
                <div class="lstats-rank">${idx + 1}</div>
                ${coverHtml}
                <div class="lstats-info">
                    <div class="lstats-artist">${esc(album.artist)}</div>
                    <div class="lstats-album">${esc(album.title)}${album.display_year ? ' (' + album.display_year + ')' : ''}</div>
                </div>
                <div class="lstats-plays">
                    ${album.listen_count}
                    <span class="lstats-plays-label">play${album.listen_count !== 1 ? 's' : ''}</span>
                </div>
            `;

            el.addEventListener('click', () => openDetailCard(album.album_id));
            grid.appendChild(el);
        });

        lstatsContent.innerHTML = '';
        lstatsContent.appendChild(grid);
    }

    btnLstats.addEventListener('click', openListeningStats);
    btnLstatsBack.addEventListener('click', closeListeningStats);
    lstatsSearchInput.addEventListener('input', () => {
        lstatsSearch = lstatsSearchInput.value.trim();
        renderListeningStats();
    });

    // --- Escape helpers ---

    function esc(str) {
        const div = document.createElement('div');
        div.textContent = str || '';
        return div.innerHTML;
    }

    function escapeAttr(str) {
        return (str || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;')
            .replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    // --- Event binding ---

    btnSelectFirst.addEventListener('click', selectNextAlbum);
    btnSelectNext.addEventListener('click', selectNextAlbum);
    btnPrevious.addEventListener('click', goToPrevious);
    btnListened.addEventListener('click', markListened);
    btnSkipped.addEventListener('click', markSkipped);
    btnExclude.addEventListener('click', promptExclude);

    btnSync.addEventListener('click', openSyncModal);
    btnSyncClose.addEventListener('click', closeSyncModal);
    syncModal.addEventListener('click', (e) => {
        if (e.target === syncModal) closeSyncModal();
    });

    btnSyncDiscogs.addEventListener('click', () => startSync('discogs'));
    btnSyncBigboard.addEventListener('click', () => startSync('bigboard'));
    btnSyncMasterYears.addEventListener('click', () => startSync('master_years'));

    btnConfirmCancel.addEventListener('click', () => closeModal(confirmModal));
    btnConfirmOk.addEventListener('click', confirmExclude);
    confirmModal.addEventListener('click', (e) => {
        if (e.target === confirmModal) closeModal(confirmModal);
    });

    btnWelcomeSync.addEventListener('click', () => {
        openSyncModal();
    });

    btnLoadMore.addEventListener('click', () => {
        historyPage++;
        loadHistory(false);
    });

    // Excluded section
    btnExcludedOpen.addEventListener('click', openExcluded);
    btnExcludedBack.addEventListener('click', closeExcluded);

    // Big Board
    btnBigboard.addEventListener('click', openBigBoard);
    btnBigboardBack.addEventListener('click', closeBigBoard);

    bigboardTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            bigboardTabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            bigboardView = tab.dataset.view;
            renderBigBoard();
        });
    });

    bigboardFilters.forEach(radio => {
        radio.addEventListener('change', () => {
            bigboardFilter = radio.value;
            renderBigBoard();
        });
    });

    bigboardSearchInput.addEventListener('input', () => {
        bigboardSearch = bigboardSearchInput.value.trim();
        renderBigBoard();
    });

    // --- Init ---

    async function init() {
        await loadStats();
        await loadHistory(true);
    }

    init();

})();
