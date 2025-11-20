import { settingsUtils } from "https://unpkg.com/blank-settings-utils@latest/Settings-Utils.js";

let data = [
  {
    groupName: "RoseWL",
    titleKey: "el_RoseWL",
    titleName: "Rose / WinLose",
    capitalTitleKey: "el_RoseWL_capital",
    capitalTitleName: "Rose / WinLose",
    element: [
      {
        name: "winlose-settings",
        title: "el_winlose_settings",
        titleName: "Settings",
        class: "winlose-settings",
        id: "WinLoseSettings",
      },
    ],
  },
];

(() => {
  const DEFAULT_CONFIG = {
    gamesCount: 1000,
    retryAttempts: 5,
    retryDelay: 1000,
    cacheExpiry: 5 * 60 * 1000,
    selectedQueue: "ranked_solo",
    kdaDisplay: "show",
    winsDisplay: "show",
    lossesDisplay: "show",
    winrateDisplay: "show",
  };

  let CONFIG = { ...DEFAULT_CONFIG };

  const cache = new Map();

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
      DataStore.set('winlose-language', language);
    },

    translations: {
      ru: {
        allQueues: "ВСЕ РЕЖИМЫ",
        rankedSoloDuo: "РАНГОВАЯ ОДИНОЧНАЯ / ПАРНАЯ",
        rankedFlex: "РАНКОВАЯ ГИБКАЯ",
        normalDraft: "РЕЖИМ ВЫБОРА",
        aram: "ARAM",
        swiftplay: "ЛЕГКАЯ ИГРА",
        gamesToAnalyze: "Игр для анализа:",
        queueType: "Тип режима:",
        kdaDisplay: "Отображение KDA:",
        winsDisplay: "Отображение побед:",
        lossesDisplay: "Отображение поражений:",
        winrateDisplay: "Отображение винрейта:",
		LoadingDisp: "Загрузка...",
        show: "Показать",
        hide: "Скрыть"
      },
      zh: {
        allQueues: "所有模式",
        rankedSoloDuo: "单排/双排",
        rankedFlex: "灵活排位",
        normalDraft: "征召模式",
        aram: "ARAM",
        swiftplay: "快速游戏",
        gamesToAnalyze: "分析游戏数:",
        queueType: "队列类型:",
        kdaDisplay: "KDA显示:",
        winsDisplay: "胜利显示:",
        lossesDisplay: "失败显示:",
        winrateDisplay: "胜率显示:",
		LoadingDisp: "Loading...",
        show: "显示",
        hide: "隐藏"
      },
      en: {
        allQueues: "All Queues",
        rankedSoloDuo: "Ranked (Solo/Duo)",
        rankedFlex: "Ranked (Flex)",
        normalDraft: "Normal (Draft Pick)",
        aram: "ARAM",
        swiftplay: "Swiftplay",
        gamesToAnalyze: "Games to analyze:",
        queueType: "Queue Type:",
        kdaDisplay: "KDA Display:",
        winsDisplay: "Wins Display:",
        lossesDisplay: "Losses Display:",
        winrateDisplay: "Winrate Display:",
		LoadingDisp: "Loading...",
        show: "Show",
        hide: "Hide"
      }
    },

    t(key) {
      const lang = this.getLanguage();
      const langTranslations = this.translations[lang] || this.translations.en;
      return langTranslations[key] || this.translations.en[key] || key;
    },

    getQueueTypes() {
      return {
        all: { id: "all", name: this.t('allQueues') },
        ranked_solo: { id: 420, name: this.t('rankedSoloDuo') },
        ranked_flex: { id: 440, name: this.t('rankedFlex') },
        normal_draft: { id: 400, name: this.t('normalDraft') },
        aram: { id: 450, name: this.t('aram') },
        swiftplay: { id: 480, name: this.t('swiftplay') },
      };
    }
  };

  const SettingsStore = {
    async loadSettings() {
      try {
        const settings = DataStore.get("winlose-settings");
        if (settings) {
          const userSettings = JSON.parse(settings);
          CONFIG = {
            ...DEFAULT_CONFIG,
            gamesCount: userSettings.gamesCount ?? DEFAULT_CONFIG.gamesCount,
            selectedQueue: userSettings.selectedQueue ?? DEFAULT_CONFIG.selectedQueue,
            kdaDisplay: userSettings.kdaDisplay ?? DEFAULT_CONFIG.kdaDisplay,
            winsDisplay: userSettings.winsDisplay ?? DEFAULT_CONFIG.winsDisplay,
            lossesDisplay: userSettings.lossesDisplay ?? DEFAULT_CONFIG.lossesDisplay,
            winrateDisplay: userSettings.winrateDisplay ?? DEFAULT_CONFIG.winrateDisplay,
          };
        }
      } catch (error) {}
    },

    async saveSettings() {
      try {
        const settings = {
          gamesCount: CONFIG.gamesCount,
          selectedQueue: CONFIG.selectedQueue,
          kdaDisplay: CONFIG.kdaDisplay,
          winsDisplay: CONFIG.winsDisplay,
          lossesDisplay: CONFIG.lossesDisplay,
          winrateDisplay: CONFIG.winrateDisplay,
        };
        DataStore.set("winlose-settings", JSON.stringify(settings));
      } catch (error) {}
    },
  };

  const utils = {
    debounce(func, wait) {
      let timeout;
      return (...args) => {
        clearTimeout(timeout);
        timeout = setTimeout(() => func(...args), wait);
      };
    },

    async retry(fn, retries = CONFIG.retryAttempts) {
      try {
        return await fn();
      } catch (error) {
        if (retries > 0) {
          await new Promise((resolve) =>
            setTimeout(resolve, CONFIG.retryDelay * (CONFIG.retryAttempts - retries + 1))
          );
          return utils.retry(fn, retries - 1);
        }
        throw error;
      }
    },
  };

  class RoseWinLose {
    constructor() {
      this.observer = null;
      this.currentSummonerId = null;
      this.statsContainer = null;
      this.processedProfiles = new Set();
      this.styleElement = null;
      this.lastCheckTime = 0;
      this.checkThrottle = 1000;
      this.isCleanedUp = false;
      this.init();
    }

    async init() {
      await SettingsStore.loadSettings();
      this.observeProfile();
      this.setupCleanup();
      this.injectStyles();
      this.initializeSettings();

      setTimeout(() => this.checkCurrentProfile(), 100);

      const tick = () => {
        const now = Date.now();
        if (now - this.lastCheckTime >= this.checkThrottle) {
          this.lastCheckTime = now;
          this.checkCurrentProfile();
        }
        if (!this.isCleanedUp) {
          requestAnimationFrame(tick);
        }
      };
      requestAnimationFrame(tick);
    }

    getQueueTypes() {
      return LanguageManager.getQueueTypes();
    }

    initializeSettings() {
      const addSettings = () => {
        const settingsContainer = document.querySelector(".winlose-settings");
        if (!settingsContainer) return;

        const queueTypes = this.getQueueTypes();

        settingsContainer.innerHTML = `
          <div class="lol-settings-general-row">
            <div style="display: flex; flex-direction: column; gap: 15px; margin-top: 10px;">
              <div style="display: flex; align-items: center; gap: 10px;">
                <p class="lol-settings-window-size-text">${LanguageManager.t('gamesToAnalyze')}</p>
                <lol-uikit-flat-input type="number" style="width: 80px;">
                  <input type="number" min="1" value="${CONFIG.gamesCount}" 
                         style="width: 100%; text-align: center;">
                </lol-uikit-flat-input>
              </div>
              <div style="display: flex; align-items: center; gap: 10px;">
                <p class="lol-settings-window-size-text">${LanguageManager.t('queueType')}</p>
                <lol-uikit-framed-dropdown class="lol-settings-general-dropdown" style="width: 200px;" tabindex="0">
                  ${Object.entries(queueTypes)
                    .map(
                      ([key, value]) => `
                    <lol-uikit-dropdown-option slot="lol-uikit-dropdown-option" class="framed-dropdown-type" selected="${
                      key === CONFIG.selectedQueue
                    }" value="${key}">
                      ${value.name}
                      <div class="lol-tooltip-component"></div>
                    </lol-uikit-dropdown-option>
                  `
                    )
                    .join("")}
                </lol-uikit-framed-dropdown>
              </div>
              <div style="display: flex; align-items: center; gap: 10px;">
                <p class="lol-settings-window-size-text">${LanguageManager.t('winsDisplay')}</p>
                <lol-uikit-framed-dropdown class="lol-settings-general-dropdown" style="width: 200px;" tabindex="0">
                  <lol-uikit-dropdown-option slot="lol-uikit-dropdown-option" class="framed-dropdown-type" selected="${
                    CONFIG.winsDisplay === "show"
                  }" value="show">
                    ${LanguageManager.t('show')}
                    <div class="lol-tooltip-component"></div>
                  </lol-uikit-dropdown-option>
                  <lol-uikit-dropdown-option slot="lol-uikit-dropdown-option" class="framed-dropdown-type" selected="${
                    CONFIG.winsDisplay === "hide"
                  }" value="hide">
                    ${LanguageManager.t('hide')}
                    <div class="lol-tooltip-component"></div>
                  </lol-uikit-dropdown-option>
                </lol-uikit-framed-dropdown>
              </div>
              <div style="display: flex; align-items: center; gap: 10px;">
                <p class="lol-settings-window-size-text">${LanguageManager.t('lossesDisplay')}</p>
                <lol-uikit-framed-dropdown class="lol-settings-general-dropdown" style="width: 200px;" tabindex="0">
                  <lol-uikit-dropdown-option slot="lol-uikit-dropdown-option" class="framed-dropdown-type" selected="${
                    CONFIG.lossesDisplay === "show"
                  }" value="show">
                    ${LanguageManager.t('show')}
                    <div class="lol-tooltip-component"></div>
                  </lol-uikit-dropdown-option>
                  <lol-uikit-dropdown-option slot="lol-uikit-dropdown-option" class="framed-dropdown-type" selected="${
                    CONFIG.lossesDisplay === "hide"
                  }" value="hide">
                    ${LanguageManager.t('hide')}
                    <div class="lol-tooltip-component"></div>
                  </lol-uikit-dropdown-option>
                </lol-uikit-framed-dropdown>
              </div>
              <div style="display: flex; align-items: center; gap: 10px;">
                <p class="lol-settings-window-size-text">${LanguageManager.t('winrateDisplay')}</p>
                <lol-uikit-framed-dropdown class="lol-settings-general-dropdown" style="width: 200px;" tabindex="0">
                  <lol-uikit-dropdown-option slot="lol-uikit-dropdown-option" class="framed-dropdown-type" selected="${
                    CONFIG.winrateDisplay === "show"
                  }" value="show">
                    ${LanguageManager.t('show')}
                    <div class="lol-tooltip-component"></div>
                  </lol-uikit-dropdown-option>
                  <lol-uikit-dropdown-option slot="lol-uikit-dropdown-option" class="framed-dropdown-type" selected="${
                    CONFIG.winrateDisplay === "hide"
                  }" value="hide">
                    ${LanguageManager.t('hide')}
                    <div class="lol-tooltip-component"></div>
                  </lol-uikit-dropdown-option>
                </lol-uikit-framed-dropdown>
              </div>
              <div style="display: flex; align-items: center; gap: 10px; padding-bottom: 10px; border-bottom: thin solid #3c3c41;">
                <p class="lol-settings-window-size-text">${LanguageManager.t('kdaDisplay')}</p>
                <lol-uikit-framed-dropdown class="lol-settings-general-dropdown" style="width: 200px;" tabindex="0">
                  <lol-uikit-dropdown-option slot="lol-uikit-dropdown-option" class="framed-dropdown-type" selected="${
                    CONFIG.kdaDisplay === "show"
                  }" value="show">
                    ${LanguageManager.t('show')}
                    <div class="lol-tooltip-component"></div>
                  </lol-uikit-dropdown-option>
                  <lol-uikit-dropdown-option slot="lol-uikit-dropdown-option" class="framed-dropdown-type" selected="${
                    CONFIG.kdaDisplay === "hide"
                  }" value="hide">
                    ${LanguageManager.t('hide')}
                    <div class="lol-tooltip-component"></div>
                  </lol-uikit-dropdown-option>
                </lol-uikit-framed-dropdown>
              </div>
            </div>
          </div>
        `;

        const input = settingsContainer.querySelector("input");
        input.addEventListener("change", this.handleSettingsChange.bind(this));

        const queueDropdown = settingsContainer.querySelectorAll("lol-uikit-framed-dropdown")[0];
        const queueOptions = queueDropdown.querySelectorAll("lol-uikit-dropdown-option");

        const currentQueueOption = Array.from(queueOptions).find(
          (opt) => opt.getAttribute("value") === CONFIG.selectedQueue
        );
        if (currentQueueOption) {
          queueOptions.forEach((opt) => opt.removeAttribute("selected"));
          currentQueueOption.setAttribute("selected", "");
          queueDropdown.setAttribute("selected-value", CONFIG.selectedQueue);
          queueDropdown.setAttribute("selected-item", queueTypes[CONFIG.selectedQueue].name);
        }

        queueOptions.forEach((option) => {
          option.addEventListener("click", () => {
            const value = option.getAttribute("value");
            this.handleQueueChange(value);

            queueOptions.forEach((opt) => opt.removeAttribute("selected"));
            option.setAttribute("selected", "");
            queueDropdown.setAttribute("selected-value", value);
            queueDropdown.setAttribute("selected-item", queueTypes[value].name);
          });
        });

        const winsDropdown = settingsContainer.querySelectorAll("lol-uikit-framed-dropdown")[1];
        const winsOptions = winsDropdown.querySelectorAll("lol-uikit-dropdown-option");

        winsOptions.forEach((option) => {
          option.addEventListener("click", () => {
            const value = option.getAttribute("value");
            CONFIG.winsDisplay = value;
            SettingsStore.saveSettings();

            winsOptions.forEach((opt) => opt.removeAttribute("selected"));
            option.setAttribute("selected", "");
            winsDropdown.setAttribute("selected-value", value);
            winsDropdown.setAttribute("selected-item", value === "show" ? LanguageManager.t('show') : LanguageManager.t('hide'));

            if (this.currentSummonerId) {
              this.updateStats(this.currentSummonerId);
            }
          });
        });

        const lossesDropdown = settingsContainer.querySelectorAll("lol-uikit-framed-dropdown")[2];
        const lossesOptions = lossesDropdown.querySelectorAll("lol-uikit-dropdown-option");

        lossesOptions.forEach((option) => {
          option.addEventListener("click", () => {
            const value = option.getAttribute("value");
            CONFIG.lossesDisplay = value;
            SettingsStore.saveSettings();

            lossesOptions.forEach((opt) => opt.removeAttribute("selected"));
            option.setAttribute("selected", "");
            lossesDropdown.setAttribute("selected-value", value);
            lossesDropdown.setAttribute("selected-item", value === "show" ? LanguageManager.t('show') : LanguageManager.t('hide'));

            if (this.currentSummonerId) {
              this.updateStats(this.currentSummonerId);
            }
          });
        });

        const winrateDropdown = settingsContainer.querySelectorAll("lol-uikit-framed-dropdown")[3];
        const winrateOptions = winrateDropdown.querySelectorAll("lol-uikit-dropdown-option");

        winrateOptions.forEach((option) => {
          option.addEventListener("click", () => {
            const value = option.getAttribute("value");
            CONFIG.winrateDisplay = value;
            SettingsStore.saveSettings();

            winrateOptions.forEach((opt) => opt.removeAttribute("selected"));
            option.setAttribute("selected", "");
            winrateDropdown.setAttribute("selected-value", value);
            winrateDropdown.setAttribute("selected-item", value === "show" ? LanguageManager.t('show') : LanguageManager.t('hide'));

            if (this.currentSummonerId) {
              this.updateStats(this.currentSummonerId);
            }
          });
        });

        const kdaDropdown = settingsContainer.querySelectorAll("lol-uikit-framed-dropdown")[4];
        const kdaOptions = kdaDropdown.querySelectorAll("lol-uikit-dropdown-option");

        kdaOptions.forEach((option) => {
          option.addEventListener("click", () => {
            const value = option.getAttribute("value");
            CONFIG.kdaDisplay = value;
            SettingsStore.saveSettings();

            kdaOptions.forEach((opt) => opt.removeAttribute("selected"));
            option.setAttribute("selected", "");
            kdaDropdown.setAttribute("selected-value", value);
            kdaDropdown.setAttribute("selected-item", value === "show" ? LanguageManager.t('show') : LanguageManager.t('hide'));

            if (this.currentSummonerId) {
              this.updateStats(this.currentSummonerId);
            }
          });
        });
      };

      const observer = new MutationObserver((mutations) => {
        for (const mutation of mutations) {
          for (const node of mutation.addedNodes) {
            if (node.classList?.contains("winlose-settings")) {
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

    handleSettingsChange(e) {
      const newValue = parseInt(e.target.value);
      if (!isNaN(newValue) && newValue > 0) {
        CONFIG.gamesCount = newValue;
        cache.clear();
        SettingsStore.saveSettings();
        if (this.currentSummonerId) {
          this.updateStats(this.currentSummonerId);
        }
      } else {
        e.target.value = CONFIG.gamesCount;
      }
    }

    handleQueueChange(newQueue) {
      const queueTypes = this.getQueueTypes();
      if (queueTypes[newQueue]) {
        CONFIG.selectedQueue = newQueue;
        cache.clear();
        SettingsStore.saveSettings();

        if (this.statsContainer) {
          this.statsContainer.remove();
          this.statsContainer = null;
        }

        if (this.currentSummonerId) {
          this.createStatsContainer();
          this.updateStats(this.currentSummonerId);
        }
      }
    }

    setupCleanup() {
      window.addEventListener("unload", () => {
        this.isCleanedUp = true;
        this.observer?.disconnect();
        this.styleElement?.remove();
        this.processedProfiles.clear();
        cache.clear();
      });
    }

    observeProfile() {
      const debouncedUpdate = utils.debounce(this.updateStats.bind(this), 250);

      this.observer = new MutationObserver(() => {
        const profileElements = document.querySelectorAll("lol-regalia-profile-v2-element");
        const searchedProfile = Array.from(profileElements).find(
          (el) => el.getAttribute("is-searched") === "true"
        );
        const targetProfile = searchedProfile || profileElements[0];

        if (!targetProfile) return;

        const puuid = targetProfile.getAttribute("puuid");
        if (!puuid || puuid === this.currentSummonerId) return;

        this.processedProfiles.clear();
        this.currentSummonerId = puuid;
        this.processedProfiles.add(puuid);
        debouncedUpdate(puuid);
        this.createStatsContainer();
      });

      this.observer.observe(document.body, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ["puuid", "is-searched"],
      });
    }

    async updateStats(puuid) {
      try {
        this.displayLoading();
        const stats = await this.fetchStats(puuid);
        this.displayStats(stats);
      } catch (error) {
        this.displayError();
      }
    }

    displayLoading() {
      if (!this.statsContainer) {
        this.createStatsContainer();
      }
      const content = document.createElement("div");
      content.className = "winloseStats";
      content.innerHTML = `<span class="loading">${LanguageManager.t('LoadingDisp')}</span>`;
      this.statsContainer.replaceChildren(content);
    }

    async fetchStats(puuid) {
      const cacheKey = `stats_${puuid}_${CONFIG.selectedQueue}`;
      const cachedData = cache.get(cacheKey);

      if (cachedData && Date.now() - cachedData.timestamp < CONFIG.cacheExpiry) {
        return cachedData.data;
      }

      const fetchData = async () => {
        const endpoint = `/lol-match-history/v1/products/lol/${puuid}/matches?begIndex=0&endIndex=${CONFIG.gamesCount - 1}`;
        const response = await fetch(endpoint);
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        return response.json();
      };

      const data = await utils.retry(fetchData);
      if (!data.games?.games) {
        return { wins: 0, losses: 0, winRate: 0, kda: 0 };
      }

      const queueTypes = this.getQueueTypes();
      const filteredGames = CONFIG.selectedQueue === "all"
          ? data.games.games
          : data.games.games.filter((game) => game.queueId === queueTypes[CONFIG.selectedQueue].id);

      const limitedGames = filteredGames.slice(0, CONFIG.gamesCount);

      const stats = limitedGames.reduce(
        (acc, game) => {
          const playerTeamId = game.participants[0].teamId;
          const teamWin = game.teams[playerTeamId === 100 ? 0 : 1].win === "Win";
          const player = game.participants[0];

          const kills = player.stats.kills || 0;
          const deaths = player.stats.deaths || 0;
          const assists = player.stats.assists || 0;

          return {
            wins: acc.wins + (teamWin ? 1 : 0),
            losses: acc.losses + (teamWin ? 0 : 1),
            totalKills: acc.totalKills + kills,
            totalDeaths: acc.totalDeaths + deaths,
            totalAssists: acc.totalAssists + assists,
          };
        },
        { wins: 0, losses: 0, totalKills: 0, totalDeaths: 0, totalAssists: 0 }
      );

      const totalGames = stats.wins + stats.losses;
      const kda = stats.totalDeaths === 0
          ? (stats.totalKills + stats.totalAssists).toFixed(1)
          : ((stats.totalKills + stats.totalAssists) / stats.totalDeaths).toFixed(1);

      const result = {
        wins: stats.wins,
        losses: stats.losses,
        winRate: totalGames === 0 ? 0 : ((stats.wins / totalGames) * 100).toFixed(1),
        kda: kda,
      };

      cache.set(cacheKey, { data: result, timestamp: Date.now() });
      return result;
    }

    displayStats({ wins, losses, winRate, kda }) {
      if (!this.statsContainer) {
        this.createStatsContainer();
      }

      const queueTypes = this.getQueueTypes();

      const content = document.createElement("div");
      content.className = "winloseStats";
      
      let statsHTML = `<div class="queue-type">${queueTypes[CONFIG.selectedQueue].name}</div><div class="stats-row">`;
      
      if (CONFIG.winsDisplay === "show") {
        statsHTML += `<span class="wins">${wins}W</span>`;
      }
      if (CONFIG.lossesDisplay === "show") {
        statsHTML += `<span class="losses">${losses}L</span>`;
      }
      if (CONFIG.winrateDisplay === "show") {
        statsHTML += `<span class="winrate">${winRate}%</span>`;
      }
      if (CONFIG.kdaDisplay === "show") {
        statsHTML += `<span class="kda">${kda}|KDA</span>`;
      }
      
      statsHTML += `</div>`;
      content.innerHTML = statsHTML;

      this.statsContainer.replaceChildren(content);
    }

    displayError() {
      if (!this.statsContainer) {
        this.createStatsContainer();
      }
      this.statsContainer.innerHTML = `<div class="winloseStats error"><span>Stats unavailable</span></div>`;
    }

    createStatsContainer() {
      const existingContainer = document.getElementById("winloseContainer");
      if (existingContainer) {
        existingContainer.remove();
      }

      const profileElements = document.querySelectorAll("lol-regalia-profile-v2-element");
      const searchedProfile = Array.from(profileElements).find(
        (el) => el.getAttribute("is-searched") === "true"
      );
      const targetProfile = searchedProfile || profileElements[0];

      if (!targetProfile) return;

      this.statsContainer = document.createElement("div");
      this.statsContainer.id = "winloseContainer";

      const targetElement = targetProfile.querySelector(".style-profile-summoner-status-icons");
      if (targetElement) {
        targetElement.parentNode.insertBefore(this.statsContainer, targetElement.nextSibling);
      }
    }

    checkCurrentProfile() {
      if (this.statsContainer && document.contains(this.statsContainer)) {
        return;
      }

      const profileElements = document.querySelectorAll("lol-regalia-profile-v2-element");
      if (!profileElements.length) return;

      const searchedProfile = Array.from(profileElements).find(
        (el) => el.getAttribute("is-searched") === "true"
      );
      const targetProfile = searchedProfile || profileElements[0];

      if (!targetProfile) return;

      const puuid = targetProfile.getAttribute("puuid");
      if (!puuid) return;

      if (puuid !== this.currentSummonerId || !this.statsContainer || !document.contains(this.statsContainer)) {
        this.currentSummonerId = puuid;
        this.createStatsContainer();
        this.updateStats(puuid);
      }
    }

    injectStyles() {
      if (this.styleElement) return;

      const styles = `
        #winloseContainer {
          display: flex;
          flex-direction: row;
          justify-content: center;
          position: absolute;
          top: 475px;
          width: 100%;
		  scale: 0.8;
        }
        .winloseStats {
			display: flex;
			gap: 5px;
			padding: 8px 15px;
			font-size: 14px;
			font-weight: 600;
			letter-spacing: 0.5px;
			font-family: "LoL Display", "LoL Body", sans-serif;
			align-items: center;
			flex-direction: column;
        }
        .winloseStats .stats-row {
			display: flex;
			gap: 15px;
			flex-direction: row;
			flex-wrap: wrap;
			justify-content: center;
			align-items: center;
			top: 51px !important;
			position: absolute;
			scale: 0.9;
        }
        .winloseStats .queue-type {
			color: var(--plug-color2);
			text-shadow: 0 0 3px rgba(200, 170, 110, 0.3);
			margin-bottom: 2px;
			position: absolute;
        }
        .winloseStats .wins {
          color: #0acbe6;
          text-shadow: 0 0 3px rgba(10, 203, 230, 0.3);
		  animation: soft-text-glow-wins 3s ease-in-out infinite alternate;
        }
        .winloseStats .losses {
          color: #ff4b4b;
          text-shadow: 0 0 3px rgba(255, 75, 75, 0.3);
		  animation: soft-text-glow-lose 3s ease-in-out infinite alternate;
        }
        .winloseStats .winrate {
          color: #f0e6d2;
          text-shadow: 0 0 3px rgba(240, 230, 210, 0.3);
		  animation: soft-text-glow-winrate 3s ease-in-out infinite alternate;
        }
        .winloseStats .kda {
          color: var(--plug-color2);
          text-shadow: 0 0 3px rgba(200, 170, 110, 0.3);
		  animation: soft-text-glow-kda 3s ease-in-out infinite alternate;
        }
        .winloseStats .loading {
          color: var(--plug-color2);
          text-shadow: 0 0 3px rgba(200, 170, 110, 0.3);
          animation: pulse 1.5s infinite;
        }
        @keyframes pulse {
          0% { opacity: 1; }
          50% { opacity: 0.5; }
          100% { opacity: 1; }
        }
        #winlose-settings .lol-settings-general-title {
          color: #f0e6d2;
          font-family: "LoL Display";
          font-size: 14px;
          font-weight: 700;
          letter-spacing: 0.0375em;
          margin-bottom: 12px;
          text-transform: uppercase;
          -webkit-font-smoothing: antialiased;
        }
      `;

      const styleElement = document.createElement("style");
      styleElement.textContent = styles;
      document.head.appendChild(styleElement);
      this.styleElement = styleElement;
    }
  }

  window.addEventListener("load", () => {
    settingsUtils(window, data);
    new RoseWinLose();
  });
})();