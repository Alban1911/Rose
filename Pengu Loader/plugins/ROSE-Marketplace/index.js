/**
 * @name ROSE-Marketplace
 * @author Rose Team
 * @description Browse RuneForge and Celestial (Divine Skins) mods from the client and add them to Rose
 * @link https://github.com/Alban1911/Rose
 */
(function initMarketplace() {
  const LOG_PREFIX = "[ROSE-Marketplace]";
  const DIALOG_ID = "rose-marketplace-dialog";
  const STYLE_ID = "rose-marketplace-css";
  const PAGE_SIZE = 24;
  const SEARCH_DELAY_MS = 300;

  // Rose's menu language (ROSE-I18n); English until it has loaded
  const t = (text, vars) =>
    window.RoseI18n
      ? window.RoseI18n.t(text, vars)
      : text.replace(/\{(\w+)\}/g, (m, k) => (vars && k in vars ? String(vars[k]) : m));
  const tAny = (text) => (window.RoseI18n ? window.RoseI18n.tAny(text) : text);

  // Same names as Rose's "Add custom mods" menu (already translated)
  const CATEGORY_LABELS = {
    skins: "Skins",
    maps: "Maps",
    fonts: "Fonts",
    announcers: "Announcers",
    ui: "UI",
    voiceover: "Voiceover",
    loading_screen: "Loading Screen",
    vfx: "VFX",
    sfx: "SFX",
    others: "Others",
  };
  const SORTS = [
    ["trending", "Trending"],
    ["new", "Newest"],
    ["updated", "Recently updated"],
    ["downloads", "Most downloaded"],
    ["likes", "Most liked"],
  ];
  const PROVIDER_BADGES = { runeforge: "RF", divine: "CE" };

  let bridge = null;
  let facets = null;
  let facetsRequested = false;
  let searchTimer = null;
  let observer = null;
  let requestCounter = 0;

  const state = {
    providers: new Set(),
    search: "",
    sort: "trending",
    champions: new Set(),
    maps: new Set(),
    categories: new Set(),
    themes: new Set(),
    features: new Set(),
    gildedOnly: false,
    ai: "all",
    page: 0,
    items: [],
    total: 0,
    hasMore: false,
    loading: false,
    requestId: null,
    skipped: {},
    errors: {},
    filtersOpen: false,
  };
  // key -> {percent} while downloading, {error, pageUrl} after a failure
  const downloads = new Map();

  function log(level, ...args) {
    const method = level === "error" ? console.error : level === "warn" ? console.warn : console.log;
    method(LOG_PREFIX, ...args);
  }

  function notify(message, isError = false) {
    if (window.RoseSettings && window.RoseSettings.notify) {
      window.RoseSettings.notify(message, isError);
    } else {
      log(isError ? "error" : "info", message);
    }
  }

  function waitForBridge() {
    return new Promise((resolve, reject) => {
      let elapsed = 0;
      const check = () => {
        if (window.__roseBridge) return resolve(window.__roseBridge);
        elapsed += 50;
        if (elapsed >= 10000) return reject(new Error("Bridge not available"));
        setTimeout(check, 50);
      };
      check();
    });
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function providerLabel(name) {
    const provider = facets && facets.providers.find((p) => p.name === name);
    return provider ? provider.label : name;
  }

  function compactNumber(value) {
    const number = Number(value) || 0;
    if (number >= 1e6) return `${(number / 1e6).toFixed(1).replace(/\.0$/, "")}M`;
    if (number >= 1e3) return `${(number / 1e3).toFixed(1).replace(/\.0$/, "")}k`;
    return String(number);
  }

  function thumbUrl(url) {
    const port = window.__roseBridge ? window.__roseBridge.port : 50000;
    return `http://127.0.0.1:${port}/market-thumb?u=${encodeURIComponent(url)}`;
  }

  // ------------------------------------------------------------------ styles
  function injectCSS() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      #${DIALOG_ID} {
        position: fixed; inset: 0; z-index: 10001;
        background: rgba(0, 0, 0, 0.6);
        display: flex; align-items: center; justify-content: center;
        font-family: "Beaufort for LOL", serif; color: #cdbe91;
      }
      #${DIALOG_ID} * { box-sizing: border-box; }
      .rmp-frame {
        width: min(1120px, 94vw); height: 88vh;
        background: #010a13; border: 1px solid #785a28;
        box-shadow: 0 0 24px rgba(0, 0, 0, 0.8);
        display: flex; flex-direction: column; overflow: hidden;
      }
      .rmp-header {
        display: flex; align-items: center; gap: 12px;
        padding: 14px 18px 10px; border-bottom: 1px solid #1e2328;
      }
      .rmp-title { flex: 1; font-size: 20px; color: #f0e6d2; letter-spacing: 0.05em; text-transform: uppercase; }
      .rmp-close {
        background: none; border: 1px solid #463714; color: #cdbe91; width: 28px; height: 28px;
        cursor: pointer; font-size: 16px; line-height: 1;
      }
      .rmp-close:hover { border-color: #c8aa6e; color: #f0e6d2; }
      .rmp-toolbar {
        display: flex; flex-wrap: wrap; align-items: center; gap: 10px;
        padding: 10px 18px; border-bottom: 1px solid #1e2328;
      }
      .rmp-search {
        flex: 1 1 260px; min-width: 200px; height: 32px; padding: 0 10px;
        background: #010a13; color: #f0e6d2; border: 1px solid #463714; font-size: 13px; outline: none;
      }
      .rmp-search:focus { border-color: #c8aa6e; }
      .rmp-select {
        height: 32px; padding: 0 8px; background: #1e2328; color: #cdbe91;
        border: 1px solid #463714; font-family: inherit; font-size: 12px; outline: none;
      }
      .rmp-pill {
        display: inline-flex; align-items: center; gap: 6px; height: 32px; padding: 0 12px;
        border: 1px solid #463714; background: #1e2328; color: #a09b8c;
        cursor: pointer; font-size: 12px; user-select: none;
      }
      .rmp-pill.on { border-color: #c8aa6e; color: #f0e6d2; background: #1e282d; }
      .rmp-pill:hover { border-color: #c8aa6e; }
      .rmp-badge {
        display: inline-block; font-size: 9px; padding: 1px 4px; border: 1px solid currentColor;
        letter-spacing: 0.06em; line-height: 12px; opacity: 0.85;
      }
      .rmp-badge.runeforge { color: #e8a24a; }
      .rmp-badge.divine { color: #7fb3ff; }
      .rmp-filters {
        display: none; padding: 12px 18px; border-bottom: 1px solid #1e2328;
        background: #0a1015; max-height: 40vh; overflow-y: auto;
      }
      .rmp-filters.open { display: block; }
      .rmp-columns { display: grid; grid-template-columns: 1.3fr 1fr 1fr 1fr 1fr; gap: 18px; }
      .rmp-column-title {
        font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; color: #a09b8c;
        margin-bottom: 8px;
      }
      .rmp-list { max-height: 200px; overflow-y: auto; padding-right: 4px; }
      .rmp-option {
        display: flex; align-items: center; gap: 8px; padding: 3px 0;
        font-size: 13px; color: #cdbe91; cursor: pointer;
      }
      .rmp-option input { accent-color: #c8aa6e; margin: 0; cursor: pointer; }
      .rmp-option.unsupported { opacity: 0.35; }
      .rmp-option .rmp-badge { margin-left: auto; }
      .rmp-mini-search {
        width: 100%; height: 26px; margin-bottom: 6px; padding: 0 8px;
        background: #010a13; color: #f0e6d2; border: 1px solid #463714; font-size: 12px; outline: none;
      }
      .rmp-filters-footer {
        display: flex; flex-wrap: wrap; align-items: center; gap: 14px;
        margin-top: 12px; padding-top: 10px; border-top: 1px solid #1e2328; font-size: 12px;
      }
      .rmp-segment { display: inline-flex; border: 1px solid #463714; margin-left: auto; }
      .rmp-segment button {
        background: #1e2328; color: #a09b8c; border: none; padding: 5px 12px;
        font-family: inherit; font-size: 12px; cursor: pointer;
      }
      .rmp-segment button.on { background: #463714; color: #f0e6d2; }
      .rmp-link-button {
        background: none; border: none; color: #c8aa6e; cursor: pointer; font-family: inherit;
        font-size: 12px; text-decoration: underline;
      }
      .rmp-status { padding: 8px 18px; font-size: 12px; color: #a09b8c; min-height: 30px; }
      .rmp-status .rmp-warn { color: #e8a24a; margin-left: 10px; }
      .rmp-body { flex: 1; overflow-y: auto; padding: 4px 18px 18px; }
      .rmp-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 14px; }
      .rmp-card {
        display: flex; flex-direction: column; background: #1e2328; border: 1px solid #1e2328;
        transition: border-color 0.15s;
      }
      .rmp-card:hover { border-color: #785a28; }
      .rmp-thumb {
        position: relative; width: 100%; aspect-ratio: 16 / 10; background: #0a1015; overflow: hidden;
      }
      .rmp-thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
      .rmp-thumb .rmp-badge { position: absolute; top: 6px; left: 6px; background: rgba(1, 10, 19, 0.85); }
      .rmp-flag {
        position: absolute; top: 6px; right: 6px; font-size: 10px; padding: 1px 5px;
        background: rgba(1, 10, 19, 0.85); color: #f0e6d2; border: 1px solid #c8aa6e;
      }
      .rmp-card-body { padding: 8px 10px 10px; display: flex; flex-direction: column; gap: 4px; flex: 1; }
      .rmp-name {
        color: #f0e6d2; font-size: 14px; line-height: 18px; overflow: hidden;
        display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
      }
      .rmp-meta { font-size: 11px; color: #a09b8c; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .rmp-actions { display: flex; align-items: center; gap: 8px; margin-top: auto; padding-top: 6px; }
      .rmp-download {
        flex: 1; height: 28px; background: #1e2328; color: #cdbe91; border: 1px solid #c8aa6e;
        font-family: inherit; font-size: 12px; letter-spacing: 0.05em; text-transform: uppercase; cursor: pointer;
      }
      .rmp-download:hover:not(:disabled) { background: #463714; color: #f0e6d2; }
      .rmp-download:disabled { border-color: #463714; color: #5b5a56; cursor: default; }
      .rmp-download.installed { border-color: #0ac8b9; color: #0ac8b9; }
      .rmp-open {
        width: 28px; height: 28px; background: none; border: 1px solid #463714; color: #a09b8c;
        cursor: pointer; font-size: 14px;
      }
      .rmp-open:hover { border-color: #c8aa6e; color: #f0e6d2; }
      .rmp-progress { height: 3px; background: #010a13; }
      .rmp-progress > div { height: 100%; width: 0; background: #c8aa6e; transition: width 0.2s; }
      .rmp-card-error { font-size: 11px; color: #ff6b6b; }
      .rmp-empty, .rmp-loading { grid-column: 1 / -1; text-align: center; padding: 30px; color: #a09b8c; }
      .rmp-sentinel { height: 1px; }
      .rmp-note { padding: 0 18px 8px; font-size: 10px; color: #5b5a56; }
    `;
    document.head.appendChild(style);
  }

  // ------------------------------------------------------------------ dialog
  function open() {
    if (!bridge) {
      notify(t("The marketplace is not available"), true);
      return;
    }
    injectCSS();
    close();

    const dialog = el("div");
    dialog.id = DIALOG_ID;
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) close();
    });
    const frame = el("div", "rmp-frame");
    frame.addEventListener("click", (event) => event.stopPropagation());
    dialog.appendChild(frame);

    const header = el("div", "rmp-header");
    header.appendChild(el("div", "rmp-title", t("Marketplace")));
    const closeButton = el("button", "rmp-close", "✕");
    closeButton.setAttribute("aria-label", t("Close"));
    closeButton.addEventListener("click", close);
    header.appendChild(closeButton);
    frame.appendChild(header);

    frame.appendChild(buildToolbar());
    const filters = el("div", "rmp-filters");
    filters.id = "rmp-filters";
    frame.appendChild(filters);
    const status = el("div", "rmp-status");
    status.id = "rmp-status";
    frame.appendChild(status);

    const body = el("div", "rmp-body");
    body.id = "rmp-body";
    const grid = el("div", "rmp-grid");
    grid.id = "rmp-grid";
    body.appendChild(grid);
    const sentinel = el("div", "rmp-sentinel");
    body.appendChild(sentinel);
    frame.appendChild(body);
    frame.appendChild(el("div", "rmp-note", t("Mods are made by the community and hosted by RuneForge and Divine Skins. Rose downloads them only when you ask.")));

    document.body.appendChild(dialog);
    document.addEventListener("keydown", onKeyDown, true);

    observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting) && state.hasMore && !state.loading) {
        loadPage(state.page + 1);
      }
    }, { root: body, rootMargin: "400px" });
    observer.observe(sentinel);

    renderFilters();
    if (!facets && !facetsRequested) {
      facetsRequested = true;
      bridge.send({ type: "marketplace-facets" });
    }
    if (state.items.length) {
      renderGrid();
      renderStatus();
    } else {
      loadPage(0);
    }
  }

  function close() {
    const dialog = document.getElementById(DIALOG_ID);
    if (dialog) dialog.remove();
    if (observer) {
      observer.disconnect();
      observer = null;
    }
    document.removeEventListener("keydown", onKeyDown, true);
  }

  function onKeyDown(event) {
    // Leave Escape to the skin/champion pickers while they are open on top
    if (event.key !== "Escape") return;
    if (document.getElementById("skin-selection-dialog") || document.getElementById("champion-selection-dialog")) return;
    event.stopPropagation();
    close();
  }

  function buildToolbar() {
    const toolbar = el("div", "rmp-toolbar");

    const search = el("input", "rmp-search");
    search.type = "search";
    search.placeholder = t("Search mods, creators, champions...");
    search.value = state.search;
    search.spellcheck = false;
    search.autocomplete = "off";
    search.addEventListener("input", () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => {
        state.search = search.value.trim();
        loadPage(0);
      }, SEARCH_DELAY_MS);
    });
    // Keep the client from treating typing as hotkeys
    search.addEventListener("keydown", (event) => event.stopPropagation());
    toolbar.appendChild(search);

    const sort = el("select", "rmp-select");
    SORTS.forEach(([value, label]) => {
      const option = el("option", null, t(label));
      option.value = value;
      option.selected = value === state.sort;
      sort.appendChild(option);
    });
    sort.addEventListener("change", () => {
      state.sort = sort.value;
      loadPage(0);
    });
    toolbar.appendChild(sort);

    const providers = el("div");
    providers.id = "rmp-providers";
    providers.style.display = "flex";
    providers.style.gap = "6px";
    toolbar.appendChild(providers);
    renderProviderPills(providers);

    const filtersButton = el("div", "rmp-pill");
    filtersButton.id = "rmp-filters-button";
    filtersButton.addEventListener("click", () => {
      state.filtersOpen = !state.filtersOpen;
      renderFilters();
    });
    toolbar.appendChild(filtersButton);
    updateFiltersButton(filtersButton);
    return toolbar;
  }

  function renderProviderPills(container = document.getElementById("rmp-providers")) {
    if (!container) return;
    container.textContent = "";
    const list = facets ? facets.providers.filter((p) => p.enabled) : [];
    list.forEach((provider) => {
      const pill = el("div", `rmp-pill${state.providers.has(provider.name) ? " on" : ""}`);
      pill.appendChild(el("span", `rmp-badge ${provider.name}`, PROVIDER_BADGES[provider.name] || provider.name));
      pill.appendChild(el("span", null, provider.label));
      pill.addEventListener("click", () => {
        if (state.providers.has(provider.name)) {
          if (state.providers.size === 1) return; // at least one site
          state.providers.delete(provider.name);
        } else {
          state.providers.add(provider.name);
        }
        renderProviderPills();
        renderFilters();
        loadPage(0);
      });
      container.appendChild(pill);
    });
  }

  function activeFilterCount() {
    return state.champions.size + state.maps.size + state.categories.size + state.themes.size +
      state.features.size + (state.gildedOnly ? 1 : 0) + (state.ai !== "all" ? 1 : 0);
  }

  function updateFiltersButton(button = document.getElementById("rmp-filters-button")) {
    if (!button) return;
    const count = activeFilterCount();
    button.className = `rmp-pill${state.filtersOpen || count ? " on" : ""}`;
    button.textContent = count ? t("Filters ({count})", { count }) : t("Filters");
  }

  // ----------------------------------------------------------------- filters
  function supportedBy(providers) {
    return !providers || providers.some((name) => state.providers.has(name));
  }

  function providerBadge(providers, allProviders) {
    // Only mark values that a single site understands
    if (!providers || providers.length >= allProviders.length || providers.length !== 1) return null;
    const name = providers[0];
    return el("span", `rmp-badge ${name}`, PROVIDER_BADGES[name] || name);
  }

  function buildOptionList(values, selected, options = {}) {
    const list = el("div", "rmp-list");
    const allProviders = facets ? facets.providers.filter((p) => p.enabled).map((p) => p.name) : [];
    values.forEach((value) => {
      const label = el("label", "rmp-option");
      if (!supportedBy(value.providers)) {
        label.classList.add("unsupported");
        label.title = t("Not available on the selected sites");
      }
      const box = el("input");
      box.type = "checkbox";
      box.checked = selected.has(value.value);
      box.addEventListener("change", () => {
        if (box.checked) selected.add(value.value);
        else selected.delete(value.value);
        updateFiltersButton();
        loadPage(0);
      });
      label.appendChild(box);
      label.appendChild(el("span", null, value.label));
      label.dataset.search = String(value.label).toLowerCase();
      const badge = providerBadge(value.providers, allProviders);
      if (badge) label.appendChild(badge);
      list.appendChild(label);
    });
    if (options.emptyText && !values.length) list.appendChild(el("div", "rmp-meta", options.emptyText));
    return list;
  }

  function column(title, content) {
    const wrapper = el("div");
    wrapper.appendChild(el("div", "rmp-column-title", title));
    if (Array.isArray(content)) content.forEach((node) => wrapper.appendChild(node));
    else wrapper.appendChild(content);
    return wrapper;
  }

  function renderFilters() {
    const panel = document.getElementById("rmp-filters");
    updateFiltersButton();
    if (!panel) return;
    panel.classList.toggle("open", state.filtersOpen);
    panel.textContent = "";
    if (!state.filtersOpen) return;
    if (!facets) {
      panel.appendChild(el("div", "rmp-meta", t("Loading filters...")));
      return;
    }

    const columns = el("div", "rmp-columns");

    // Champions, with their own search box
    const championFilter = el("input", "rmp-mini-search");
    championFilter.type = "search";
    championFilter.placeholder = t("Filter");
    championFilter.addEventListener("keydown", (event) => event.stopPropagation());
    const championValues = facets.champions.map((c) => ({ value: c.name, label: c.name, providers: c.providers }));
    // Selected champions first so they stay visible
    championValues.sort((a, b) => (state.champions.has(b.value) - state.champions.has(a.value)) || a.label.localeCompare(b.label));
    const championList = buildOptionList(championValues, state.champions);
    championFilter.addEventListener("input", () => {
      const term = championFilter.value.toLowerCase().trim();
      championList.querySelectorAll(".rmp-option").forEach((option) => {
        option.style.display = !term || option.dataset.search.includes(term) ? "" : "none";
      });
    });
    columns.appendChild(column(t("Champions"), [championFilter, championList]));

    columns.appendChild(column(t("Maps"), buildOptionList(facets.maps, state.maps, { emptyText: "—" })));
    columns.appendChild(column(t("Categories"), buildOptionList(
      facets.categories.map((c) => ({ value: c.value, label: t(CATEGORY_LABELS[c.value] || c.value), providers: c.providers })),
      state.categories,
    )));
    columns.appendChild(column(t("Themes"), buildOptionList(facets.themes, state.themes)));
    columns.appendChild(column(t("Features"), buildOptionList(
      facets.features.map((f) => ({ value: f.value, label: t(f.label), providers: f.providers })),
      state.features,
    )));
    panel.appendChild(columns);

    const footer = el("div", "rmp-filters-footer");
    if (facets.gilded.length) {
      const gilded = el("label", "rmp-option");
      if (!supportedBy(facets.gilded)) gilded.classList.add("unsupported");
      const box = el("input");
      box.type = "checkbox";
      box.checked = state.gildedOnly;
      box.addEventListener("change", () => {
        state.gildedOnly = box.checked;
        updateFiltersButton();
        loadPage(0);
      });
      gilded.appendChild(box);
      gilded.appendChild(el("span", null, t("Gilded only")));
      const badge = providerBadge(facets.gilded, facets.providers.filter((p) => p.enabled).map((p) => p.name));
      if (badge) gilded.appendChild(badge);
      footer.appendChild(gilded);
    }

    const clear = el("button", "rmp-link-button", t("Clear filters"));
    clear.addEventListener("click", () => {
      [state.champions, state.maps, state.categories, state.themes, state.features].forEach((set) => set.clear());
      state.gildedOnly = false;
      state.ai = "all";
      renderFilters();
      loadPage(0);
    });
    footer.appendChild(clear);

    footer.appendChild(el("span", null, t("AI content")));
    const segment = el("div", "rmp-segment");
    segment.style.marginLeft = "0";
    [["all", "All"], ["exclude", "Hide AI"], ["only", "Only AI"]].forEach(([value, label]) => {
      const button = el("button", value === state.ai ? "on" : "", t(label));
      button.addEventListener("click", () => {
        state.ai = value;
        renderFilters();
        loadPage(0);
      });
      segment.appendChild(button);
    });
    footer.appendChild(segment);
    panel.appendChild(footer);
  }

  // ------------------------------------------------------------------ search
  function loadPage(page) {
    if (!bridge) return;
    if (page === 0) {
      state.items = [];
      state.total = 0;
      state.hasMore = false;
      const body = document.getElementById("rmp-body");
      if (body) body.scrollTop = 0;
    }
    state.page = page;
    state.loading = true;
    state.requestId = `mp-${Date.now()}-${++requestCounter}`;
    bridge.send({
      type: "marketplace-search",
      requestId: state.requestId,
      providers: Array.from(state.providers),
      search: state.search,
      sort: state.sort,
      page,
      pageSize: PAGE_SIZE,
      champions: Array.from(state.champions),
      maps: Array.from(state.maps),
      categories: Array.from(state.categories),
      themes: Array.from(state.themes),
      features: Array.from(state.features),
      gildedOnly: state.gildedOnly,
      ai: state.ai,
    });
    renderGrid();
    renderStatus();
  }

  function handleSearchResponse(payload) {
    if (!payload || payload.requestId !== state.requestId) return; // an older search
    state.loading = false;
    const seen = new Set(state.items.map((item) => item.key));
    (payload.items || []).forEach((item) => {
      if (!seen.has(item.key)) state.items.push(item);
    });
    state.total = payload.total || 0;
    state.hasMore = Boolean(payload.hasMore);
    state.skipped = payload.skipped || {};
    state.errors = payload.errors || {};
    renderGrid();
    renderStatus();
  }

  function renderStatus() {
    const status = document.getElementById("rmp-status");
    if (!status) return;
    status.textContent = "";
    if (state.loading && !state.items.length) {
      status.appendChild(el("span", null, t("Loading mods...")));
    } else {
      status.appendChild(el("span", null, t("{count} mods", { count: state.total })));
    }
    Object.keys(state.skipped).forEach((name) => {
      status.appendChild(el("span", "rmp-warn", t("{site} can't apply these filters", { site: providerLabel(name) })));
    });
    Object.keys(state.errors).forEach((name) => {
      status.appendChild(el("span", "rmp-warn", t("{site} is unavailable right now", { site: providerLabel(name) })));
    });
  }

  function renderGrid() {
    const grid = document.getElementById("rmp-grid");
    if (!grid) return;
    grid.textContent = "";
    state.items.forEach((item) => grid.appendChild(buildCard(item)));
    if (state.loading) {
      grid.appendChild(el("div", "rmp-loading", t("Loading mods...")));
    } else if (!state.items.length) {
      grid.appendChild(el("div", "rmp-empty", t("No mods match these filters.")));
    }
  }

  // ------------------------------------------------------------------- cards
  function cardMeta(item) {
    const parts = [];
    if (item.author) parts.push(t("by {name}", { name: item.author }));
    if (item.championCount > 2) parts.push(t("{count} champions", { count: item.championCount }));
    else if (item.champions && item.champions.length) parts.push(item.champions.map((c) => c.name).join(", "));
    else if (item.category) parts.push(t(CATEGORY_LABELS[item.category] || item.category));
    return parts.join(" · ");
  }

  function buildCard(item) {
    const card = el("div", "rmp-card");
    card.dataset.key = item.key;

    const thumb = el("div", "rmp-thumb");
    if (item.thumb_url) {
      const img = el("img");
      img.loading = "lazy";
      img.alt = item.name;
      img.src = thumbUrl(item.thumb_url);
      img.onerror = function () { this.style.display = "none"; };
      thumb.appendChild(img);
    }
    thumb.appendChild(el("span", `rmp-badge ${item.provider}`, PROVIDER_BADGES[item.provider] || item.provider));
    if (item.gilded) thumb.appendChild(el("span", "rmp-flag", t("Gilded")));
    else if (item.ai) thumb.appendChild(el("span", "rmp-flag", "AI"));
    card.appendChild(thumb);

    const progress = el("div", "rmp-progress");
    progress.appendChild(el("div"));
    card.appendChild(progress);

    const body = el("div", "rmp-card-body");
    const name = el("div", "rmp-name", item.name);
    name.title = item.name;
    body.appendChild(name);
    body.appendChild(el("div", "rmp-meta", cardMeta(item)));
    body.appendChild(el("div", "rmp-meta", `⬇ ${compactNumber(item.downloads)}   ♥ ${compactNumber(item.likes)}`));
    const error = el("div", "rmp-card-error");
    body.appendChild(error);

    const actions = el("div", "rmp-actions");
    const download = el("button", "rmp-download");
    download.addEventListener("click", () => startDownload(item));
    actions.appendChild(download);
    const openPage = el("button", "rmp-open", "↗");
    openPage.title = t("Open on {site}", { site: providerLabel(item.provider) });
    openPage.addEventListener("click", () => bridge.send({ type: "marketplace-open-page", url: item.page_url }));
    actions.appendChild(openPage);
    body.appendChild(actions);
    card.appendChild(body);

    updateCard(card, item);
    return card;
  }

  function updateCard(card, item) {
    const download = card.querySelector(".rmp-download");
    const bar = card.querySelector(".rmp-progress > div");
    const error = card.querySelector(".rmp-card-error");
    const status = downloads.get(item.key);
    download.classList.remove("installed");
    download.disabled = false;
    error.textContent = "";
    bar.style.width = "0";

    if (status && status.active) {
      download.disabled = true;
      download.textContent = status.percent != null ? `${Math.round(status.percent)}%` : t("Downloading...");
      bar.style.width = `${status.percent || 3}%`;
      return;
    }
    if (status && status.error) error.textContent = tAny(status.error);
    if (item.updateAvailable) {
      download.textContent = t("Update");
    } else if (item.installed) {
      download.textContent = t("Installed");
      download.classList.add("installed");
      download.title = t("Download again");
    } else {
      download.textContent = t("Download");
    }
  }

  function refreshCard(key) {
    const item = state.items.find((entry) => entry.key === key);
    const card = document.querySelector(`#rmp-grid .rmp-card[data-key="${CSS.escape(key)}"]`);
    if (item && card) updateCard(card, item);
  }

  // ---------------------------------------------------------------- download
  function championIdFor(item) {
    const byName = new Map((facets ? facets.champions : []).map((c) => [c.name.toLowerCase(), c.id]));
    const idOf = (champ) => (champ.id != null ? Number(champ.id) : byName.get(String(champ.name).toLowerCase()) || null);
    const champions = item.champions || [];
    if (item.championCount === 1 && champions.length === 1) return idOf(champions[0]);
    // A multi-champion mod: use the champion the user filtered on
    const filtered = champions.filter((c) => state.champions.has(c.name));
    if (filtered.length === 1) return idOf(filtered[0]);
    return null;
  }

  async function startDownload(item) {
    const status = downloads.get(item.key);
    if (status && status.active) return;

    const payload = {
      type: "marketplace-download",
      provider: item.provider,
      id: item.id,
      name: item.name,
      updatedAt: item.updated_at,
      category: item.category || "others",
    };

    if (payload.category === "skins") {
      const settings = window.RoseSettings;
      if (!settings) {
        notify(t("The marketplace is not available"), true);
        return;
      }
      let championId = championIdFor(item);
      if (!championId) {
        championId = await settings.pickChampion();
        if (!championId) return;
      }
      const targets = await settings.pickSkinTargets(championId, {
        preselect: [Number(championId) * 1000],
        confirmLabel: t("Confirm & Download"),
      });
      if (!targets || !targets.skinIds || !targets.skinIds.length) return;
      payload.championId = targets.championId;
      payload.skinIds = targets.skinIds;
    }

    downloads.set(item.key, { active: true, percent: null });
    refreshCard(item.key);
    bridge.send(payload);
  }

  function handleDownloadProgress(payload) {
    const status = downloads.get(payload.key);
    if (!status || !status.active) return;
    status.percent = payload.percent;
    refreshCard(payload.key);
  }

  function handleDownloadResult(payload) {
    const item = state.items.find((entry) => entry.key === payload.key);
    const name = item ? item.name : payload.modName;
    if (payload.success) {
      downloads.delete(payload.key);
      if (item) {
        item.installed = true;
        item.updateAvailable = false;
      }
      notify(t("{name} added to Rose", { name: payload.modName || name }));
    } else if (payload.captcha) {
      downloads.set(payload.key, { error: t("The site asks for a captcha: download this mod from its page.") });
      notify(t("The site asks for a captcha: download this mod from its page."), true);
      if (payload.pageUrl) bridge.send({ type: "marketplace-open-page", url: payload.pageUrl });
    } else {
      downloads.set(payload.key, { error: payload.error || "Download failed" });
      notify(t("Couldn't add {name}: {error}", { name, error: tAny(payload.error || "Download failed") }), true);
    }
    refreshCard(payload.key);
  }

  function handleFacetsResponse(payload) {
    facets = payload;
    facets.providers = facets.providers || [];
    if (!state.providers.size) {
      facets.providers.filter((p) => p.enabled).forEach((p) => state.providers.add(p.name));
    }
    Object.entries(facets.errors || {}).forEach(([name, error]) => log("warn", `${name} filters unavailable: ${error}`));
    renderProviderPills();
    renderFilters();
  }

  // -------------------------------------------------------------------- init
  async function init() {
    try {
      bridge = await waitForBridge();
    } catch (err) {
      log("error", "Init failed:", err);
      return;
    }
    bridge.subscribe("marketplace-facets-response", handleFacetsResponse);
    bridge.subscribe("marketplace-search-response", handleSearchResponse);
    bridge.subscribe("marketplace-download-progress", handleDownloadProgress);
    bridge.subscribe("marketplace-download-result", handleDownloadResult);
    // Ask again after a reconnect if the first request was lost
    bridge.onReady(() => {
      if (!facets && facetsRequested) bridge.send({ type: "marketplace-facets" });
    });
    log("info", "Marketplace plugin initialized");
  }

  window.RoseMarketplace = Object.freeze({ open, close });

  if (typeof document === "undefined") return;
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => init(), { once: true });
  } else {
    init();
  }
})();
