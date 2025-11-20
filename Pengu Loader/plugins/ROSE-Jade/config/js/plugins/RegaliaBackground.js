const baseData = [
    {
        groupName: "RoseBackground",
        titleKey: "el_RoseBackground",
        titleName: "Rose / Background",
        capitalTitleKey: "el_RoseBackground_capital", 
        capitalTitleName: "Rose / Background",
        element: [
            {
                name: "bgcm-settings", 
                title: "el_RoseBackground_settings",
                titleName: "Settings",
                class: "bgcm-settings",
                id: "RoseBackgroundSettings",
            },
        ],
    },
];

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
                BlurAmount: "Степень размытия",
            },
            zh: {
                BlurAmount: "模糊强度",
            },
            en: {
                BlurAmount: "Blur Amount",
            }
        },

        t(key) {
            const lang = this.getLanguage();
            const langTranslations = this.translations[lang] || this.translations.en;
            return langTranslations[key] || this.translations.en[key] || key;
        }
    };

    const CONFIG = {
        STYLE_ID: "bgcm-button-style",
        BUTTON_ID: "bgcm-custom-button",
        MODAL_ID: "bgcm-modal"
    };

    let skinData = [];
    let previewGroups = [];
    let currentSearchQuery = "";
    let selectedSkinId = null;
    let searchTimeout = null;
    let currentPage = 1;
    const ITEMS_PER_PAGE = 32;

    class BGCM {
        constructor() {
            this.buttonCreated = false;
            this.customButton = null;
            this.currentBackgroundType = 'image';
            this.dataLoaded = false;
            this.blurObserver = null;
            this.isChampionSelectActive = false;
            this.championSelectObserver = null;
            this.settings = {
                blurAmount: 5
            };
            this.init();
        }

        async init() {
            this.loadSettings();
            this.loadData();
            this.buttonContainerObserver();
            this.applyCustomBackground();
            this.setupChampionSelectObserver();
            
            if (window.DataStore) {
                selectedSkinId = window.DataStore.get('bgcm-selected-skin-id');
            }
        }

        loadSettings() {
            const savedSettings = DataStore?.get("bgcm-settings");
            if (savedSettings) {
                try {
                    const parsed = JSON.parse(savedSettings);
                    this.settings.blurAmount = parsed.blurAmount ?? 5;
                } catch (e) {}
            }
        }

        saveSettings() {
            if (window.DataStore) {
                DataStore.set("bgcm-settings", JSON.stringify(this.settings));
            }
        }

        setupChampionSelectObserver() {
            this.championSelectObserver = new MutationObserver((mutations) => {
                const championSelectElement = document.querySelector('.champion-select-main-container');
                
                if (championSelectElement && championSelectElement.offsetParent !== null) {
                    if (!this.isChampionSelectActive) {
                        this.isChampionSelectActive = true;
                        this.disablePlugin();
                    }
                } else {
                    if (this.isChampionSelectActive) {
                        this.isChampionSelectActive = false;
                        this.enablePlugin();
                    }
                }
            });

            this.championSelectObserver.observe(document.body, {
                childList: true,
                subtree: true,
                attributes: true,
                attributeFilter: ['style', 'class']
            });

            const initialCheck = document.querySelector('.champion-select-main-container');
            if (initialCheck && initialCheck.offsetParent !== null) {
                this.isChampionSelectActive = true;
                this.disablePlugin();
            }
        }

        disablePlugin() {
            this.removeCustomBackground();
            
            if (this.customButton && document.body.contains(this.customButton)) {
                this.customButton.remove();
                this.customButton = null;
                this.buttonCreated = false;
            }
            
            const modal = document.getElementById(CONFIG.MODAL_ID);
            if (modal) {
                modal.remove();
            }
        }

        enablePlugin() {
            this.applyCustomBackground();
            
            const isContainerVisible = this.isButtonContainerVisible();
            if (isContainerVisible && !this.buttonCreated) {
                this.customButton = this.createCustomButton();
                this.customButton.addEventListener('click', () => this.handleButtonClick());
                this.buttonCreated = true;
            }
        }

        async loadData() {
            try {
                const endpoints = [
                    "https://raw.communitydragon.org/pbe/plugins/rcp-be-lol-game-data/global/default/v1/skins.json"
                ];

                let skinsResponse = null;
                for (const endpoint of endpoints) {
                    try {
                        skinsResponse = await fetch(endpoint);
                        if (skinsResponse.ok) break;
                    } catch (e) {
                        continue;
                    }
                }

                if (!skinsResponse || !skinsResponse.ok) {
                    return;
                }

                const skinsRaw = await skinsResponse.json();

                let skinsArray = [];
                if (Array.isArray(skinsRaw)) {
                    skinsArray = skinsRaw;
                } else if (typeof skinsRaw === 'object') {
                    skinsArray = this.extractSkinsOptimized(skinsRaw);
                }

                const uniqueSkins = new Map();
                skinsArray.forEach(skin => {
                    if (skin && skin.id && !uniqueSkins.has(skin.id)) {
                        uniqueSkins.set(skin.id, skin);
                    }
                });
                
                skinData = Array.from(uniqueSkins.values()).flatMap(skin => this.processSkinData(skin));
                
                await this.loadTFTData();
                
                this.dataLoaded = true;

            } catch (error) {
                this.dataLoaded = true;
            }
        }

        extractSkinsOptimized(obj) {
            const skins = [];
            
            if (typeof obj === 'object') {
                for (const key in obj) {
                    if (obj.hasOwnProperty(key)) {
                        const item = obj[key];
                        
                        if (item && typeof item === 'object' && item.id !== undefined && item.name !== undefined) {
                            skins.push(item);
                            
                            if (item.questSkinInfo?.tiers) {
                                item.questSkinInfo.tiers.forEach(tier => {
                                    if (tier?.id !== undefined && tier.name !== undefined) {
                                        skins.push(tier);
                                    }
                                });
                            }
                        }
                    }
                }
            }
            
            return skins;
        }

        async loadTFTData() {
            try {
                const tftEndpoints = [
                    "https://raw.communitydragon.org/pbe/plugins/rcp-be-lol-game-data/global/default/v1/tftrotationalshopitemdata.json"
                ];

                let tftResponse = null;
                for (const endpoint of tftEndpoints) {
                    try {
                        tftResponse = await fetch(endpoint);
                        if (tftResponse.ok) break;
                    } catch (e) {
                        continue;
                    }
                }

                if (!tftResponse || !tftResponse.ok) {
                    return;
                }

                const tftRaw = await tftResponse.json();
                const tftArray = Array.isArray(tftRaw) ? tftRaw : [];

                const companionItems = tftArray
                    .filter(item => 
                        item && 
                        item.descriptionTraKey &&
                        item.descriptionTraKey.toLowerCase().startsWith("companion") &&
                        item.backgroundTextureLCU
                    )
                    .map(item => this.processTFTItem(item));

                skinData.push(...companionItems);

            } catch (error) {}
        }

        processTFTItem(item) {
            const cleanPath = (path) => {
                if (!path) return "";
                return path
                    .replace(/^ASSETS\//i, "")
                    .toLowerCase();
            };

            const cleanBackgroundTexture = cleanPath(item.backgroundTextureLCU);
            const cleanLargeIcon = cleanPath(item.standaloneLoadoutsLargeIcon);

            return {
                id: `tft-${item.id || Math.random()}`,
                name: item.name || "TFT Companion",
                tilePath: cleanLargeIcon
                    ? `https://raw.communitydragon.org/pbe/plugins/rcp-be-lol-game-data/global/default/assets/${cleanLargeIcon}`
                    : "",
                splashPath: cleanBackgroundTexture
                    ? `https://raw.communitydragon.org/pbe/plugins/rcp-be-lol-game-data/global/default/assets/${cleanBackgroundTexture}`
                    : "",
                uncenteredSplashPath: cleanBackgroundTexture
                    ? `https://raw.communitydragon.org/pbe/plugins/rcp-be-lol-game-data/global/default/assets/${cleanBackgroundTexture}`
                    : "",
                splashVideoPath: "",
                collectionSplashVideoPath: "",
                isAnimated: false,
                isTFT: true,
                skinLineId: null,
                skinLineName: null
            };
        }

        processSkinData(skin) {
            if (!skin) return [];

            const cleanPath = (path) => {
                if (!path) return "";
                return path
                    .replace(/^\/lol-game-data\/assets\/ASSETS\//i, "")
                    .toLowerCase();
            };

            const baseSkin = {
                ...skin,
                tilePath: cleanPath(skin.tilePath)
                    ? `https://raw.communitydragon.org/pbe/plugins/rcp-be-lol-game-data/global/default/assets/${cleanPath(skin.tilePath)}`
                    : skin.tilePath || "/lol-game-data/assets/v1/profile-icons/1.jpg",
                splashPath: cleanPath(skin.splashPath)
                    ? `https://raw.communitydragon.org/pbe/plugins/rcp-be-lol-game-data/global/default/assets/${cleanPath(skin.splashPath)}`
                    : skin.splashPath || skin.tilePath || "/lol-game-data/assets/v1/profile-icons/1.jpg",
                uncenteredSplashPath: cleanPath(skin.uncenteredSplashPath)
                    ? `https://raw.communitydragon.org/pbe/plugins/rcp-be-lol-game-data/global/default/assets/${cleanPath(skin.uncenteredSplashPath)}`
                    : "",
                splashVideoPath: cleanPath(skin.splashVideoPath)
                    ? `https://raw.communitydragon.org/pbe/plugins/rcp-be-lol-game-data/global/default/assets/${cleanPath(skin.splashVideoPath)}`
                    : "",
                collectionSplashVideoPath: cleanPath(skin.collectionSplashVideoPath)
                    ? `https://raw.communitydragon.org/pbe/plugins/rcp-be-lol-game-data/global/default/assets/${cleanPath(skin.collectionSplashVideoPath)}`
                    : "",
                isAnimated: false,
                isTFT: false,
            };

            const skins = [baseSkin];

            if (skin.splashVideoPath || skin.collectionSplashVideoPath) {
                const videoPath = skin.splashVideoPath || skin.collectionSplashVideoPath;
                skins.push({
                    ...skin,
                    id: `${skin.id}-animated`,
                    name: `${skin.name} (Animated)`,
                    tilePath: baseSkin.tilePath,
                    splashPath: cleanPath(videoPath)
                        ? `https://raw.communitydragon.org/pbe/plugins/rcp-be-lol-game-data/global/default/assets/${cleanPath(videoPath)}`
                        : baseSkin.splashPath,
                    uncenteredSplashPath: cleanPath(videoPath)
                        ? `https://raw.communitydragon.org/pbe/plugins/rcp-be-lol-game-data/global/default/assets/${cleanPath(videoPath)}`
                        : "",
                    splashVideoPath: cleanPath(videoPath)
                        ? `https://raw.communitydragon.org/pbe/plugins/rcp-be-lol-game-data/global/default/assets/${cleanPath(videoPath)}`
                        : "",
                    isAnimated: true,
                    isTFT: false,
                });
            }

            return skins;
        }

        setCustomBackground(url, isAnimated = false, skinId = null) {
            if (this.isChampionSelectActive) return;
            
            this.removeCustomBackground();

            this.currentBackgroundType = isAnimated ? 'video' : 'image';

            if (isAnimated) {
                this.createVideoBackground(url);
            } else {
                this.createImageElementBackground(url);
            }
            
            if (window.DataStore) {
                window.DataStore.set('bgcm-selected-background', url);
                window.DataStore.set('bgcm-background-type', this.currentBackgroundType);
                if (skinId) {
                    selectedSkinId = skinId;
                    window.DataStore.set('bgcm-selected-skin-id', skinId);
                }
            }
        }

        updateBlur() {
            const profileInfo = document.querySelector('.style-profile-summoner-info-component');
            const shouldBlur = !(profileInfo && profileInfo.offsetParent !== null);
            
            const image = document.getElementById('bgcm-custom-image');
            const video = document.getElementById('bgcm-custom-video');
            
            const blurAmount = shouldBlur ? `${this.settings.blurAmount}px` : '0px';
            
            if (image) image.style.filter = `blur(${blurAmount})`;
            if (video) video.style.filter = `blur(${blurAmount})`;
        }

        createImageElementBackground(url) {
            this.cleanupInlineStyles();

            const img = document.createElement('img');
            img.id = 'bgcm-custom-image';
            img.src = url;
            
            img.style.cssText = `
                position: fixed;
                top: 0;
                left: 0;
                width: 100vw;
                height: 100vh;
                object-fit: cover;
                z-index: -1;
                pointer-events: none;
                transition: filter 0.5s ease-in-out;
            `;

            this.updateBlur();
            
            this.blurObserver = new MutationObserver(() => {
                this.updateBlur();
            });
            
            this.blurObserver.observe(document.body, {
                childList: true,
                subtree: true,
                attributes: true,
                attributeFilter: ['style', 'class']
            });

            document.body.appendChild(img);

            const style = document.createElement('style');
            style.id = 'bgcm-custom-style';
            style.textContent = `
                lol-uikit-background-switcher-image,
                .lol-uikit-background-switcher-image,
                [class*="background-switcher"],
                [src*="parties-background"],
                [src*="background"] {
                    display: none !important;
                    visibility: hidden !important;
                }

                #bgcm-custom-image {
                    display: block !important;
                    visibility: visible !important;
                }

                #bgcm-custom-video {
                    display: none !important;
                }
            `;
            
            document.head.appendChild(style);
        }

        createVideoBackground(url) {
            this.cleanupInlineStyles();

            const video = document.createElement('video');
            video.id = 'bgcm-custom-video';
            video.src = url;
            video.autoplay = true;
            video.loop = true;
            video.muted = true;
            video.playsInline = true;
            
            video.style.cssText = `
                position: fixed;
                top: 0;
                left: 0;
                width: 100vw;
                height: 100vh;
                object-fit: cover;
                z-index: -1;
                pointer-events: none;
                transition: filter 0.5s ease-in-out;
            `;

            this.updateBlur();
            
            this.blurObserver = new MutationObserver(() => {
                this.updateBlur();
            });
            
            this.blurObserver.observe(document.body, {
                childList: true,
                subtree: true,
                attributes: true,
                attributeFilter: ['style', 'class']
            });

            video.onerror = () => {
                const imageUrl = url.replace('-animated', '').replace('(Animated)', '').trim();
                this.setCustomBackground(imageUrl, false);
            };

            document.body.appendChild(video);

            const style = document.createElement('style');
            style.id = 'bgcm-custom-style';
            style.textContent = `
                lol-uikit-background-switcher-image,
                .lol-uikit-background-switcher-image,
                [class*="background-switcher"],
                [src*="parties-background"],
                [src*="background"] {
                    display: none !important;
                    visibility: hidden !important;
                }

                #bgcm-custom-video {
                    display: block !important;
                    visibility: visible !important;
                }
            `;
            
            document.head.appendChild(style);
        }

        cleanupInlineStyles() {
            const selectors = [
                'lol-uikit-background-switcher-image',
                '.lol-uikit-background-switcher-image',
                '[class*="background"]',
                '[src*="parties-background"]',
                '[src*="background"]'
            ];

            selectors.forEach(selector => {
                const elements = document.querySelectorAll(selector);
                elements.forEach(element => {
                    element.style.backgroundImage = '';
                    element.style.display = '';
                    element.style.visibility = '';
                });
            });
        }

        removeCustomBackground() {
            const style = document.getElementById('bgcm-custom-style');
            if (style) {
                style.remove();
            }
            
            const video = document.getElementById('bgcm-custom-video');
            if (video) {
                video.remove();
            }
            
            const img = document.getElementById('bgcm-custom-image');
            if (img) {
                img.remove();
            }
            
            if (this.blurObserver) {
                this.blurObserver.disconnect();
                this.blurObserver = null;
            }
            
            this.cleanupInlineStyles();
        }

        applyCustomBackground() {
            if (this.isChampionSelectActive) return;
            
            const savedBackground = window.DataStore?.get('bgcm-selected-background');
            const backgroundType = window.DataStore?.get('bgcm-background-type') || 'image';
            
            if (savedBackground) {
                this.setCustomBackground(savedBackground, backgroundType === 'video');
            }
        }

        generatePreviewGroups() {
            previewGroups = [];

            if (!this.dataLoaded) {
                return;
            }

            const lolGroup = {
                title: "LoL Skins",
                items: []
            };
            
            const tftGroup = {
                title: "TFT Companions",
                items: []
            };
            
            skinData.forEach((skin) => {
                if (!skin || !skin.name) return;
                
                if (skin.isTFT) {
                    tftGroup.items.push({
                        id: skin.id || Math.random(),
                        name: skin.name,
                        tilePath: skin.tilePath,
                        splashPath: skin.splashPath,
                        uncenteredSplashPath: skin.uncenteredSplashPath,
                        splashVideoPath: skin.splashVideoPath,
                        skinLineId: null,
                        skinLineName: null,
                        isAnimated: skin.isAnimated,
                        isTFT: true,
                    });
                } else {
                    lolGroup.items.push({
                        id: skin.id || Math.random(),
                        name: skin.name,
                        tilePath: skin.tilePath,
                        splashPath: skin.splashPath,
                        uncenteredSplashPath: skin.uncenteredSplashPath,
                        splashVideoPath: skin.splashVideoPath,
                        skinLineId: null,
                        skinLineName: null,
                        isAnimated: skin.isAnimated,
                        isTFT: false,
                    });
                }
            });

            lolGroup.items.sort((a, b) => a.name.localeCompare(b.name));
            tftGroup.items.sort((a, b) => a.name.localeCompare(b.name));

            if (lolGroup.items.length > 0) {
                previewGroups.push(lolGroup);
            }
            
            if (tftGroup.items.length > 0) {
                previewGroups.push(tftGroup);
            }

            const customBackgrounds = window.DataStore?.get("customBackgrounds") || [];
            const customGroup = {
                title: "Custom Background",
                items: customBackgrounds.map((item, index) => ({
                    id: `custom-${index}`,
                    name: item.name,
                    tilePath: item.tilePath,
                    splashPath: item.splashPath,
                    uncenteredSplashPath: item.uncenteredSplashPath,
                    skinLineId: null,
                    isTFT: false,
                    isAnimated: item.isAnimated,
                })),
            };
            customGroup.items.sort((a, b) => a.name.localeCompare(b.name));
            previewGroups.push(customGroup);
        }

        buttonContainerObserver() {
            const checkInterval = setInterval(() => {
                if (this.isChampionSelectActive) return;
                
                const isContainerVisible = this.isButtonContainerVisible();
                
                if (isContainerVisible) {
                    if (!this.buttonCreated) {
                        this.customButton = this.createCustomButton();
                        this.customButton.addEventListener('click', () => this.handleButtonClick());
                        this.buttonCreated = true;
                    }
                } else {
                    if (this.buttonCreated && this.customButton) {
                        if (document.body.contains(this.customButton)) {
                            this.customButton.style.transition = 'opacity 0.2s ease';
                            this.customButton.style.opacity = '0';
                            setTimeout(() => {
                                if (document.body.contains(this.customButton)) {
                                    document.body.removeChild(this.customButton);
                                }
                            }, 200);
                        }
                        this.customButton = null;
                        this.buttonCreated = false;
                    }
                }
            }, 250);
        }

        isButtonContainerVisible() {
            const container = document.querySelector('.lol-social-sidebar');
            return container && container.offsetParent !== null;
        }

        createCustomButton() {
            const button = document.createElement('button');
            button.id = CONFIG.BUTTON_ID;
            
            const img = document.createElement('img');
            img.src = '/fe/lol-uikit/images/icon_settings.png';
            img.style.width = '15px';
            img.style.height = '15px';
            img.style.display = 'block';
            
            button.appendChild(img);
            button.style.position = 'absolute';
            button.style.top = '10px';
            button.style.right = '200px';
            button.style.zIndex = '9999';
            button.style.padding = '5px';
            button.style.backgroundColor = '#1e292c';
            button.style.border = 'var(--plug-jsbutton-color)';
            button.style.borderRadius = '50%';
            button.style.cursor = 'pointer';
            button.style.width = '20px';
            button.style.height = '20px';
            button.style.display = 'flex';
            button.style.alignItems = 'center';
            button.style.justifyContent = 'center';
            button.style.boxShadow = '0 2px 10px rgba(0,0,0,0.3)';
            button.style.transition = 'all 0.3s ease';
            button.style.opacity = '0';
            
            document.body.appendChild(button);
            
            setTimeout(() => {
                button.style.transition = 'opacity 0.2s ease, all 0.3s ease';
                button.style.opacity = '1';
            }, 10);
            
            button.addEventListener('mouseenter', () => {
                button.style.backgroundColor = '#253236';
                button.style.transform = 'scale(1.1)';
                button.style.boxShadow = '0 4px 15px rgba(0,0,0,0.4)';
            });
            
            button.addEventListener('mouseleave', () => {
                button.style.backgroundColor = '#1e292c';
                button.style.transform = 'scale(1)';
                button.style.boxShadow = '0 2px 10px rgba(0,0,0,0.3)';
            });
            
            return button;
        }

        handleButtonClick() {
            if (this.isChampionSelectActive) return;
            this.showModal();
        }

        async showModal() {
            document.getElementById(CONFIG.MODAL_ID)?.remove();

            const modal = document.createElement('div');
            modal.id = CONFIG.MODAL_ID;
            modal.style.position = 'fixed';
            modal.style.top = '0';
            modal.style.left = '0';
            modal.style.width = '100%';
            modal.style.height = '100%';
            modal.style.backgroundColor = 'rgba(0,0,0,0.8)';
            modal.style.zIndex = '10000';
            modal.style.display = 'flex';
            modal.style.alignItems = 'center';
            modal.style.justifyContent = 'center';
            
            const content = document.createElement('div');
            content.style.backgroundColor = '#131312';
            content.style.padding = '10px';
            content.style.borderRadius = '15px';
            content.style.maxWidth = '1200px';
            content.style.width = '80%';
            content.style.maxHeight = '600px';
            content.style.height = '100%';
            content.style.overflow = 'hidden';
            content.style.boxShadow = '0 0 30px rgba(0,0,0,0.7)';
            content.style.position = 'relative';
            content.style.boxSizing = 'border-box';
            content.style.display = 'flex';
            content.style.flexDirection = 'column';

            const logoUrl = 'https://plugins/Rose/assets/logo.png';
            const testImg = new Image();
            testImg.onload = () => {
                const logoBackground = document.createElement('div');
                logoBackground.style.position = 'absolute';
                logoBackground.style.top = '0';
                logoBackground.style.left = '0';
                logoBackground.style.width = '100%';
                logoBackground.style.height = '100%';
                logoBackground.style.backgroundImage = `url('${logoUrl}')`;
                logoBackground.style.backgroundSize = '600px';
                logoBackground.style.backgroundRepeat = 'no-repeat';
                logoBackground.style.backgroundPosition = '-70px -70px';
                logoBackground.style.zIndex = '0';
                logoBackground.style.pointerEvents = 'none';
                logoBackground.style.animation = 'logoGlow 3s ease-in-out infinite alternate';
                logoBackground.style.transformOrigin = 'center center';
                logoBackground.style.opacity = '0.2';
                content.appendChild(logoBackground);
            };
            testImg.src = logoUrl;

            const reminder = document.createElement('div');
            reminder.style.color = 'var(--plug-color1)';
            reminder.style.fontSize = '9px';
            reminder.style.fontWeight = 'bold';
            reminder.style.fontFamily = 'Montserrat, sans-serif';
            reminder.style.textAlign = 'right';
            reminder.style.padding = '10px';
            reminder.style.marginRight = '30px';
            reminder.style.marginBottom = '0px';
            reminder.textContent = 'REMEMBER: ONLY YOU CAN SEE CHANGES';
            reminder.className = 'soft-text-glow';
            content.appendChild(reminder);

            const searchContainer = document.createElement('div');
            searchContainer.style.position = 'absolute';
            searchContainer.style.top = '15px';
            searchContainer.style.left = '15px';
            searchContainer.style.zIndex = '10001';

            const searchInput = document.createElement('input');
            searchInput.type = 'text';
            searchInput.placeholder = 'Search...';
            searchInput.className = 'search-input';
            searchContainer.appendChild(searchInput);
            content.appendChild(searchContainer);
            
            const closeBtn = document.createElement('button');
            closeBtn.style.position = 'absolute';
            closeBtn.style.top = '15px';
            closeBtn.style.right = '15px';
            closeBtn.style.width = '16px';
            closeBtn.style.height = '16px';
            closeBtn.style.backgroundColor = 'var(--plug-color1)';
            closeBtn.style.borderRadius = '50%';
            closeBtn.style.border = 'none';
            closeBtn.style.cursor = 'pointer';
            closeBtn.style.display = 'flex';
            closeBtn.style.alignItems = 'center';
            closeBtn.style.justifyContent = 'center';
            
            closeBtn.addEventListener('mouseenter', () => {
                closeBtn.style.animation = 'ColorUp 0.3s forwards';
            });

            closeBtn.addEventListener('mouseleave', () => {
                closeBtn.style.animation = 'ColorDown 0.25s forwards';
            });
            
            const closeModal = () => {
                searchInput.value = '';
                currentSearchQuery = '';
                currentPage = 1;
                document.body.removeChild(modal);
            };
            
            closeBtn.addEventListener('click', closeModal);
            
            const listContainer = document.createElement('div');
            listContainer.style.flex = '1';
            listContainer.style.overflow = 'hidden';
            listContainer.style.marginTop = '0px';
            listContainer.style.padding = '10px';
            listContainer.style.boxSizing = 'border-box';
                
            const list = document.createElement('div');
            list.style.display = 'grid';
            list.style.gridTemplateColumns = 'repeat(auto-fill, minmax(100px, 1fr))';
            list.style.gap = '15px';
            list.style.width = '100%';
            list.style.marginTop = '10px';
            list.style.boxSizing = 'border-box';

            listContainer.appendChild(list);
            
            const paginationContainer = document.createElement('div');
            paginationContainer.style.display = 'flex';
            paginationContainer.style.justifyContent = 'flex-end';
            paginationContainer.style.alignItems = 'center';
            paginationContainer.style.gap = '20px';
            paginationContainer.style.marginTop = '-30px';
            paginationContainer.style.padding = '8px';
            
            const prevButton = document.createElement('button');
            prevButton.innerHTML = '&lt;';
            prevButton.className = 'pagination-button';
            
            const nextButton = document.createElement('button');
            nextButton.innerHTML = '&gt;';
            nextButton.className = 'pagination-button';
            
            const pageInfo = document.createElement('span');
            pageInfo.className = 'page-info';
            pageInfo.style.color = 'var(--plug-color1)';
            pageInfo.style.fontSize = '14px';
            pageInfo.style.fontFamily = 'Montserrat, sans-serif';
            pageInfo.style.fontWeight = 'normal';
            pageInfo.style.cursor = 'pointer';
            pageInfo.style.padding = '6px 12px';
            pageInfo.style.margin = '0';
            pageInfo.style.borderRadius = '4px';
            pageInfo.style.transition = 'all 0.3s ease';
            pageInfo.style.display = 'inline-block';
            pageInfo.style.minWidth = '60px';
            pageInfo.style.textAlign = 'center';
            pageInfo.style.lineHeight = '1.2';
            pageInfo.style.boxSizing = 'border-box';
            
            paginationContainer.appendChild(prevButton);
            paginationContainer.appendChild(pageInfo);
            paginationContainer.appendChild(nextButton);
            
            content.appendChild(closeBtn);
            content.appendChild(listContainer);
            content.appendChild(paginationContainer);
            modal.appendChild(content);
            document.body.appendChild(modal);

            if (!this.dataLoaded) {
                list.innerHTML = `
                    <div style="grid-column: 1 / -1; text-align: center; padding: 40px;">
                    <p style="color: #728581; font-size: 16px; margin: 0;">Loading skins...</p>
                    </div>
                `;
                
                await this.loadData();
            }

            let totalPages = 0;
            let pageInput = null;

            const updatePagination = (filteredItems) => {
                totalPages = Math.ceil(filteredItems.length / ITEMS_PER_PAGE);
                
                if (currentPage > totalPages && totalPages > 0) {
                    currentPage = totalPages;
                } else if (totalPages === 0) {
                    currentPage = 1;
                }
                
                pageInfo.textContent = `${currentPage}/${totalPages}`;
                
                prevButton.disabled = currentPage === 1;
                nextButton.disabled = currentPage === totalPages || totalPages === 0;
                
                if (prevButton.disabled) {
                    prevButton.classList.add('disabled');
                } else {
                    prevButton.classList.remove('disabled');
                }
                
                if (nextButton.disabled) {
                    nextButton.classList.add('disabled');
                } else {
                    nextButton.classList.remove('disabled');
                }
            };

            const loadCurrentPage = (filteredItems) => {
                const startIndex = (currentPage - 1) * ITEMS_PER_PAGE;
                const endIndex = startIndex + ITEMS_PER_PAGE;
                const pageItems = filteredItems.slice(startIndex, endIndex);
                
                if (pageItems.length < ITEMS_PER_PAGE && currentPage > 1) {
                    const actualPages = Math.ceil(filteredItems.length / ITEMS_PER_PAGE);
                    if (currentPage > actualPages) {
                        currentPage = Math.max(1, actualPages);
                        const newStartIndex = (currentPage - 1) * ITEMS_PER_PAGE;
                        const newEndIndex = newStartIndex + ITEMS_PER_PAGE;
                        const newPageItems = filteredItems.slice(newStartIndex, newEndIndex);
                        this.loadSkinsIntoModal(list, newPageItems);
                        updatePagination(filteredItems);
                        return;
                    }
                }
                
                this.loadSkinsIntoModal(list, pageItems);
                updatePagination(filteredItems);
            };

            const showPageInput = () => {
                if (pageInput && pageInput.parentNode) {
                    pageInput.remove();
                }

                const pageInfoStyles = window.getComputedStyle(pageInfo);
                
                pageInput = document.createElement('input');
                pageInput.type = 'number';
                pageInput.min = '1';
                pageInput.max = totalPages;
                pageInput.placeholder = `${currentPage}/${totalPages}`;
                pageInput.className = 'search-input';
                
                pageInput.style.width = pageInfoStyles.width;
                pageInput.style.height = pageInfoStyles.height;
                pageInput.style.fontSize = pageInfoStyles.fontSize;
                pageInput.style.fontFamily = pageInfoStyles.fontFamily;
                pageInput.style.fontWeight = pageInfoStyles.fontWeight;
                pageInput.style.padding = pageInfoStyles.padding;
                pageInput.style.margin = pageInfoStyles.margin;
                pageInput.style.lineHeight = pageInfoStyles.lineHeight;
                pageInput.style.textAlign = 'center';
                pageInput.style.border = 'var (--plug-search-input-border)';
                pageInput.style.borderRadius = pageInfoStyles.borderRadius;
                pageInput.style.backgroundColor = '#131312';
                pageInput.style.color = '#728581';
                pageInput.style.boxSizing = 'border-box';
                pageInput.style.display = 'inline-block';
                pageInput.style.verticalAlign = 'middle';

                pageInput.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter') {
                        let pageNum = parseInt(pageInput.value);
                        
                        if (isNaN(pageNum)) {
                            pageNum = currentPage;
                        }
                        
                        if (pageNum > totalPages) {
                            pageNum = totalPages;
                        }
                        
                        if (pageNum < 1) {
                            pageNum = 1;
                        }
                        
                        currentPage = pageNum;
                        const filteredItems = this.getFilteredItems();
                        loadCurrentPage(filteredItems);
                        
                        paginationContainer.replaceChild(pageInfo, pageInput);
                        pageInput = null;
                    } else if (e.key === 'Escape') {
                        paginationContainer.replaceChild(pageInfo, pageInput);
                        pageInput = null;
                    }
                });

                pageInput.addEventListener('blur', () => {
                    if (pageInput && pageInput.parentNode) {
                        paginationContainer.replaceChild(pageInfo, pageInput);
                        pageInput = null;
                    }
                });

                paginationContainer.replaceChild(pageInput, pageInfo);
                pageInput.focus();
                pageInput.select();
            };

            pageInfo.addEventListener('mouseenter', () => {
                pageInfo.style.color = 'var(--plug-color2)';
            });

            pageInfo.addEventListener('mouseleave', () => {
                pageInfo.style.color = 'var(--plug-color1)';
            });

            pageInfo.addEventListener('click', showPageInput);

            prevButton.addEventListener('click', () => {
                if (currentPage > 1) {
                    currentPage--;
                    const filteredItems = this.getFilteredItems();
                    loadCurrentPage(filteredItems);
                }
            });

            nextButton.addEventListener('click', () => {
                const filteredItems = this.getFilteredItems();
                const totalPages = Math.ceil(filteredItems.length / ITEMS_PER_PAGE);
                if (currentPage < totalPages) {
                    currentPage++;
                    loadCurrentPage(filteredItems);
                }
            });

            searchInput.addEventListener('input', () => {
                if (searchTimeout) {
                    clearTimeout(searchTimeout);
                }
                
                searchTimeout = setTimeout(() => {
                    currentSearchQuery = searchInput.value.toLowerCase().trim();
                    currentPage = 1;
                    const filteredItems = this.getFilteredItems();
                    loadCurrentPage(filteredItems);
                }, 500);
            });

            const filteredItems = this.getFilteredItems();
            loadCurrentPage(filteredItems);

            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    closeModal();
                }
            });
            
            const handleEscape = (e) => {
                if (e.key === 'Escape') {
                    closeModal();
                    document.removeEventListener('keydown', handleEscape);
                }
            };
            document.addEventListener('keydown', handleEscape);
            
            modal.addEventListener('DOMNodeRemoved', () => {
                document.removeEventListener('keydown', handleEscape);
            });
        }

        getFilteredItems() {
            this.generatePreviewGroups();
            
            const allItems = [];
            previewGroups.forEach(group => {
                let groupItems = group.items;
                
                if (currentSearchQuery) {
                    groupItems = groupItems.filter(item => {
                        if (!item || !item.name) return false;
                        
                        const searchTerm = currentSearchQuery.toLowerCase().trim();
                        const itemName = item.name.toLowerCase();
                        
                        const nameMatch = itemName.includes(searchTerm);
                        
                        const tftMatch = (searchTerm === 'tft' || searchTerm === 'teamfight tactics') && item.isTFT;
                        const lolMatch = (searchTerm === 'lol' || searchTerm === 'league of legends') && !item.isTFT;
                        const animatedMatch = (searchTerm === 'animated' || searchTerm === 'animation') && item.isAnimated;
                        
                        return nameMatch || tftMatch || lolMatch || animatedMatch;
                    });
                }
                
                allItems.push(...groupItems);
            });

            allItems.sort((a, b) => {
                if (a.isTFT !== b.isTFT) {
                    return a.isTFT ? 1 : -1;
                }
                
                return a.name.localeCompare(b.name);
            });

            return allItems;
        }

        async loadSkinsIntoModal(list, itemsToLoad) {
            try {
                list.innerHTML = '';

                const validItems = [];
                
                const imagePromises = itemsToLoad.map(item => {
                    return new Promise((resolve) => {
                        const img = new Image();
                        const timeout = setTimeout(() => {
                            resolve();
                        }, 5000);
                        
                        img.onload = () => {
                            clearTimeout(timeout);
                            validItems.push({
                                ...item,
                                element: img
                            });
                            resolve();
                        };
                        img.onerror = () => {
                            clearTimeout(timeout);
                            resolve();
                        };
                        img.src = item.tilePath;
                        img.style.width = '100%';
                        img.style.height = '100%';
                        img.style.objectFit = 'cover';
                        img.style.borderRadius = '4px';
                        img.style.boxSizing = 'border-box';
                    });
                });

                await Promise.all(imagePromises);

                if (validItems.length === 0) {
                    list.innerHTML = `
                    <div style="grid-column: 1 / -1; text-align: center; padding: 40px;">
                    <p style="color: #728581; font-size: 16px; margin: 0;">
                        ${this.dataLoaded ? 'No skins found matching your search.' : 'Loading skins...'}
                    </p>
                    </div>
                `;
                    return;
                }

                validItems.forEach(item => {
                    if (!item.element) {
                        return;
                    }

                    const itemElement = document.createElement('div');
                    itemElement.className = 'skin-item';
                    itemElement.style.padding = '10px';
                    itemElement.style.backgroundColor = '#21211F';
                    itemElement.style.borderRadius = '8px';
                    itemElement.style.cursor = 'pointer';
                    itemElement.style.border = '2px solid transparent';
                    itemElement.style.display = 'flex';
                    itemElement.style.flexDirection = 'column';
                    itemElement.style.alignItems = 'center';
                    itemElement.style.gap = '8px';
                    itemElement.style.zIndex = '1';
                    itemElement.style.boxSizing = 'border-box';
                    itemElement.style.position = 'relative';
                    itemElement.style.transition = 'all 0.3s ease';
                    
                    if (item.isAnimated) {
                        const animationBadge = document.createElement('div');
                        animationBadge.textContent = 'ANIMATED';
                        animationBadge.style.position = 'absolute';
                        animationBadge.style.fontFamily = 'var(--font-display)';
                        animationBadge.style.top = '5px';
                        animationBadge.style.left = '5px';
                        animationBadge.style.color = '#010a13';
                        animationBadge.style.padding = '2px 6px';
                        animationBadge.style.borderRadius = '4px';
                        animationBadge.style.fontSize = '10px';
                        animationBadge.style.fontWeight = 'bold';
                        animationBadge.style.zIndex = '2';
                        animationBadge.style.background = 'linear-gradient(45deg, #287861, #6ec8ad)';
                        itemElement.appendChild(animationBadge);
                    }
                    
                    if (item.isTFT) {
                        const tftBadge = document.createElement('div');
                        tftBadge.textContent = 'TFT';
                        tftBadge.style.position = 'absolute';
                        tftBadge.style.fontFamily = 'var(--font-display)';
                        tftBadge.style.top = '5px';
                        tftBadge.style.right = '5px';
                        tftBadge.style.color = '#000';
                        tftBadge.style.padding = '2px 6px';
                        tftBadge.style.borderRadius = '4px';
                        tftBadge.style.fontSize = '10px';
                        tftBadge.style.fontWeight = 'bold';
                        tftBadge.style.zIndex = '2';
                        tftBadge.style.background = 'linear-gradient(45deg, #3f2878, #6e76c8)';
                        itemElement.appendChild(tftBadge);
                    } else {
                        const lolBadge = document.createElement('div');
                        lolBadge.textContent = 'LoL';
                        lolBadge.style.position = 'absolute';
                        lolBadge.style.fontFamily = 'var(--font-display)';
                        lolBadge.style.top = '5px';
                        lolBadge.style.right = '5px';
                        lolBadge.style.color = '#000';
                        lolBadge.style.padding = '2px 6px';
                        lolBadge.style.borderRadius = '4px';
                        lolBadge.style.fontSize = '10px';
                        lolBadge.style.fontWeight = 'bold';
                        lolBadge.style.zIndex = '2';
                        lolBadge.style.background = 'linear-gradient(45deg, #785a28, #c8aa6e)';
                        itemElement.appendChild(lolBadge);
                    }
                    
                    const itemImg = item.element.cloneNode(true);
                    
                    if (item.id === selectedSkinId) {
                        itemImg.classList.add('selected-item-img');
                        itemElement.classList.add('selected-item-border');
                    }
                    
                    itemImg.addEventListener('mouseenter', () => {
                        if (!itemElement.classList.contains('selected-item-border')) {
                            itemImg.style.animation = 'scaleUp 1s ease forwards';
                        }
                    });

                    itemImg.addEventListener('mouseleave', () => {
                        if (!itemElement.classList.contains('selected-item-border')) {
                            itemImg.style.animation = 'scaleDown 0.5s ease forwards';
                        }
                    });

                    itemElement.addEventListener('mouseenter', () => {
                        if (!itemElement.classList.contains('selected-item-border')) {
                            itemElement.style.animation = 'BorderColorUp 1s ease forwards';
                        }
                    });

                    itemElement.addEventListener('mouseleave', () => {
                        if (!itemElement.classList.contains('selected-item-border')) {
                            itemElement.style.animation = 'BorderColorDown 0.5s ease forwards';
                        }
                    });
                    
                    itemElement.addEventListener('click', async () => {
                        document.querySelectorAll('.skin-item').forEach(el => {
                            el.classList.remove('selected-item-border');
                            el.style.borderColor = 'transparent';
                            el.style.animation = '';
                            const img = el.querySelector('img');
                            if (img) {
                                img.classList.remove('selected-item-img');
                            }
                        });
                        
                        itemImg.classList.add('selected-item-img');
                        itemElement.classList.add('selected-item-border');
                        
                        const backgroundUrl = item.isAnimated ? 
                        (item.splashVideoPath || item.splashPath) : 
                        (item.splashPath || item.uncenteredSplashPath || item.tilePath);
                        
                        this.setCustomBackground(backgroundUrl, item.isAnimated, item.id);
                        
                        setTimeout(() => {
                            if (document.body.contains(document.getElementById(CONFIG.MODAL_ID))) {
                                document.body.removeChild(document.getElementById(CONFIG.MODAL_ID));
                            }
                            currentSearchQuery = '';
                            currentPage = 1;
                        }, 500);
                    });
                    
                    itemElement.appendChild(itemImg);
                    list.appendChild(itemElement);
                });

            } catch (error) {
                list.innerHTML = `
                <div style="grid-column: 1 / -1; text-align: center; padding: 40px;">
                    <p style="color: #e63946; font-size: 16px; margin: 0;">Failed to load skins.</p>
                </div>
                `;
            }
        }

        destroy() {
            if (this.customButton && document.body.contains(this.customButton)) {
                document.body.removeChild(this.customButton);
            }
            this.buttonCreated = false;
            this.customButton = null;
            
            if (this.blurObserver) {
                this.blurObserver.disconnect();
            }
            
            if (this.championSelectObserver) {
                this.championSelectObserver.disconnect();
            }
            
            if (searchTimeout) {
                clearTimeout(searchTimeout);
                searchTimeout = null;
            }
        }
    }

    class RoseBackgroundSettings {
		constructor() {
			this.settings = {
				blurAmount: 5
			};
			this.init();
		}

		async init() {
			this.loadSettings();
			this.initializeSettings();
		}

		loadSettings() {
			const savedSettings = DataStore?.get("bgcm-settings");
			if (savedSettings) {
				try {
					const parsed = JSON.parse(savedSettings);
					this.settings.blurAmount = parsed.blurAmount ?? 5;
				} catch (e) {}
			}
		}

		saveSettings() {
			if (window.DataStore) {
				DataStore.set("bgcm-settings", JSON.stringify(this.settings));
			}
			
			if (window.BGCM) {
				window.BGCM.settings.blurAmount = this.settings.blurAmount;
				window.BGCM.updateBlur();
			}
		}

		initializeSettings() {
			const addSettings = () => {
				const settingsContainer = document.querySelector(".bgcm-settings");
				if (!settingsContainer) return;

				const percentage = (this.settings.blurAmount / 100) * 100;
				const buttonPosition = (percentage / 100) * 400;

				settingsContainer.innerHTML = `
					<div class="lol-settings-general-row">
						<div style="display: flex; flex-direction: column; gap: 0px; margin-top: 10px;">
							<div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 0;">
								<div style="display: flex; align-items: center; gap: 10px; flex: 1;">
									<p class="lol-settings-window-size-text" style="margin: 0; font-size: 12px; color: #a09b8c;">
										${LanguageManager.t('BlurAmount')}: ${this.settings.blurAmount}px
									</p>
								</div>
							</div>
							<div style="display: flex; align-items: center; justify-content: space-between; padding: 5px 0 15px 0;">
								<div class="lol-settings-slider-component" style="display: flex; align-items: center; width: 100%;">
									<div class="lol-settings-slider" style="width: 400px; height: 30px; position: relative;">
										<input type="range" min="0" max="100" value="${this.settings.blurAmount}" 
											   style="width: 100%; height: 100%; opacity: 0; cursor: pointer; position: absolute; z-index: 2;">
										<div class="lol-uikit-slider-wrapper horizontal" style="position: relative; height: 30px; width: 100%;">
											<div class="lol-uikit-slider-base" style="height: 30px; width: 100%; position: absolute;">
												<div class="lol-uikit-slider-base-track" style="position: absolute; top: 14px; left: 0; width: calc(100% - 2.5px); height: 2px; background: #1e2328;"></div>
												<div class="lol-uikit-slider-fill" style="width: ${buttonPosition}px; height: 2px; background: linear-gradient(to left, #695625, #463714); position: absolute; top: 13px; border: thin solid #010a13; transition: width 0.1s ease-out, background 0.2s ease;"></div>
												<div class="lol-uikit-slider-button" style="left: ${buttonPosition}px; width: 30px; height: 30px; background: url('/fe/lol-uikit/images/slider-btn.png') no-repeat top left; background-size: 100%; position: absolute; top: 0px; cursor: pointer; transition: left 0.1s ease-out, background-position 0.2s ease;"></div>
											</div>
										</div>
									</div>
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
						if (node.classList?.contains("bgcm-settings")) {
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
				const slider = document.querySelector('.bgcm-settings input[type="range"]');
				const button = document.querySelector('.bgcm-settings .lol-uikit-slider-button');
				const fill = document.querySelector('.bgcm-settings .lol-uikit-slider-fill');
				const valueDisplay = document.querySelector('.bgcm-settings .lol-settings-window-size-text');
				
				if (slider && button && fill && valueDisplay) {
					let isHovered = false;
					let isDragging = false;

					const updateSlider = (value) => {
						const percentage = (value / 100) * 100;
						const buttonPosition = (percentage / 100) * 400;
						
						if (isDragging) {
							button.style.transition = 'none';
							fill.style.transition = 'none';
						} else {
							button.style.transition = 'left 0.1s ease-out, background-position 0.2s ease';
							fill.style.transition = 'width 0.1s ease-out, background 0.2s ease';
						}
						
						button.style.left = `${buttonPosition}px`;
						fill.style.width = `${buttonPosition}px`;
						valueDisplay.textContent = `${LanguageManager.t('BlurAmount')}: ${value}px`;
						this.settings.blurAmount = value;
						this.saveSettings();
					};

					const updateHoverEffects = () => {
						if (isHovered || isDragging) {
							fill.style.background = isDragging 
								? 'linear-gradient(to right, #695625, #463714)'
								: 'linear-gradient(to right, #785a28 0%, #c89b3c 56%, #c8aa6e 100%)';
							button.style.backgroundPosition = isDragging ? '0 -60px' : '0 -30px';
						} else {
							fill.style.background = 'linear-gradient(to left, #695625, #463714)';
							button.style.backgroundPosition = 'top left';
						}
					};

					slider.addEventListener('input', (e) => {
						updateSlider(parseInt(e.target.value));
					});

					const sliderWrapper = document.querySelector('.bgcm-settings .lol-uikit-slider-wrapper');
					
					sliderWrapper.addEventListener('mouseenter', () => {
						isHovered = true;
						updateHoverEffects();
					});

					sliderWrapper.addEventListener('mouseleave', () => {
						isHovered = false;
						updateHoverEffects();
					});

					const handleMouseMove = (e) => {
						if (!isDragging) return;
						
						const sliderRect = slider.getBoundingClientRect();
						const x = Math.max(0, Math.min(sliderRect.width, e.clientX - sliderRect.left));
						const percentage = x / sliderRect.width;
						const value = Math.round(percentage * 100);
						
						updateSlider(value);
						slider.value = value;
					};

					button.addEventListener('mousedown', (e) => {
						isDragging = true;
						updateHoverEffects();
						e.preventDefault();
						
						button.style.transition = 'none';
						fill.style.transition = 'none';
						
						document.addEventListener('mousemove', handleMouseMove);
						document.addEventListener('mouseup', () => {
							isDragging = false;
							updateHoverEffects();
							
							button.style.transition = 'left 0.1s ease-out, background-position 0.2s ease';
							fill.style.transition = 'width 0.1s ease-out, background 0.2s ease';
							
							document.removeEventListener('mousemove', handleMouseMove);
						}, { once: true });
					});

					const track = document.querySelector('.bgcm-settings .lol-uikit-slider-base-track');
					track.addEventListener('click', (e) => {
						const sliderRect = slider.getBoundingClientRect();
						const x = Math.max(0, Math.min(sliderRect.width, e.clientX - sliderRect.left));
						const percentage = x / sliderRect.width;
						const value = Math.round(percentage * 100);
						
						updateSlider(value);
						slider.value = value;
					});
				}
			}, 100);
		}
	}

    window.addEventListener("load", () => {
        settingsUtils(window, baseData);
        new RoseBackgroundSettings();
        window.BGCM = new BGCM();
    });
})();