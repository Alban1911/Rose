import "./config/css/plug-th.css";
import * as observer from './config/js/main/observer.js';
import * as shadowDom from './config/js/main/shadowDom.js';
import { settingsUtils } from "https://unpkg.com/blank-settings-utils@latest/Settings-Utils.js";

const LOG_PREFIX = "[Rose-Jade]";

// Simple logging function - logs to browser console only
function log(level, message, data = null) {
    const consoleMethod = level === "error" ? console.error : level === "warn" ? console.warn : console.log;
    if (data) {
        consoleMethod(`${LOG_PREFIX} ${message}`, data);
    } else {
        consoleMethod(`${LOG_PREFIX} ${message}`);
    }
}

// Make logging function available globally for sub-modules
window.ROSEJadeLog = log;

const initializeObserver = async () => {
    try {
        if (observer && typeof observer.subscribeToElementCreation === 'function') {
            observer.subscribeToElementCreation('lol-regalia-emblem-element', (element) => {
                // Only apply border style if border plugin is enabled
                if (window.CONFIG && window.CONFIG.regaliaBorderEnabled) {
                    shadowDom.currentBorder(element);
                }
            });
        }
    } catch (error) {
        if (window.ROSEJadeLog) {
            window.ROSEJadeLog("error", "Failed to initialize observer", { error: error.message });
        }
    }
};

(() => {
    const DEFAULT_CONFIG = {
        regaliaBorderEnabled: false,
        regaliaBackgroundEnabled: false,
        regaliaBannerEnabled: false,
        regaliaIconEnabled: false,
        regaliaTitleEnabled: false,
        addonAAEnabled: false,
        addonWinLose: false,
        addonBckChangerEnabled: false
    };

    let CONFIG = { ...DEFAULT_CONFIG };

    const LanguageManager = {
        getLanguage() {
            if (!document.documentElement || !document.body) {
                return 'en';
            }

            const htmlLang = document.documentElement.lang;
            if (htmlLang && (htmlLang.includes('ru') || htmlLang.includes('RU'))) {
                this.saveLanguageToStorage('ru');
                return 'ru';
            }
            if (htmlLang && (htmlLang.includes('zh') || htmlLang.includes('CN'))) {
                this.saveLanguageToStorage('zh');
                return 'zh';
            }

            const bodyClasses = document.body.className;
            if (bodyClasses.includes('lang-ru') || bodyClasses.includes('ru-RU') || bodyClasses.includes('typekit-lang-ru')) {
                this.saveLanguageToStorage('ru');
                return 'ru';
            }
            if (bodyClasses.includes('lang-zh') || bodyClasses.includes('zh-CN') || bodyClasses.includes('typekit-lang-zh')) {
                this.saveLanguageToStorage('zh');
                return 'zh';
            }

            const pageText = document.body.textContent;
            if (pageText.includes('Настройки') || pageText.includes('Язык') || pageText.includes('Русский')) {
                this.saveLanguageToStorage('ru');
                return 'ru';
            }
            if (pageText.includes('设置') || pageText.includes('语言') || pageText.includes('中文')) {
                this.saveLanguageToStorage('zh');
                return 'zh';
            }

            this.saveLanguageToStorage('en');
            return 'en';
        },

        saveLanguageToStorage(language) {
            DataStore.set('Rose-language', language);
        },

        getLanguageFromStorage() {
            return DataStore.get('Rose-language') || 'en';
        },

        translations: {
            ru: {
                pluginSettings: "Настройка плагинов",
                restartRequired: "Требуется перезагрузка!",
                restartRequiredDesc: "Изменения вступят в силу после перезагрузки клиента",
                borderDesc: "Включить изменение Рамки",
                backgroundDesc: "Включить изменение Фона профиля",
                bannerDesc: "Включить изменение Знамя",
                iconDesc: "Включить изменение Иконки призывателя",
                TitleDesc: "Включить изменение Титула",
                restartButton: "Перезагрузить",
                addons: "Аддоны",
                addonAADesc: "Автопринятие игр",
                addonWinLoseDesc: "Включить отображение статистики игр",
                addonBckChangerDesc: "Скоро...",
                AAMatchFound: "Включить автоматическое принятие",
                AAHideModal: "Скрывать модальное окно",
                AAMuteSound: "Отключить звук"
            },
            zh: {
                pluginSettings: "插件设置",
                restartRequired: "需要重启！",
                restartRequiredDesc: "插件启用/禁用状态的更改将在重启客户端后生效",
                borderDesc: "启用边框更改",
                backgroundDesc: "启用背景更改",
                bannerDesc: "启用横幅更改",
                iconDesc: "启用图标更改",
                TitleDesc: "更改标题",
                restartButton: "重启",
                addons: "插件",
                addonAADesc: "自动接受游戏",
                addonWinLoseDesc: "Enable WinLose Stats",
                addonBckChangerDesc: "Coming soon...",
                AAMatchFound: "Enable Auto Accept",
                AAHideModal: "Hide Modal Window",
                AAMuteSound: "Mute Sound"
            },
            en: {
                pluginSettings: "PLUGINS",
                restartRequired: "Restart Required!",
                restartRequiredDesc: "Changes will take effect after restarting the client",
                borderDesc: "Enable Border changes",
                backgroundDesc: "Enable Background changes",
                bannerDesc: "Enable Banner changes",
                iconDesc: "Enable Icon changes",
                TitleDesc: "Enable Title changes",
                restartButton: "Restart",
                addons: "ADDONS",
                addonAADesc: "Auto Accept games",
                addonWinLoseDesc: "Enable WinLose Stats",
                addonBckChangerDesc: "Coming soon...",
                AAMatchFound: "Enable Auto Accept",
                AAHideModal: "Hide Modal Window",
                AAMuteSound: "Mute Sound"
            }
        },

        t(key) {
            const lang = this.getLanguage();
            const langTranslations = this.translations[lang] || this.translations.en;
            return langTranslations[key] || this.translations.en[key] || key;
        }
    };

    const baseData = [
        {
            groupName: "Rose",
            titleKey: "el_Rose",
            titleName: "Rose",
            capitalTitleKey: "el_Rose_capital",
            capitalTitleName: "Rose",
            element: [
                {
                    name: "Rose-plugin-settings",
                    title: "el_Rose_plugin_settings",
                    titleName: "PLUGINS",
                    class: "Rose-plugin-settings",
                    id: "RosePluginSettings",
                },
                {
                    name: "Rose-addon",
                    title: "el_Rose_addon",
                    titleName: "ADDONS",
                    class: "Rose-addon",
                    id: "RoseAddon",
                },
            ],
        },
    ];

    const overrideNavigationTitles = () => {
        setTimeout(() => {
            const navItems = document.querySelectorAll('lol-uikit-navigation-item');
            navItems.forEach(navItem => {
                const text = navItem.textContent?.trim();

                if (text === "Plugin Settings" || text === "Настройка плагинов" || text === "插件设置") {
                    const translatedText = LanguageManager.t('pluginSettings');
                    if (text !== translatedText) {
                        navItem.textContent = translatedText;
                    }
                }
                if (text === "Addons" || text === "Аддоны" || text === "插件") {
                    const translatedText = LanguageManager.t('addons');
                    if (text !== translatedText) {
                        navItem.textContent = translatedText;
                    }
                }
            });
        }, 1000);
    };

    const SettingsStore = {
        async loadSettings() {
            try {
                const settings = DataStore.get("Rose-plugin-settings");
                if (settings) {
                    const userSettings = JSON.parse(settings);
                    CONFIG = {
                        ...DEFAULT_CONFIG,
                        regaliaBorderEnabled: userSettings.regaliaBorderEnabled ?? DEFAULT_CONFIG.regaliaBorderEnabled,
                        regaliaBackgroundEnabled: userSettings.regaliaBackgroundEnabled ?? DEFAULT_CONFIG.regaliaBackgroundEnabled,
                        regaliaBannerEnabled: userSettings.regaliaBannerEnabled ?? DEFAULT_CONFIG.regaliaBannerEnabled,
                        regaliaIconEnabled: userSettings.regaliaIconEnabled ?? DEFAULT_CONFIG.regaliaIconEnabled,
                        regaliaTitleEnabled: userSettings.regaliaTitleEnabled ?? DEFAULT_CONFIG.regaliaTitleEnabled,
                        addonAAEnabled: userSettings.addonAAEnabled ?? DEFAULT_CONFIG.addonAAEnabled,
                        addonWinLose: userSettings.addonWinLose ?? DEFAULT_CONFIG.addonWinLose,
                        addonBckChangerEnabled: userSettings.addonBckChangerEnabled ?? DEFAULT_CONFIG.addonBckChangerEnabled
                    };
                    // Update global CONFIG reference
                    window.CONFIG = CONFIG;
                }
            } catch (error) { }
        },

        async saveSettings() {
            try {
                const settings = {
                    regaliaBorderEnabled: CONFIG.regaliaBorderEnabled,
                    regaliaBackgroundEnabled: CONFIG.regaliaBackgroundEnabled,
                    regaliaBannerEnabled: CONFIG.regaliaBannerEnabled,
                    regaliaIconEnabled: CONFIG.regaliaIconEnabled,
                    regaliaTitleEnabled: CONFIG.regaliaTitleEnabled,
                    addonAAEnabled: CONFIG.addonAAEnabled,
                    addonWinLose: CONFIG.addonWinLose,
                    addonBckChangerEnabled: CONFIG.addonBckChangerEnabled
                };
                DataStore.set("Rose-plugin-settings", JSON.stringify(settings));
            } catch (error) { }
        },
    };

    class RosePlugin {
        constructor() {
            this.init();
        }

        async init() {
            // Test log to verify logging is working
            if (window.ROSEJadeLog) {
                window.ROSEJadeLog("info", "ROSE-Jade plugin initializing");
            }
            await SettingsStore.loadSettings();
            // Expose CONFIG globally so plugins can check their enabled state
            window.CONFIG = CONFIG;
            this.initializeSettings();

            // Apply unified effect only if background plugin is enabled
            if (CONFIG.regaliaBackgroundEnabled) {
                if (window.Effect && typeof window.Effect.apply === 'function') {
                    window.Effect.apply('unified', { color: "#000000DA" });
                }
                this.loadPlugin("RegaliaBackground");
            }

            if (CONFIG.regaliaBorderEnabled) {
                this.loadPlugin("RegaliaBorder");
            }
            if (CONFIG.regaliaBannerEnabled) {
                this.loadPlugin("RegaliaBanner");
            }
            if (CONFIG.regaliaIconEnabled) {
                this.loadPlugin("RegaliaIcon");
            }
            if (CONFIG.regaliaTitleEnabled) {
                this.loadPlugin("RegaliaTitle");
            }
            if (CONFIG.addonAAEnabled) {
                this.loadAddon("AA");
            }
            if (CONFIG.addonWinLose) {
                this.loadAddon("WinLose");
            }
            if (CONFIG.addonBckChangerEnabled) {
                this.loadAddon("BckChanger");
            }
        }

        async loadPlugin(pluginName) {
            try {
                const pluginModule = await import(`./config/js/plugins/${pluginName}.js`);

                if (pluginModule.default) {
                    new pluginModule.default();
                } else if (typeof pluginModule === 'function') {
                    new pluginModule();
                } else if (pluginModule.init) {
                    pluginModule.init();
                }
            } catch (error) { }
        }

        async loadAddon(addonName) {
            try {
                const addonModule = await import(`./config/js/addons/${addonName}.js`);

                if (addonModule.default) {
                    new addonModule.default();
                } else if (typeof addonModule === 'function') {
                    new addonModule();
                } else if (addonModule.init) {
                    addonModule.init();
                }
            } catch (error) { }
        }

        initializeSettings() {
            this.initializePluginSettings();
            this.initializeAddonSettings();
        }

        initializePluginSettings() {
            const addSettings = () => {
                const settingsContainer = document.querySelector(".Rose-plugin-settings");
                if (!settingsContainer) return;

                settingsContainer.innerHTML = `
                    <div class="lol-settings-general-row">
                        <div style="display: flex; flex-direction: column; gap: 15px; margin-top: 10px;">
                            <div style="display: flex; align-items: flex-start; gap: 10px; padding: 10px; background: rgba(240, 230, 210, 0.1); border-radius: 4px; border-left: 3px solid #c8aa6e;">
                                <lol-uikit-icon icon="warning" style="color: #c8aa6e; margin-top: 2px;"></lol-uikit-icon>
                                <div style="display: flex; flex-direction: column; gap: 3px;">
                                    <p class="lol-settings-window-size-text" style="margin: 0; font-weight: bold; color: #f0e6d2;">
                                        ${LanguageManager.t('restartRequired')}
                                    </p>
                                    <p class="lol-settings-window-size-text" style="margin: 0; font-size: 12px; color: #a09b8c;">
                                        ${LanguageManager.t('restartRequiredDesc')}
                                    </p>
                                </div>
                            </div>
                        
                            <div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 0; border-bottom: thin solid #3c3c41;">
                                <lol-uikit-flat-checkbox ${CONFIG.regaliaBorderEnabled ? 'class="checked"' : ''} style="margin-right: 15px;">
                                    <input slot="input" type="checkbox" ${CONFIG.regaliaBorderEnabled ? 'checked' : ''}>
                                </lol-uikit-flat-checkbox>
                                <div style="display: flex; flex-direction: column; gap: 5px; flex: 1;">
                                    <p class="lol-settings-window-size-text" style="margin: 0; font-size: 12px; color: #a09b8c;">
                                        ${LanguageManager.t('borderDesc')}
                                    </p>
                                </div>
                            </div>

                            <div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 0; border-bottom: thin solid #3c3c41;">
                                <lol-uikit-flat-checkbox ${CONFIG.regaliaBackgroundEnabled ? 'class="checked"' : ''} style="margin-right: 15px;">
                                    <input slot="input" type="checkbox" ${CONFIG.regaliaBackgroundEnabled ? 'checked' : ''}>
                                </lol-uikit-flat-checkbox>
                                <div style="display: flex; flex-direction: column; gap: 5px; flex: 1;">
                                    <p class="lol-settings-window-size-text" style="margin: 0; font-size: 12px; color: #a09b8c;">
                                        ${LanguageManager.t('backgroundDesc')}
                                    </p>
                                </div>
                            </div>

                            <div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 0; border-bottom: thin solid #3c3c41;">
                                <lol-uikit-flat-checkbox ${CONFIG.regaliaBannerEnabled ? 'class="checked"' : ''} style="margin-right: 15px;">
                                    <input slot="input" type="checkbox" ${CONFIG.regaliaBannerEnabled ? 'checked' : ''}>
                                </lol-uikit-flat-checkbox>
                                <div style="display: flex; flex-direction: column; gap: 5px; flex: 1;">
                                    <p class="lol-settings-window-size-text" style="margin: 0; font-size: 12px; color: #a09b8c;">
                                        ${LanguageManager.t('bannerDesc')}
                                    </p>
                                </div>
                            </div>

                            <div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 0; border-bottom: thin solid #3c3c41;">
                                <lol-uikit-flat-checkbox ${CONFIG.regaliaIconEnabled ? 'class="checked"' : ''} style="margin-right: 15px;">
                                    <input slot="input" type="checkbox" ${CONFIG.regaliaIconEnabled ? 'checked' : ''}>
                                </lol-uikit-flat-checkbox>
                                <div style="display: flex; flex-direction: column; gap: 5px; flex: 1;">
                                    <p class="lol-settings-window-size-text" style="margin: 0; font-size: 12px; color: #a09b8c;">
                                        ${LanguageManager.t('iconDesc')}
                                    </p>
                                </div>
                            </div>
                            
                            <div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 0; border-bottom: thin solid #3c3c41;">
                                <lol-uikit-flat-checkbox ${CONFIG.regaliaTitleEnabled ? 'class="checked"' : ''} style="margin-right: 15px;">
                                    <input slot="input" type="checkbox" ${CONFIG.regaliaTitleEnabled ? 'checked' : ''}>
                                </lol-uikit-flat-checkbox>
                                <div style="display: flex; flex-direction: column; gap: 5px; flex: 1;">
                                    <p class="lol-settings-window-size-text" style="margin: 0; font-size: 12px; color: #a09b8c;">
                                        ${LanguageManager.t('TitleDesc')}
                                    </p>
                                </div>
                            </div>

                            <div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 0;">
                                <div style="display: flex; flex-direction: column; gap: 5px; flex: 1;">
                                    <p class="lol-settings-window-size-text" style="margin: 0; font-size: 12px; color: #a09b8c;">
                                    </p>
                                </div>
                                <lol-uikit-flat-button-secondary 
                                    id="restartClientBtn"
                                    style="margin-left: 15px;"
                                >
                                    ${LanguageManager.t('restartButton')}
                                </lol-uikit-flat-button-secondary>
                            </div>
                        </div>
                    </div>
                `;

                this.addPluginEventListeners();
            };

            const observer = new MutationObserver((mutations) => {
                for (const mutation of mutations) {
                    for (const node of mutation.addedNodes) {
                        if (node.classList?.contains("Rose-plugin-settings")) {
                            addSettings();
                            return;
                        }
                    }
                }
            });

            observer.observe(document.body, {
                childList: true,
                subtree: true,
            });
        }

        initializeAddonSettings() {
            const addSettings = () => {
                const settingsContainer = document.querySelector(".Rose-addon");
                if (!settingsContainer) return;

                settingsContainer.innerHTML = `
                    <div class="lol-settings-general-row">
                        <div style="display: flex; flex-direction: column; gap: 15px; margin-top: 10px;">
                            <div style="display: flex; align-items: flex-start; gap: 10px; padding: 10px; background: rgba(240, 230, 210, 0.1); border-radius: 4px; border-left: 3px solid #c8aa6e;">
                                <lol-uikit-icon icon="warning" style="color: #c8aa6e; margin-top: 2px;"></lol-uikit-icon>
                                <div style="display: flex; flex-direction: column; gap: 3px;">
                                    <p class="lol-settings-window-size-text" style="margin: 0; font-weight: bold; color: #f0e6d2;">
                                        ${LanguageManager.t('restartRequired')}
                                    </p>
                                    <p class="lol-settings-window-size-text" style="margin: 0; font-size: 12px; color: #a09b8c;">
                                        ${LanguageManager.t('restartRequiredDesc')}
                                    </p>
                                </div>
                            </div>
                        
                            <div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 0; border-bottom: thin solid #3c3c41;">
                                <lol-uikit-flat-checkbox ${CONFIG.addonAAEnabled ? 'class="checked"' : ''} style="margin-right: 15px;">
                                    <input slot="input" type="checkbox" ${CONFIG.addonAAEnabled ? 'checked' : ''}>
                                </lol-uikit-flat-checkbox>
                                <div style="display: flex; flex-direction: column; gap: 5px; flex: 1;">
                                    <p class="lol-settings-window-size-text" style="margin: 0; font-size: 12px; color: #a09b8c;">
                                        ${LanguageManager.t('addonAADesc')}
                                    </p>
                                </div>
                            </div>
							
							<div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 0; border-bottom: thin solid #3c3c41;">
                                <lol-uikit-flat-checkbox ${CONFIG.addonWinLose ? 'class="checked"' : ''} style="margin-right: 15px;">
                                    <input slot="input" type="checkbox" ${CONFIG.addonWinLose ? 'checked' : ''}>
                                </lol-uikit-flat-checkbox>
                                <div style="display: flex; flex-direction: column; gap: 5px; flex: 1;">
                                    <p class="lol-settings-window-size-text" style="margin: 0; font-size: 12px; color: #a09b8c;">
                                        ${LanguageManager.t('addonWinLoseDesc')}
                                    </p>
                                </div>
                            </div>

                            <div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 0;">
                                <div style="display: flex; flex-direction: column; gap: 5px; flex: 1;">
                                    <p class="lol-settings-window-size-text" style="margin: 0; font-size: 12px; color: #a09b8c;">
                                    </p>
                                </div>
                                <lol-uikit-flat-button-secondary 
                                    id="restartClientBtnAddons"
                                    style="margin-left: 15px;"
                                >
                                    ${LanguageManager.t('restartButton')}
                                </lol-uikit-flat-button-secondary>
                            </div>
                        </div>
                    </div>
                `;

                this.addAddonEventListeners();
            };

            const observer = new MutationObserver((mutations) => {
                for (const mutation of mutations) {
                    for (const node of mutation.addedNodes) {
                        if (node.classList?.contains("Rose-addon")) {
                            addSettings();
                            return;
                        }
                    }
                }
            });

            observer.observe(document.body, {
                childList: true,
                subtree: true,
            });
        }

        addPluginEventListeners() {
            const checkboxHandler = (checkboxId, configKey) => {
                const checkbox = document.querySelector(`#${checkboxId} input[type="checkbox"]`);
                if (checkbox) {
                    checkbox.addEventListener('change', (e) => {
                        const wasEnabled = CONFIG[configKey];
                        CONFIG[configKey] = e.target.checked;
                        // Update global CONFIG reference
                        if (window.CONFIG) {
                            window.CONFIG[configKey] = e.target.checked;
                        }
                        SettingsStore.saveSettings();

                        // Handle unified effect for background plugin
                        if (configKey === 'regaliaBackgroundEnabled') {
                            if (e.target.checked && !wasEnabled) {
                                // Enable background - apply unified effect
                                if (window.Effect && typeof window.Effect.apply === 'function') {
                                    window.Effect.apply('unified', { color: "#000000DA" });
                                }
                            } else if (!e.target.checked && wasEnabled) {
                                // Disable background - remove unified effect
                                if (window.Effect && typeof window.Effect.remove === 'function') {
                                    window.Effect.remove('unified');
                                } else if (window.Effect && typeof window.Effect.apply === 'function') {
                                    // Fallback: apply transparent effect to clear it
                                    window.Effect.apply('unified', { color: "#00000000" });
                                }
                            }
                        }

                        // Handle border plugin enable/disable
                        if (configKey === 'regaliaBorderEnabled') {
                            if (window.RegaliaBorder) {
                                if (e.target.checked && !wasEnabled) {
                                    // Enable border plugin
                                    window.RegaliaBorder.enabled = true;
                                    window.RegaliaBorder.startObserver();
                                } else if (!e.target.checked && wasEnabled) {
                                    // Disable border plugin - stop observer and revert borders
                                    window.RegaliaBorder.stop();
                                    // Remove border styles from shadow DOMs
                                    if (shadowDom && typeof shadowDom.removeBorderStyles === 'function') {
                                        shadowDom.removeBorderStyles();
                                    }
                                }
                            }
                        }

                        const flatCheckbox = checkbox.closest('lol-uikit-flat-checkbox');
                        if (flatCheckbox) {
                            if (e.target.checked) {
                                flatCheckbox.classList.add('checked');
                            } else {
                                flatCheckbox.classList.remove('checked');
                            }
                        }
                    });
                }
            };

            setTimeout(() => {
                const checkboxes = document.querySelectorAll('.Rose-plugin-settings lol-uikit-flat-checkbox');
                if (checkboxes[0]) {
                    checkboxes[0].id = 'borderCheckbox';
                    checkboxHandler('borderCheckbox', 'regaliaBorderEnabled');
                }
                if (checkboxes[1]) {
                    checkboxes[1].id = 'backgroundCheckbox';
                    checkboxHandler('backgroundCheckbox', 'regaliaBackgroundEnabled');
                }
                if (checkboxes[2]) {
                    checkboxes[2].id = 'bannerCheckbox';
                    checkboxHandler('bannerCheckbox', 'regaliaBannerEnabled');
                }
                if (checkboxes[3]) {
                    checkboxes[3].id = 'iconCheckbox';
                    checkboxHandler('iconCheckbox', 'regaliaIconEnabled');
                }
                if (checkboxes[4]) {
                    checkboxes[4].id = 'titleCheckbox';
                    checkboxHandler('titleCheckbox', 'regaliaTitleEnabled');
                }
            }, 100);

            const restartButton = document.querySelector('#restartClientBtn');
            if (restartButton) {
                restartButton.addEventListener('click', () => {
                    this.restartClient();
                });
            }
        }

        addAddonEventListeners() {
            const checkboxHandler = (checkboxId, configKey) => {
                const checkbox = document.querySelector(`#${checkboxId} input[type="checkbox"]`);
                if (checkbox) {
                    checkbox.addEventListener('change', (e) => {
                        CONFIG[configKey] = e.target.checked;
                        SettingsStore.saveSettings();

                        const flatCheckbox = checkbox.closest('lol-uikit-flat-checkbox');
                        if (flatCheckbox) {
                            if (e.target.checked) {
                                flatCheckbox.classList.add('checked');
                            } else {
                                flatCheckbox.classList.remove('checked');
                            }
                        }
                    });
                }
            };

            setTimeout(() => {
                const checkboxes = document.querySelectorAll('.Rose-addon lol-uikit-flat-checkbox');
                if (checkboxes[0]) {
                    checkboxes[0].id = 'aaCheckbox';
                    checkboxHandler('aaCheckbox', 'addonAAEnabled');
                }
                if (checkboxes[1]) {
                    checkboxes[1].id = 'WinLoseCheckbox';
                    checkboxHandler('WinLoseCheckbox', 'addonWinLose');
                }
            }, 100);

            const restartButton = document.querySelector('#restartClientBtnAddons');
            if (restartButton) {
                restartButton.addEventListener('click', () => {
                    this.restartClient();
                });
            }
        }

        restartClient() {
            window.location.reload();
        }
    }

    window.addEventListener("load", () => {
        // Initialize settings panel FIRST (synchronously, like other plugins)
        settingsUtils(window, baseData);

        // Then initialize other things
        overrideNavigationTitles();
        new RosePlugin();
        initializeObserver();
    });
})();