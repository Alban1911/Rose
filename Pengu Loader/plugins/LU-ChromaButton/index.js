/**
 * LU-ChromaButton Plugin
 * Creates a fake chroma button to replace the hidden official one
 */
(function createFakeChromaButton() {
  const LOG_PREFIX = "[LU-ChromaButton]";
  const BUTTON_CLASS = "lu-chroma-button";
  const BUTTON_SELECTOR = `.${BUTTON_CLASS}`;

  const CSS_RULES = `
    .${BUTTON_CLASS} {
      pointer-events: auto;
      -webkit-user-select: none;
      list-style-type: none;
      cursor: default;
      display: block !important;
      bottom: 0;
      height: 25px;
      left: 50%;
      position: absolute;
      transform: translateX(-50%) translateY(50%);
      width: 25px;
    }

    .${BUTTON_CLASS} .outer-mask {
      pointer-events: auto;
      -webkit-user-select: none;
      list-style-type: none;
      cursor: default;
      border-radius: 50%;
      box-shadow: 0 0 4px 1px rgba(1,10,19,.25);
      box-sizing: border-box;
      height: 100%;
      overflow: hidden;
      position: relative;
    }

    .${BUTTON_CLASS} .frame-color {
      pointer-events: auto;
      -webkit-user-select: none;
      list-style-type: none;
      cursor: default;
      background-image: linear-gradient(0deg,#695625 0,#a9852d 23%,#b88d35 93%,#c8aa6e);
      box-sizing: border-box;
      height: 100%;
      overflow: hidden;
      width: 100%;
      padding: 2px;
    }

    .${BUTTON_CLASS} .content {
      pointer-events: auto;
      -webkit-user-select: none;
      list-style-type: none;
      cursor: default;
      display: block;
      background: url(/fe/lol-champ-select/images/config/button-chroma.png) no-repeat;
      background-size: contain;
      border: 2px solid #010a13;
      border-radius: 50%;
      height: 16px;
      margin: 1px;
      width: 16px;
    }

    .${BUTTON_CLASS} .inner-mask {
      -webkit-user-select: none;
      list-style-type: none;
      cursor: default;
      border-radius: 50%;
      box-sizing: border-box;
      overflow: hidden;
      pointer-events: none;
      position: absolute;
      box-shadow: inset 0 0 4px 4px rgba(0,0,0,.75);
      width: calc(100% - 4px);
      height: calc(100% - 4px);
      left: 2px;
      top: 2px;
    }
  `;

  const log = {
    info: (msg, extra) => console.info(`${LOG_PREFIX} ${msg}`, extra ?? ""),
    warn: (msg, extra) => console.warn(`${LOG_PREFIX} ${msg}`, extra ?? ""),
    debug: (msg, extra) => console.debug(`${LOG_PREFIX} ${msg}`, extra ?? ""),
  };

  function injectCSS() {
    const styleId = "lu-chroma-button-css";
    if (document.getElementById(styleId)) {
      return;
    }

    const styleTag = document.createElement("style");
    styleTag.id = styleId;
    styleTag.textContent = CSS_RULES;
    document.head.appendChild(styleTag);
    log.debug("injected CSS rules");
  }

  function createFakeButton() {
    const button = document.createElement("div");
    button.className = BUTTON_CLASS;

    const outerMask = document.createElement("div");
    outerMask.className = "outer-mask interactive";

    const frameColor = document.createElement("div");
    frameColor.className = "frame-color";
    frameColor.style.padding = "2px";

    const content = document.createElement("div");
    content.className = "content";
    content.style.background = "";

    const innerMask = document.createElement("div");
    innerMask.className = "inner-mask inner-shadow";
    innerMask.style.width = "calc(100% - 4px)";
    innerMask.style.height = "calc(100% - 4px)";
    innerMask.style.left = "2px";
    innerMask.style.top = "2px";

    frameColor.appendChild(content);
    frameColor.appendChild(innerMask);
    outerMask.appendChild(frameColor);
    button.appendChild(outerMask);

    return button;
  }

  function ensureFakeButton(skinItem) {
    if (!skinItem) {
      return;
    }

    // Check if button already exists
    let existingButton = skinItem.querySelector(BUTTON_SELECTOR);
    if (existingButton) {
      return;
    }

    // Create and inject the fake button
    const fakeButton = createFakeButton();
    skinItem.appendChild(fakeButton);
    log.debug("created fake chroma button for skin item");
  }

  function scanSkinSelection() {
    const skinItems = document.querySelectorAll(".skin-selection-item");
    skinItems.forEach((skinItem) => {
      ensureFakeButton(skinItem);
    });
  }

  function setupObserver() {
    const observer = new MutationObserver(() => {
      scanSkinSelection();
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["class"],
    });

    // Periodic scan as safety net
    const intervalId = setInterval(scanSkinSelection, 500);

    // Return cleanup function
    return () => {
      observer.disconnect();
      clearInterval(intervalId);
    };
  }

  function init() {
    if (!document || !document.head) {
      requestAnimationFrame(init);
      return;
    }

    injectCSS();
    scanSkinSelection();
    setupObserver();
    log.info("fake chroma button creation active");
  }

  if (typeof document === "undefined") {
    log.warn("document unavailable; aborting");
    return;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();

