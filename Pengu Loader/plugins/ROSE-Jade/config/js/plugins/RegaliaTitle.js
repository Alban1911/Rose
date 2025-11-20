(() => {
  const CONFIG = {
    MODAL_ID: "regalia.title-modal",
    DATASTORE_KEY: "regalia.title-datastore"
  };

  class RegaliaTitle {
    constructor() {
      this.buttonCreated = false;
      this.customButton = null;
      this.allTitles = [];
      this.currentLanguage = 'en';
      this.API_URL = '';
      this.savedTitleName = null;
      this.universalObserver = null;
      this.init();
    }

    getLanguage() {
      const savedLanguage = DataStore.get('Rose-language');
      if (savedLanguage && (savedLanguage === 'ru' || savedLanguage === 'zh' || savedLanguage === 'en')) {
        return savedLanguage;
      }
      return 'en';
    }

    getApiUrl(language) {
      const baseUrl = "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/";
      switch(language) {
        case 'ru': return `${baseUrl}ru_ru/v1/achievementtitles.json`;
        case 'zh': return `${baseUrl}zh_cn/v1/achievementtitles.json`;
        default: return `${baseUrl}default/v1/achievementtitles.json`;
      }
    }

    waitForLanguage() {
      return new Promise((resolve) => {
        const checkLanguage = () => {
          const savedLanguage = DataStore.get('Rose-language');
          if (savedLanguage && (savedLanguage === 'ru' || savedLanguage === 'zh' || savedLanguage === 'en')) {
            resolve(savedLanguage);
          } else {
            setTimeout(checkLanguage, 100);
          }
        };
        checkLanguage();
        setTimeout(() => resolve('en'), 5000);
      });
    }

    async getCurrentTitle() {
      try {
        return await window.DataStore.get(CONFIG.DATASTORE_KEY);
      } catch (error) {
        return null;
      }
    }

    async setCurrentTitle(titleData) {
      try {
        await window.DataStore.set(CONFIG.DATASTORE_KEY, titleData);
      } catch (error) {}
    }

    isPlayerActive() {
      const lobbyContainer = document.querySelector('.v2-banner-component.local-player');
      const profileInfo = document.querySelector('.style-profile-summoner-info-component');
      const titleCustomizer = document.querySelector('.challenges-identity-customizer-tab-titles-component');
      return (lobbyContainer && lobbyContainer.offsetParent !== null) || 
             (profileInfo && profileInfo.offsetParent !== null) ||
             (titleCustomizer && titleCustomizer.offsetParent !== null);
    }

    async applySavedTitle() {
      try {
        const savedTitle = await this.getCurrentTitle();
        if (savedTitle && savedTitle.titleName) {
          this.savedTitleName = savedTitle.titleName;
          this.applyTitleToAllElements(this.savedTitleName);
        }
      } catch (error) {}
    }

    applyTitleToAllElements(titleName) {
      if (!this.isPlayerActive()) return;

      const bannerTitle = document.querySelector('.banner-title');
      if (bannerTitle && bannerTitle.textContent !== titleName) {
        bannerTitle.textContent = titleName;
      }

      const challengeBanner = document.querySelector('.challenge-banner-title-container');
      if (challengeBanner) {
        challengeBanner.innerHTML = '';
        const textNode = document.createTextNode(`\n  ${titleName}\n`);
        challengeBanner.appendChild(textNode);
        
        const tooltipDiv = document.createElement('div');
        tooltipDiv.id = 'ember14034';
        tooltipDiv.className = 'lol-tooltip-component ember-view';
        tooltipDiv.innerHTML = '<!--#ember-component template-path="T:\\cid\\p4\\v3\\Releases_15_21\\LeagueClientContent_Release\\15682\\DevRoot\\Client\\fe\\rcp-fe-ember-libs\\src\\lib\\ember-uikit\\addon\\templates\\components\\uikit-tooltip.hbs" style-path="null" js-path="T:\\cid\\p4\\v3\\Releases_15_21\\LeagueClientContent_Release\\15682\\DevRoot\\Client\\fe\\rcp-fe-ember-libs\\src\\lib\\ember-uikit\\addon\\components\\uikit-tooltip.js" -->';
        challengeBanner.appendChild(tooltipDiv);
      }
    }

    startUniversalObserver() {
      if (this.universalObserver) {
        this.universalObserver.disconnect();
      }

      this.universalObserver = new MutationObserver((mutations) => {
        if (!this.isPlayerActive()) return;
        
        let titleChanged = false;
        
        for (const mutation of mutations) {
          for (const node of mutation.addedNodes) {
            if (node.nodeType === Node.ELEMENT_NODE) {
              if (node.matches && (
                node.matches('.banner-title') ||
                node.matches('.challenge-banner-title-container')
              )) {
                titleChanged = true;
                break;
              }
              if (node.querySelector && (
                node.querySelector('.banner-title') ||
                node.querySelector('.challenge-banner-title-container')
              )) {
                titleChanged = true;
                break;
              }
            }
          }
          
          if (mutation.type === 'characterData') {
            const parent = mutation.target.parentElement;
            if (parent && (
              parent.classList.contains('banner-title') ||
              parent.classList.contains('challenge-banner-title-container')
            )) {
              titleChanged = true;
            }
          }
        }
        
        if (titleChanged && this.savedTitleName) {
          this.applyTitleToAllElements(this.savedTitleName);
        }
      });

      this.universalObserver.observe(document.body, {
        childList: true,
        subtree: true,
        characterData: true
      });
    }

    applyTitle(titleName) {
      this.savedTitleName = titleName;
      this.applyTitleToAllElements(titleName);
    }

    init() {
      this.startButtonObserver();
      this.startUniversalObserver();
      this.applySavedTitle();
      setInterval(() => {
        if (this.savedTitleName && this.isPlayerActive()) {
          this.applyTitleToAllElements(this.savedTitleName);
        }
      }, 3000);
    }

    startButtonObserver() {
      const checkInterval = setInterval(() => {
        const isTitleCustomizerVisible = this.isTitleCustomizerVisible();
        const isPlayerVisible = this.isPlayerActive();
        
        if (isPlayerVisible && this.savedTitleName) {
          this.applyTitleToAllElements(this.savedTitleName);
        }
        
        if (isTitleCustomizerVisible) {
          if (!this.buttonCreated) {
            this.customButton = this.createCustomButton();
            this.customButton.addEventListener('click', () => this.showTitleModal());
            this.buttonCreated = true;
          }
        } else {
          if (this.buttonCreated && this.customButton) {
            document.body.removeChild(this.customButton);
            this.customButton = null;
            this.buttonCreated = false;
          }
        }
      }, 250);
    }

    isTitleCustomizerVisible() {
      const targetElement = document.querySelector('.challenges-identity-customizer-tab-titles-component');
      return targetElement && targetElement.offsetParent !== null;
    }

    createCustomButton() {
      const button = document.createElement('button');
      const img = document.createElement('img');
      img.src = '/fe/lol-uikit/images/icon_settings.png';
      img.style.width = '15px';
      img.style.height = '15px';
      img.style.display = 'block';
      button.appendChild(img);
      button.style.position = 'fixed';
      button.style.bottom = '514px';
      button.style.right = '620px';
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

    async showTitleModal() {
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

      const searchContainer = document.createElement('div');
      searchContainer.style.position = 'absolute';
      searchContainer.style.top = '15px';
      searchContainer.style.left = '15px';
      searchContainer.style.zIndex = '10001';

      const searchInput = document.createElement('input');
      searchInput.type = 'text';
      searchInput.placeholder = 'Search...';
      searchInput.className = 'search-input';
      searchInput.addEventListener('input', (e) => {
        this.filterTitles(e.target.value);
      });

      searchContainer.appendChild(searchInput);
      content.appendChild(searchContainer);

      const reminder = document.createElement('div');
      reminder.style.position = 'absolute';
      reminder.style.top = '15px';
      reminder.style.right = '50px';
      reminder.style.color = 'var(--plug-color1)';
      reminder.style.fontSize = '9px';
      reminder.style.fontWeight = 'bold';
      reminder.style.fontFamily = 'Montserrat, sans-serif';
      reminder.style.textAlign = 'right';
      reminder.style.padding = '10px';
      reminder.style.marginBottom = '0px';
      reminder.textContent = 'REMEMBER: ONLY YOU CAN SEE CHANGES';
      reminder.className = 'soft-text-glow';
      content.appendChild(reminder);
      
      const closeBtn = document.createElement('button');
      closeBtn.style.position = 'absolute';
      closeBtn.style.top = '20px';
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
      
      closeBtn.addEventListener('click', () => {
        document.body.removeChild(modal);
      });
      
      const listContainer = document.createElement('div');
      listContainer.style.flex = '1';
      listContainer.style.overflowY = 'auto';
      listContainer.style.overflowX = 'hidden';
      listContainer.style.marginTop = '30px';
      listContainer.style.paddingRight = '10px';
      listContainer.className = 'rose-scrollable';
      
      const list = document.createElement('div');
      list.style.display = 'grid';
      list.style.gridTemplateColumns = 'repeat(auto-fill, minmax(140px, 1fr))';
	  list.style.marginTop = '10px';
      list.style.gap = '10px';
      list.style.width = '100%';
      list.style.boxSizing = 'border-box';
      list.id = 'titles-grid';

      listContainer.appendChild(list);
      content.appendChild(closeBtn);
      content.appendChild(listContainer);
      modal.appendChild(content);
      document.body.appendChild(modal);

      this.loadTitlesIntoModal(list, modal);

      modal.addEventListener('click', (e) => {
        if (e.target === modal) {
          document.body.removeChild(modal);
        }
      });
      
      const handleEscape = (e) => {
        if (e.key === 'Escape') {
          document.body.removeChild(modal);
          document.removeEventListener('keydown', handleEscape);
        }
      };
      
      document.addEventListener('keydown', handleEscape);
      
      modal.addEventListener('DOMNodeRemoved', () => {
        document.removeEventListener('keydown', handleEscape);
      });

      setTimeout(() => searchInput.focus(), 100);
    }

    async loadTitlesIntoModal(list, modal) {
      try {
        const language = await this.waitForLanguage();
        this.currentLanguage = language;
        this.API_URL = this.getApiUrl(language);

        const response = await fetch(this.API_URL);
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        const titlesData = await response.json();
        
        list.innerHTML = '';
        this.allTitles = [];
        
        const extractAllTitles = (data) => {
          if (!data) return;
          if (typeof data === 'object') {
            for (let key in data) {
              if (data.hasOwnProperty(key)) {
                const item = data[key];
                if (item && typeof item === 'object' && item.itemId && item.titleName) {
                  this.allTitles.push({
                    itemId: item.itemId,
                    titleName: item.titleName,
                    name: item.name || item.titleName
                  });
                }
                extractAllTitles(item);
              }
            }
          }
          if (Array.isArray(data)) {
            data.forEach(item => extractAllTitles(item));
          }
        };

        extractAllTitles(titlesData);
        this.allTitles.sort((a, b) => b.itemId - a.itemId);
        const currentTitle = await this.getCurrentTitle();
        this.titlesList = list;
        this.renderTitles(this.allTitles, currentTitle);

      } catch (error) {
        list.innerHTML = `
          <div style="grid-column: 1 / -1; text-align: center; padding: 40px;">
            <p style="color: #e63946; font-size: 16px; margin: 0; font-family: Montserrat, sans-serif;">
              Failed to load titles for ${this.currentLanguage.toUpperCase()} language.
            </p>
          </div>
        `;
      }
    }

    renderTitles(titles, currentTitle) {
      if (!this.titlesList) return;
      this.titlesList.innerHTML = '';

      titles.forEach(title => {
        const item = document.createElement('div');
        item.style.padding = '15px';
        item.style.backgroundColor = '#21211F';
        item.style.borderRadius = '8px';
        item.style.cursor = 'pointer';
        item.style.border = '2px solid transparent';
        item.style.display = 'flex';
        item.style.flexDirection = 'column';
        item.style.alignItems = 'center';
        item.style.gap = '8px';
        item.style.zIndex = '1';
        item.style.boxSizing = 'border-box';
        item.style.textAlign = 'center';
        item.style.minHeight = '50px';
        item.style.justifyContent = 'center';
        item.style.transition = 'all 0.3s ease';
        
        const isCurrentTitle = currentTitle && currentTitle.itemId === title.itemId;
        
        const titleText = document.createElement('span');
        titleText.textContent = title.titleName;
        titleText.style.color = '#ffffff';
        titleText.style.fontFamily = 'Montserrat, sans-serif';
        titleText.style.fontSize = '12px';
        titleText.style.fontWeight = '500';
        titleText.style.textAlign = 'center';
        titleText.style.wordBreak = 'break-word';
        titleText.style.lineHeight = '1.2';
        item.appendChild(titleText);
        
        titleText.addEventListener('mouseenter', () => {
          if (!isCurrentTitle) {
            titleText.style.animation = 'scaleUp 1s ease forwards';
          }
        });
		item.addEventListener('mouseenter', () => {
          if (!isCurrentTitle) {
            item.style.animation = 'BorderColorUp 1s ease forwards';
          }
        });
        
        titleText.addEventListener('mouseleave', () => {
          if (!isCurrentTitle) {
            titleText.style.animation = 'scaleDown 0.5s ease forwards';
          }
        });
		item.addEventListener('mouseleave', () => {
          if (!isCurrentTitle) {
            item.style.animation = 'BorderColorDown 0.5s ease forwards';
          }
        });
        
		if (isCurrentTitle) {
			titleText.classList.add('selected-title');
			item.classList.add('selected-item-border');
		}
		
        item.addEventListener('click', async () => {
          await this.setCurrentTitle(title);
          this.applyTitle(title.titleName);
          document.body.removeChild(document.getElementById(CONFIG.MODAL_ID));
        });
        
        this.titlesList.appendChild(item);
      });

      if (titles.length === 0) {
        this.titlesList.innerHTML = '<div style="grid-column: 1 / -1; text-align: center; padding: 40px;"><p style="color: #e63946; font-size: 16px; margin: 0; font-family: Montserrat, sans-serif;">No titles found matching your search.</p></div>';
      }
    }

    filterTitles(searchTerm) {
      if (!searchTerm) {
        this.renderTitles(this.allTitles);
        return;
      }
      const filteredTitles = this.allTitles.filter(title => 
        title.titleName.toLowerCase().includes(searchTerm.toLowerCase())
      );
      this.renderTitles(filteredTitles);
    }
  }

  window.addEventListener("load", () => {
    window.RegaliaTitle = new RegaliaTitle();
  });
})();