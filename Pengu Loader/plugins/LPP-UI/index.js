/**
 * Ensure champ-select treats disabled skins as visually unlocked by injecting
 * a companion stylesheet (and falling back to inline rules if it fails).
 */
(function enableLockedSkinPreview() {
  const LOG_PREFIX = '[LPP-UI][skin-preview]';
  const STYLE_ID = 'lpp-ui-unlock-skins-css';
  const INLINE_ID = `${STYLE_ID}-inline`;
  const STYLESHEET_NAME = 'style.css';
  const BORDER_CLASS = 'lpp-skin-border';
  const HIDDEN_CLASS = 'lpp-skin-hidden';
  const VISIBLE_OFFSETS = new Set([0, 1, 2, 3, 4]);

  const INLINE_RULES = `
    .skin-selection-carousel .skin-selection-item {
      position: relative;
      z-index: 1;
    }

    .skin-selection-carousel .skin-selection-item .skin-selection-item-information {
      position: relative;
      z-index: 2;
    }

    .skin-selection-carousel .skin-selection-item.disabled,
    .skin-selection-carousel .skin-selection-item[aria-disabled="true"] {
      filter: grayscale(0) saturate(1.1) contrast(1.05) !important;
      -webkit-filter: grayscale(0) saturate(1.1) contrast(1.05) !important;
      pointer-events: auto !important;
      cursor: pointer !important;
    }

    .skin-selection-carousel .skin-selection-item.disabled .skin-selection-thumbnail,
    .skin-selection-carousel .skin-selection-item[aria-disabled="true"] .skin-selection-thumbnail {
      filter: grayscale(0) saturate(1.15) contrast(1.05) !important;
      -webkit-filter: grayscale(0) saturate(1.15) contrast(1.05) !important;
      transition: filter 0.25s ease;
    }

    .skin-selection-carousel .skin-selection-item.disabled::before,
    .skin-selection-carousel .skin-selection-item.disabled::after,
    .skin-selection-carousel .skin-selection-item[aria-disabled="true"]::before,
    .skin-selection-carousel .skin-selection-item[aria-disabled="true"]::after,
    .skin-selection-carousel .skin-selection-item.disabled .skin-selection-thumbnail::before,
    .skin-selection-carousel .skin-selection-item.disabled .skin-selection-thumbnail::after,
    .skin-selection-carousel .skin-selection-item[aria-disabled="true"] .skin-selection-thumbnail::before,
    .skin-selection-carousel .skin-selection-item[aria-disabled="true"] .skin-selection-thumbnail::after {
      display: none !important;
    }

    .skin-selection-carousel .skin-selection-item.disabled .locked-state,
    .skin-selection-carousel .skin-selection-item[aria-disabled="true"] .locked-state {
      display: none !important;
    }

    .skin-selection-carousel .skin-selection-item.${HIDDEN_CLASS} {
      pointer-events: none !important;
    }

    .unlock-skin-hit-area {
      display: none !important;
      pointer-events: none !important;
    }

    .unlock-skin-hit-area .locked-state {
      display: none !important;
    }

 

    .skin-selection-carousel-container .skin-selection-carousel .skin-selection-item .skin-selection-thumbnail {
      height: 100% !important;
      margin: 0 !important;
      transition: filter 0.25s ease !important;
      transform: none !important;
    }

    .skin-selection-carousel-container .skin-selection-carousel .skin-selection-item.skin-selection-item-selected {
      background: #3c3c41 !important;
    }

    .skin-selection-carousel-container .skin-selection-carousel .skin-selection-item.skin-selection-item-selected .skin-selection-thumbnail {
      height: 100% !important;
      margin: 0 !important;
    }

    .skin-selection-carousel .skin-selection-item .lpp-skin-border {
      position: absolute;
      inset: 0;
      border: 2px solid transparent;
      border-image-source: linear-gradient(0deg, #4f4f54 0%, #3c3c41 50%, #29272b 100%);
      border-image-slice: 1;
      border-radius: inherit;
      box-sizing: border-box;
      pointer-events: none;
      z-index: 1;
    }

    .skin-selection-carousel .skin-selection-item.skin-carousel-offset-2 .lpp-skin-border {
      border: 2px solid transparent;
      border-image-source: linear-gradient(0deg, #c8aa6e 0%, #c89b3c 44%, #a07b32 59%, #785a28 100%);
      border-image-slice: 1;
      box-shadow: inset 0 0 0 1px rgba(1, 10, 19, 0.6);
    }


  `;

  const log = {
    info: (msg, extra) => console.info(`${LOG_PREFIX} ${msg}`, extra ?? ''),
    warn: (msg, extra) => console.warn(`${LOG_PREFIX} ${msg}`, extra ?? ''),
  };

  function resolveStylesheetHref() {
    try {
      const script =
        document.currentScript ||
        document.querySelector('script[src$="index.js"]') ||
        document.querySelector('script[src*="LPP-UI"]');

      if (script?.src) {
        return new URL(STYLESHEET_NAME, script.src).toString();
      }
    } catch (error) {
      log.warn('failed to resolve stylesheet URL; falling back to relative path', error);
    }

    return STYLESHEET_NAME;
  }

  function injectInlineRules() {
    if (document.getElementById(INLINE_ID)) {
      return;
    }

    const styleTag = document.createElement('style');
    styleTag.id = INLINE_ID;
    styleTag.textContent = INLINE_RULES;
    document.head.appendChild(styleTag);
    log.warn('applied inline fallback styling');
  }

  function removeInlineRules() {
    const existing = document.getElementById(INLINE_ID);
    if (existing) {
      existing.remove();
    }
  }

  function attachStylesheet() {
    if (document.getElementById(STYLE_ID)) {
      return;
    }

    const link = document.createElement('link');
    link.id = STYLE_ID;
    link.rel = 'stylesheet';
    link.href = resolveStylesheetHref();

    link.addEventListener('load', () => {
      removeInlineRules();
      log.info('external stylesheet loaded');
    });

    link.addEventListener('error', () => {
      link.remove();
      injectInlineRules();
    });

    document.head.appendChild(link);
  }

  function ensureBorderFrame(skinItem) {
    if (!skinItem) {
      return;
    }

    if (skinItem.querySelector(`.${BORDER_CLASS}`)) {
      return;
    }

    const border = document.createElement('div');
    border.className = BORDER_CLASS;
    border.setAttribute('aria-hidden', 'true');
    skinItem.appendChild(border);
  }

  function parseCarouselOffset(skinItem) {
    const offsetClass = Array.from(skinItem.classList).find((cls) => cls.startsWith('skin-carousel-offset'));
    if (!offsetClass) {
      return null;
    }

    const match = offsetClass.match(/skin-carousel-offset-(-?\d+)/);
    if (!match) {
      return null;
    }

    const value = Number.parseInt(match[1], 10);
    return Number.isNaN(value) ? null : value;
  }

  function isOffsetVisible(offset) {
    if (offset === null) {
      return true;
    }

    return VISIBLE_OFFSETS.has(offset);
  }

  function applyOffsetVisibility(skinItem) {
    if (!skinItem) {
      return;
    }

    const offset = parseCarouselOffset(skinItem);
    const shouldBeVisible = isOffsetVisible(offset);

    skinItem.classList.toggle('lpp-visible-skin', shouldBeVisible);
    skinItem.classList.toggle(HIDDEN_CLASS, !shouldBeVisible);

    if (shouldBeVisible) {
      skinItem.style.removeProperty('pointer-events');
    } else {
      skinItem.style.setProperty('pointer-events', 'none', 'important');
    }
  }

  function scanSkinSelection() {
    document.querySelectorAll('.skin-selection-item').forEach((skinItem) => {
      ensureBorderFrame(skinItem);
      applyOffsetVisibility(skinItem);
    });
  }

  function setupSkinObserver() {
    const observer = new MutationObserver(() => {
      scanSkinSelection();
    });
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['class'],
    });

    // Re-scan periodically as a safety net (LCU sometimes swaps DOM wholesale)
    const intervalId = setInterval(scanSkinSelection, 500);

    const handleResize = () => {
      scanSkinSelection();
    };
    window.addEventListener('resize', handleResize, { passive: true });

    document.addEventListener(
      'visibilitychange',
      () => {
        if (document.visibilityState === 'visible') {
          scanSkinSelection();
        }
      },
      false
    );

    // Return cleanup in case we ever need it
    return () => {
      observer.disconnect();
      clearInterval(intervalId);
      window.removeEventListener('resize', handleResize);
    };
  }

  function init() {
    if (!document || !document.head) {
      requestAnimationFrame(init);
      return;
    }

    attachStylesheet();
    scanSkinSelection();
    setupSkinObserver();
    log.info('skin preview overrides active');
  }

  if (typeof document === 'undefined') {
    log.warn('document unavailable; aborting');
    return;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();

