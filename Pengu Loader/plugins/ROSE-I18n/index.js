/**
 * @name ROSE-I18n
 * @author Rose Team
 * @description Language of Rose's menus: the one picked in Settings, else the League client's, else English
 */
(function initRoseI18n() {
  const LOG_PREFIX = "[ROSE-I18n]";
  const CACHE_KEY = "rose_i18n";
  const EVENT_CHANGED = "rose-i18n-changed";

  // Texts are keyed by their English version, which is also the fallback
  let state = { language: "en", setting: "auto", direction: "ltr", languages: { en: "English" }, strings: {} };

  function format(text, vars) {
    if (!vars) return text;
    return text.replace(/\{(\w+)\}/g, (match, key) => (key in vars ? String(vars[key]) : match));
  }

  function t(text, vars) {
    if (typeof text !== "string") return text;
    const translated = state.strings[text];
    return format(typeof translated === "string" && translated ? translated : text, vars);
  }

  // Templated texts ("Connected to {name}") as regexes, to translate finished
  // English texts from Rose (error messages). Short ones ("Skin {id}") would
  // match about anything, so they are left out.
  let templates = [];

  function compileTemplates() {
    templates = Object.keys(state.strings)
      .filter((key) => /\{\w+\}/.test(key) && key.replace(/\{\w+\}/g, "").length >= 12)
      .map((key) => {
        const names = [];
        const source = key
          .split(/(\{\w+\})/)
          .map((part) => {
            const name = /^\{(\w+)\}$/.exec(part);
            if (name) {
              names.push(name[1]);
              return "(.+?)";
            }
            return part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
          })
          .join("");
        return { key, names, regex: new RegExp(`^${source}$`) };
      });
  }

  function tAny(text) {
    if (typeof text !== "string") return text;
    if (state.strings[text]) return state.strings[text];
    for (const { key, names, regex } of templates) {
      const match = regex.exec(text);
      if (!match) continue;
      const vars = {};
      names.forEach((name, i) => { vars[name] = match[i + 1]; });
      return t(key, vars);
    }
    return text;
  }

  function apply(next, announce) {
    if (!next || typeof next !== "object" || typeof next.strings !== "object") return;
    const changed =
      next.language !== state.language ||
      (next.setting || "auto") !== state.setting ||
      JSON.stringify(next.strings) !== JSON.stringify(state.strings);
    state = {
      language: next.language || "en",
      setting: next.setting || "auto",
      direction: next.direction === "rtl" ? "rtl" : "ltr",
      languages: next.languages || state.languages,
      strings: next.strings || {},
    };
    compileTemplates();
    if (changed && announce) {
      window.dispatchEvent(new CustomEvent(EVENT_CHANGED, { detail: { language: state.language } }));
    }
  }

  // Last loaded texts, so menus built before Rose answers already speak the language
  try {
    const cached = JSON.parse(localStorage.getItem(CACHE_KEY) || "null");
    if (cached) apply(cached, false);
  } catch (e) {
    // no cache yet
  }

  async function load() {
    const bridge = window.__roseBridge;
    if (!bridge || !bridge.port) return;
    try {
      const response = await fetch(`http://127.0.0.1:${bridge.port}/i18n`, { cache: "no-store" });
      if (!response.ok) return;
      const next = await response.json();
      apply(next, true);
      localStorage.setItem(CACHE_KEY, JSON.stringify(state));
    } catch (e) {
      console.warn(`${LOG_PREFIX} Could not load the menu language:`, e);
    }
  }

  window.RoseI18n = Object.freeze({
    t,
    tAny,
    get language() { return state.language; },
    get setting() { return state.setting; },
    get direction() { return state.direction; },
    get languages() { return state.languages; },
    reload: load,
    onChange(callback) {
      const listener = (event) => callback(event.detail);
      window.addEventListener(EVENT_CHANGED, listener);
      return () => window.removeEventListener(EVENT_CHANGED, listener);
    },
  });

  // Load once the bridge is up, again whenever it reconnects or the language changes
  let attached = false;
  const attach = () => {
    const bridge = window.__roseBridge;
    if (!bridge) {
      setTimeout(attach, 250);
      return;
    }
    if (attached) return;
    attached = true;
    bridge.subscribe("language-changed", load);
    // onReady fires now if connected, then on every reconnect
    if (typeof bridge.onReady === "function") bridge.onReady(load);
    else load();
  };
  attach();
})();
