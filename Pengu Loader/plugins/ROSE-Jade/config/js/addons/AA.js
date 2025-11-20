import { settingsUtils } from "https://unpkg.com/blank-settings-utils@latest/Settings-Utils.js";

(() => {
    const LanguageManager = {
        getLanguage() {
            if (!document.documentElement || !document.body) {
                return 'en';
            }
            
            const htmlLang = document.documentElement.lang;
            if (htmlLang && (htmlLang.includes('ru') || htmlLang.includes('RU'))) {
                return 'ru';
            }
            if (htmlLang && (htmlLang.includes('zh') || htmlLang.includes('CN'))) {
                return 'zh';
            }
            
            const bodyClasses = document.body.className;
            if (bodyClasses.includes('lang-ru') || bodyClasses.includes('ru-RU') || bodyClasses.includes('typekit-lang-ru')) {
                return 'ru';
            }
            if (bodyClasses.includes('lang-zh') || bodyClasses.includes('zh-CN') || bodyClasses.includes('typekit-lang-zh')) {
                return 'zh';
            }
            
            const pageText = document.body.textContent;
            if (pageText.includes('Настройки') || pageText.includes('Язык') || pageText.includes('Русский')) {
                return 'ru';
            }
            if (pageText.includes('设置') || pageText.includes('语言') || pageText.includes('中文')) {
                return 'zh';
            }
            
            return 'en';
        },

        translations: {
            ru: {
                AAMatchFound: "Включить автоматическое принятие",
                AAHideModal: "Скрывать модальное окно",
                AAMuteSound: "Отключить звук"
            },
            zh: {
                AAMatchFound: "启用自动接受",
                AAHideModal: "隐藏模态窗口", 
                AAMuteSound: "静音"
            },
            en: {
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

    class RoseAA {
        constructor() {
            this.styleElement = null;
            this.apiCallTimeout = null;
            this.countdownInterval = null;
            this.countdownValue = 10;
            this.readyCheckTimeout = null;
            this.readyCheckStartTime = null;
            this.observer = null;
            this.originalXHR = null;
            this.settings = {
                RoseAA: true,
                hideModal: true,
                muteSound: true
            };
            this.init();
        }

        async init() {
            this.loadSettings();
            this.setupSoundMuting();
            this.startObservers();
            this.checkForUIChanges();
        }

        loadSettings() {
            const savedSettings = DataStore?.get("eaa-settings");
            if (savedSettings) {
                try {
                    const parsed = JSON.parse(savedSettings);
                    this.settings.RoseAA = parsed.RoseAA ?? true;
                    this.settings.hideModal = parsed.hideModal ?? true;
                    this.settings.muteSound = parsed.muteSound ?? true;
                } catch (e) {}
            }
        }

        setupSoundMuting() {
			this.originalXHR = window.XMLHttpRequest;
			const self = this;
			
			function PatchedXMLHttpRequest() {
				const xhr = new (self.originalXHR)();
				const originalSend = xhr.send;
				
				xhr.send = function(data) {
					const url = this._url || (this._method && this._url !== undefined ? this._url : null);
					
					if (self.settings.muteSound && url && (
						url.includes('sfx-readycheck-ringmagic-accepted-loop') || 
						url.includes('sfx-readycheck-sr-portal') ||
						url.includes('ready-check')
					)){
						return;
					}
					
					return originalSend.call(this, data);
				};
				
				return xhr;
			}
			
			for (const prop in self.originalXHR) {
				if (self.originalXHR.hasOwnProperty(prop)) {
					PatchedXMLHttpRequest[prop] = self.originalXHR[prop];
				}
			}
			
			PatchedXMLHttpRequest.prototype = self.originalXHR.prototype;
			window.XMLHttpRequest = PatchedXMLHttpRequest;
		}

        restoreSoundMuting() {
			if (this.originalXHR) {
				window.XMLHttpRequest = this.originalXHR;
				this.originalXHR = null;
			}
		}

        checkForMatch() {
            const dialogLargeElement = document.querySelector('.ready-check-timer');
            
            if (dialogLargeElement && !this.styleElement && (this.settings.RoseAA || this.settings.hideModal)) {
                if (!this.readyCheckStartTime) {
                    this.readyCheckStartTime = Date.now();
                }
                
                if (!this.readyCheckTimeout) {
                    this.readyCheckTimeout = setTimeout(() => {
                        this.forceCleanupReadyCheck();
                    }, 15000);
                }
                
                if (this.settings.hideModal) {
                    this.styleElement = document.createElement("style");
                    this.styleElement.appendChild(document.createTextNode(`
                        .modal { display: none !important }
                    `));
                    document.body.appendChild(this.styleElement);
                }

                this.countdownValue = 10;

                this.countdownInterval = setInterval(() => {
                    this.countdownValue--;
                    if (this.countdownValue <= 0) {
                        clearInterval(this.countdownInterval);
                    }
                }, 1000);

                if (this.settings.RoseAA) {
                    this.apiCallTimeout = setTimeout(() => {
                        fetch('/lol-matchmaking/v1/ready-check/accept', {
                            method: 'POST'
                        });
                    }, 1000);
                }
            } else if (!dialogLargeElement && (this.styleElement || this.readyCheckStartTime)) {
                this.cleanupReadyCheck();
            }
        }
        
        cleanupReadyCheck() {
            if (this.styleElement) {
                this.styleElement.parentNode.removeChild(this.styleElement);
                this.styleElement = null;
            }

            if (this.apiCallTimeout) clearTimeout(this.apiCallTimeout);
            if (this.countdownInterval) clearInterval(this.countdownInterval);
            if (this.readyCheckTimeout) clearTimeout(this.readyCheckTimeout);

            this.apiCallTimeout = null;
            this.countdownInterval = null;
            this.readyCheckTimeout = null;
            this.readyCheckStartTime = null;
        }

        forceCleanupReadyCheck() {
            this.cleanupReadyCheck();
            
            const readyCheckDialog = document.querySelector('.ready-check-timer');
            if (readyCheckDialog) {
                readyCheckDialog.style.display = 'none';
                
                const modal = document.querySelector('.modal');
                if (modal) {
                    modal.style.display = 'none';
                }
                
                const closeButtons = document.querySelectorAll('[aria-label="Close"], .close-button, [data-testid="close"]');
                closeButtons.forEach(button => {
                    if (button.offsetParent !== null) {
                        button.click();
                    }
                });
            }
        }

        checkForUIChanges() {
            this.checkForMatch();
        }

        startObservers() {
            setInterval(() => this.checkForUIChanges(), 1000);
            
            setInterval(() => {
                if (this.readyCheckStartTime) {
                    const timeSinceStart = Date.now() - this.readyCheckStartTime;
                    if (timeSinceStart > 20000) {
                        this.forceCleanupReadyCheck();
                    }
                }
            }, 5000);

            this.observer = new MutationObserver(() => {
                this.checkForUIChanges();
            });
            
            this.observer.observe(document.body, {
                childList: true, 
                subtree: true   
            });
        }

        destroy() {
            if (this.observer) {
                this.observer.disconnect();
            }
            this.cleanupReadyCheck();
            this.restoreSoundMuting();
        }
    }

    class RoseAASettings {
        constructor() {
            this.settings = {
                RoseAA: true,
                hideModal: true,
                muteSound: true
            };
            this.init();
        }

        async init() {
            this.loadSettings();
            this.initializeSettings();
        }

        loadSettings() {
            const savedSettings = DataStore?.get("eaa-settings");
            if (savedSettings) {
                try {
                    const parsed = JSON.parse(savedSettings);
                    this.settings.RoseAA = parsed.RoseAA ?? true;
                    this.settings.hideModal = parsed.hideModal ?? true;
                    this.settings.muteSound = parsed.muteSound ?? true;
                } catch (e) {}
            }
        }

        saveSettings() {
            if (window.DataStore) {
                DataStore.set("eaa-settings", JSON.stringify(this.settings));
            }
        }

        initializeSettings() {
            const addSettings = () => {
                const settingsContainer = document.querySelector(".eaa-settings");
                if (!settingsContainer) return;

                settingsContainer.innerHTML = `
                    <div class="lol-settings-general-row">
                        <div style="display: flex; flex-direction: column; gap: 15px; margin-top: 10px;">
                            <div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 0; border-bottom: thin solid #3c3c41;">
                                <lol-uikit-flat-checkbox ${this.settings.RoseAA ? 'class="checked"' : ''} style="margin-right: 15px;">
                                    <input slot="input" type="checkbox" ${this.settings.RoseAA ? 'checked' : ''}>
                                </lol-uikit-flat-checkbox>
                                <div style="display: flex; flex-direction: column; gap: 5px; flex: 1;">
                                    <p class="lol-settings-window-size-text" style="margin: 0; font-size: 12px; color: #a09b8c;">
                                        ${LanguageManager.t('AAMatchFound')}
                                    </p>
                                </div>
                            </div>

                            <div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 0; border-bottom: thin solid #3c3c41;">
                                <lol-uikit-flat-checkbox ${this.settings.hideModal ? 'class="checked"' : ''} style="margin-right: 15px;">
                                    <input slot="input" type="checkbox" ${this.settings.hideModal ? 'checked' : ''}>
                                </lol-uikit-flat-checkbox>
                                <div style="display: flex; flex-direction: column; gap: 5px; flex: 1;">
                                    <p class="lol-settings-window-size-text" style="margin: 0; font-size: 12px; color: #a09b8c;">
                                        ${LanguageManager.t('AAHideModal')}
                                    </p>
                                </div>
                            </div>

                            <div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 0; border-bottom: thin solid #3c3c41;">
                                <lol-uikit-flat-checkbox ${this.settings.muteSound ? 'class="checked"' : ''} style="margin-right: 15px;">
                                    <input slot="input" type="checkbox" ${this.settings.muteSound ? 'checked' : ''}>
                                </lol-uikit-flat-checkbox>
                                <div style="display: flex; flex-direction: column; gap: 5px; flex: 1;">
                                    <p class="lol-settings-window-size-text" style="margin: 0; font-size: 12px; color: #a09b8c;">
                                        ${LanguageManager.t('AAMuteSound')}
                                    </p>
                                </div>
                            </div>
                        </div>
                    </div>
                `;

                this.addEventListeners();
            };

            const observer = new MutationObserver((mutations) => {
                for (const mutation of mutations) {
                    for (const node of mutation.addedNodes) {
                        if (node.classList?.contains("eaa-settings")) {
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

        addEventListeners() {
            setTimeout(() => {
                const checkboxes = document.querySelectorAll('.eaa-settings lol-uikit-flat-checkbox');
                
                if (checkboxes[0]) {
                    const checkbox = checkboxes[0].querySelector('input[type="checkbox"]');
                    if (checkbox) {
                        checkbox.addEventListener('change', (e) => {
                            this.settings.RoseAA = e.target.checked;
                            this.saveSettings();
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
                }

                if (checkboxes[1]) {
                    const checkbox = checkboxes[1].querySelector('input[type="checkbox"]');
                    if (checkbox) {
                        checkbox.addEventListener('change', (e) => {
                            this.settings.hideModal = e.target.checked;
                            this.saveSettings();
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
                }

                if (checkboxes[2]) {
                    const checkbox = checkboxes[2].querySelector('input[type="checkbox"]');
                    if (checkbox) {
                        checkbox.addEventListener('change', (e) => {
                            this.settings.muteSound = e.target.checked;
                            this.saveSettings();
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
                }
            }, 100);
        }
    }

    const baseData = [
        {
            groupName: "RoseAA",
            titleKey: "el_RoseAA",
            titleName: "Rose / AutoAccept",
            capitalTitleKey: "el_RoseAA_capital", 
            capitalTitleName: "Rose / AutoAccept",
            element: [
                {
                    name: "eaa-settings", 
                    title: "el_RoseAA_settings",
                    titleName: "Settings",
                    class: "eaa-settings",
                    id: "RoseAASettings",
                },
            ],
        },
    ];

    window.addEventListener("load", () => {
        settingsUtils(window, baseData);
        new RoseAASettings();
        window.RoseAA = new RoseAA();
    });
})();