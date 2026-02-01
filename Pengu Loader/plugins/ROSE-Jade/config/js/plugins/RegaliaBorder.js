(() => {
  const CONFIG = {
    API_URL: "https://plugins/ROSE-Jade/API/border.json",
    MODAL_ID: "regalia.border-modal",
    DATASTORE_KEY: "regalia.border-datastore"
  };

  function StopTimeProp(object, properties) {
    if (!object) return;
    for (const type in object) {
      if (
        (properties && properties.length && properties.includes(type)) ||
        !properties ||
        !properties.length
      ) {
        let value = object[type];
        try {
          Object.defineProperty(object, type, {
            configurable: false,
            get: () => value,
            set: (v) => v,
          });
        } catch {}
      }
    }
  }

  class RegaliaBorder {
    constructor() {
      this.buttonCreated = false;
      this.customButton = null;
      this.borderList = [];
      this.currentTab = 'classic';
      this.currentBorderPath = null;
      this.borderObservers = new Map();
      this._frozen = false;
      this._applying = false;
      this.originalDivisions = new WeakMap();
      this._rankSubtitleOriginalText = new WeakMap();
      this.currentBorderData = null;
      this.checkInterval = null;
      this.startObserver();
    }

    _tierLabelFromTierUpper(tierUpper) {
      const names = {
        UNRANKED: 'Unranked',
        IRON: 'Iron',
        BRONZE: 'Bronze',
        SILVER: 'Silver',
        GOLD: 'Gold',
        PLATINUM: 'Platinum',
        EMERALD: 'Emerald',
        DIAMOND: 'Diamond',
        MASTER: 'Master',
        GRANDMASTER: 'Grandmaster',
        CHALLENGER: 'Challenger',
      };

      const t = (tierUpper || '').toUpperCase();
      const base = names[t] || names.UNRANKED;
      const highTiers = ['MASTER', 'GRANDMASTER', 'CHALLENGER'];
      return highTiers.includes(t) ? base : `${base} I`;
    }

    _applyRankedProfileSubtitle(selectedBorder) {
      // ONLY for the ranked profile emblem component the user pasted.
      try {
        const rankedComponent = document.querySelector('.style-profile-ranked-component');
        if (!rankedComponent) return;

        const subtitle = rankedComponent.querySelector(
          '.style-profile-emblem-subheader-ranked .style-profile-emblem-header-subtitle, ' +
          '.style-profile-emblem-header-subtitle'
        );
        if (!subtitle) return;

        // Prefer the chosen custom border tier (what you clicked in ROSE-Jade),
        // fall back to the real emblem tier if missing.
        const tierUpper =
          (selectedBorder && selectedBorder.rankedTier ? String(selectedBorder.rankedTier).toUpperCase() : '') ||
          rankedComponent.querySelector('lol-regalia-emblem-element[ranked-tier]')?.getAttribute?.('ranked-tier');
        if (!tierUpper) return;

        if (!this._rankSubtitleOriginalText.has(subtitle)) {
          this._rankSubtitleOriginalText.set(subtitle, subtitle.textContent);
        }

        const label = this._tierLabelFromTierUpper(tierUpper);
        if (subtitle.textContent !== label) subtitle.textContent = label;
      } catch {}
    }

    _restoreRankedProfileSubtitle() {
      try {
        const rankedComponent = document.querySelector('.style-profile-ranked-component');
        if (!rankedComponent) return;

        const subtitle = rankedComponent.querySelector(
          '.style-profile-emblem-subheader-ranked .style-profile-emblem-header-subtitle, ' +
          '.style-profile-emblem-header-subtitle'
        );
        if (!subtitle) return;

        if (!this._rankSubtitleOriginalText.has(subtitle)) return;
        const original = this._rankSubtitleOriginalText.get(subtitle);
        this._rankSubtitleOriginalText.delete(subtitle);

        if (subtitle.textContent !== original) subtitle.textContent = original || '';
      } catch {}
    }

    isFullPageModalVisible() {
      const fullPageModal = document.querySelector('lol-uikit-full-page-modal');
      return fullPageModal && fullPageModal.offsetParent !== null;
    }

    freeze() {
      this.revertBorder();
      this._frozen = true;
    }

    unfreeze() {
      this._frozen = false;
      this.applyCustomBorder();
    }

    saveOriginalDivision(crestElement) {
      if (crestElement.hasAttribute('ranked-division') && !this.originalDivisions.has(crestElement)) {
        this.originalDivisions.set(crestElement, crestElement.getAttribute('ranked-division'));
      }
    }

    restoreOriginalDivision(crestElement) {
      if (this.originalDivisions.has(crestElement)) {
        const originalValue = this.originalDivisions.get(crestElement);
        if (originalValue) {
          crestElement.setAttribute('ranked-division', originalValue);
        } else {
          crestElement.removeAttribute('ranked-division');
        }
        this.originalDivisions.delete(crestElement);
      }
    }

    setCurrentBorderCSS(borderData) {
      this.currentBorderData = borderData;
      
      if (borderData && borderData.crestType === 'ranked' && borderData.previewPath) {
        document.documentElement.style.setProperty('--current-border', `url('${borderData.previewPath}')`);
        this.applyBorderStylesToEmblems();
      } else {
        document.documentElement.style.removeProperty('--current-border');
        this.removeBorderStylesFromEmblems();
      }
    }

    applyBorderStylesToEmblems() {
      if (this.isFullPageModalVisible()) return;

      const styleId = 'regalia-border-emblem-styles';
      
      this.removeBorderStylesFromEmblems();

      const style = document.createElement('style');
      style.id = styleId;
      style.textContent = `
        :host .regalia-emblem-container .regalia-emblem[ranked-tier="unranked"],
        :host .regalia-emblem-container .regalia-emblem[ranked-tier="iron"],
        :host .regalia-emblem-container .regalia-emblem[ranked-tier="bronze"],
        :host .regalia-emblem-container .regalia-emblem[ranked-tier="silver"],
        :host .regalia-emblem-container .regalia-emblem[ranked-tier="gold"],
        :host .regalia-emblem-container .regalia-emblem[ranked-tier="platinum"],
        :host .regalia-emblem-container .regalia-emblem[ranked-tier="emerald"],
        :host .regalia-emblem-container .regalia-emblem[ranked-tier="diamond"],
        :host .regalia-emblem-container .regalia-emblem[ranked-tier="master"],
        :host .regalia-emblem-container .regalia-emblem[ranked-tier="grandmaster"],
        :host .regalia-emblem-container .regalia-emblem[ranked-tier="challenger"] {
          background-image: var(--current-border);
        }
      `;
      document.head.appendChild(style);

      this.applyStylesToExistingEmblems();
    }

    applyStylesToExistingEmblems() {
      if (this.isFullPageModalVisible()) return;

      const emblemElements = document.querySelectorAll('lol-regalia-emblem-element');
      
      emblemElements.forEach(emblemElement => {
        if (emblemElement.shadowRoot) {
          const styleId = 'current-border-emblem-style';
          let existingStyle = emblemElement.shadowRoot.getElementById(styleId);
          
          if (this.currentBorderData && this.currentBorderData.crestType === 'ranked') {
            if (!existingStyle) {
              existingStyle = document.createElement('style');
              existingStyle.id = styleId;
              emblemElement.shadowRoot.appendChild(existingStyle);
            }
            
            existingStyle.textContent = `
              :host .regalia-emblem-container .regalia-emblem[ranked-tier="unranked"],
              :host .regalia-emblem-container .regalia-emblem[ranked-tier="iron"],
              :host .regalia-emblem-container .regalia-emblem[ranked-tier="bronze"],
              :host .regalia-emblem-container .regalia-emblem[ranked-tier="silver"],
              :host .regalia-emblem-container .regalia-emblem[ranked-tier="gold"],
              :host .regalia-emblem-container .regalia-emblem[ranked-tier="platinum"],
              :host .regalia-emblem-container .regalia-emblem[ranked-tier="emerald"],
              :host .regalia-emblem-container .regalia-emblem[ranked-tier="diamond"],
              :host .regalia-emblem-container .regalia-emblem[ranked-tier="master"],
              :host .regalia-emblem-container .regalia-emblem[ranked-tier="grandmaster"],
              :host .regalia-emblem-container .regalia-emblem[ranked-tier="challenger"] {
                background-image: var(--current-border);
              }
            `;
          } else if (existingStyle) {
            existingStyle.remove();
          }
        }
      });
    }

    removeBorderStylesFromEmblems() {
      const styleId = 'regalia-border-emblem-styles';
      const existingStyle = document.getElementById(styleId);
      if (existingStyle) {
        existingStyle.remove();
      }

      const emblemElements = document.querySelectorAll('lol-regalia-emblem-element');
      emblemElements.forEach(emblemElement => {
        if (emblemElement.shadowRoot) {
          const shadowStyle = emblemElement.shadowRoot.getElementById('current-border-emblem-style');
          if (shadowStyle) {
            shadowStyle.remove();
          }
        }
      });
    }

    findAllCrestElements() {
      const foundElements = [];
      
      const playerLocations = [
        '.style-profile-summoner-info-component',
        '.lobby-player.local-player',
        '.v2-banner-component.local-player',
        '.local-player [prestige-crest-id]',
        '.local-player [crest-type]',
        '.player-card.local-player',
        '.summoner-profile.local-player'
      ];
      
      const searchInLocation = (locationSelector) => {
        const containers = document.querySelectorAll(locationSelector);
        containers.forEach(container => {
          const searchInElement = (element) => {
            const selectors = [
              'lol-regalia-crest-v2-element',
              'lol-regalia-emblem-element',
              '.regalia-emblem',
              '[prestige-crest-id]',
              '[crest-type]',
              '[ranked-tier]'
            ];
            
            selectors.forEach(selector => {
              const elements = element.querySelectorAll(selector);
              elements.forEach(el => {
                if (!foundElements.includes(el)) {
                  foundElements.push(el);
                }
              });
            });
            
            if (element.shadowRoot) {
              searchInElement(element.shadowRoot);
            }
            
            element.querySelectorAll('*').forEach(child => {
              if (child.shadowRoot) {
                searchInElement(child.shadowRoot);
              }
            });
          };
          
          searchInElement(container);
        });
      };
      
      playerLocations.forEach(location => {
        searchInLocation(location);
      });
      
      if (foundElements.length === 0) {
        searchInLocation('.local-player');
      }
      
      return foundElements;
    }

    startObserver() {
      this.checkInterval = setInterval(() => {
        if (this._frozen) return;
        
        const isPlayerActive = this.isPlayerActive();
        const isBorderVisible = this.isBorderContainerVisible();
        
        if (this.isFullPageModalVisible()) {
          if (this.buttonCreated && this.customButton) {
            document.body.removeChild(this.customButton);
            this.customButton = null;
            this.buttonCreated = false;
          }
          return;
        }
        
        if (isPlayerActive) {
          this.applyCustomBorder();
          
          if (isBorderVisible) {
            if (!this.buttonCreated) {
              this.customButton = this.createRegaliaBorder();
              this.customButton.addEventListener('click', () => this.showBorderModal());
              this.buttonCreated = true;
            }
          } else {
            if (this.buttonCreated && this.customButton) {
              document.body.removeChild(this.customButton);
              this.customButton = null;
              this.buttonCreated = false;
            }
          }
        } else {
          if (this.buttonCreated && this.customButton) {
            document.body.removeChild(this.customButton);
            this.customButton = null;
            this.buttonCreated = false;
          }
        }
      }, 850);
    }

    stop() {
      if (this.checkInterval) {
        clearInterval(this.checkInterval);
        this.checkInterval = null;
      }
    }

    isBorderContainerVisible() {
      const borderContainer = document.querySelector('.identity-customizer-tab-borders-component');
      return borderContainer && borderContainer.offsetParent !== null;
    }

    isPlayerActive() {
      const lobbyContainer = document.querySelector('.v2-banner-component.local-player');
      const profileInfo = document.querySelector('.style-profile-summoner-info-component');
      
      return (lobbyContainer && lobbyContainer.offsetParent !== null) || 
             (profileInfo && profileInfo.offsetParent !== null);
    }

    createRegaliaBorder() {
      const button = document.createElement('button');
      
      const img = document.createElement('img');
      img.src = '/fe/lol-uikit/images/icon_settings.png';
      img.style.width = '15px';
      img.style.height = '15px';
      img.style.display = 'block';
      
      button.appendChild(img);
      button.style.position = 'fixed';
      button.style.bottom = '515px';
      button.style.right = '200px';
      button.style.zIndex = '9999';
      button.style.padding = '5px';
      button.style.backgroundColor = '#1e292c';
      button.style.border = '2px solid var(--plug-jsbutton-color2)';
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

    async loadBordersFromAPI() {
      try {
        const response = await fetch(CONFIG.API_URL);
        const bordersData = await response.json();
        
		const sortedBordersData = bordersData.sort((a, b) => {
		  return parseInt(a.id) - parseInt(b.id);
		});
		
        this.borderList = sortedBordersData.map(border => {
          const uniqueId = border["ranked-tier"] ? 
            `${border.id}-${border["ranked-tier"]}` : 
            border.id;
          
          return {
            id: border.id,
            uniqueId: uniqueId,
            crestType: border["crest-type"],
            rankedTier: border["ranked-tier"],
            previewPath: this.getPreviewPath(border.assetPath)
          };
        });
        
      } catch (error) {}
    }
      
    getPreviewPath(assetPath) {
      return assetPath;
    }

    async applyCustomBorder() {
      if (this._frozen || this._applying || this.isFullPageModalVisible()) return;
      this._applying = true;
      
      try {
        this.revertBorder();
        
        const selectedBorder = await this.getCurrentBorder();
        if (!selectedBorder) {
          return;
        }

        this.currentBorderPath = selectedBorder;

        const crestElements = this.findAllCrestElements();
        if (crestElements.length > 0) {
          crestElements.forEach((crestElement) => {
            this.applyBorderToElement(crestElement, selectedBorder);
            StopTimeProp(crestElement, ['prestige-crest-id', 'crest-type', 'ranked-tier', 'ranked-division']);
          });
        }
        
        const customizerElement = document.querySelector('lol-regalia-identity-customizer-element');
        if (customizerElement && customizerElement.shadowRoot) {
          const customizerCrest = customizerElement.shadowRoot.querySelector('lol-regalia-crest-v2-element.regalia-identity-customizer-crest-element');
          if (customizerCrest) {
            this.applyBorderToElement(customizerCrest, selectedBorder);
            StopTimeProp(customizerCrest, ['prestige-crest-id', 'crest-type', 'ranked-tier', 'ranked-division']);
          }
        }
        
        this.setCurrentBorderCSS(selectedBorder);

        // Re-add: update only the ranked profile subtitle to match the current crest tier.
        // This is scoped to `.style-profile-ranked-component` so honor/etc are untouched.
        if (selectedBorder.crestType === 'ranked') {
          this._applyRankedProfileSubtitle(selectedBorder);
        } else {
          this._restoreRankedProfileSubtitle();
        }
        
      } catch (error) {
      } finally {
        this._applying = false;
      }
    }

    applyBorderToElement(crestElement, borderData) {
      try {
        this.saveOriginalDivision(crestElement);

        if (borderData.crestType === 'prestige') {
          crestElement.setAttribute('prestige-crest-id', borderData.id);
          crestElement.setAttribute('crest-type', 'prestige');
          // IMPORTANT: Do not clear `ranked-tier` for prestige borders.
          // Clearing it makes the UI treat the player as "unranked" and hides the rank.
          this.restoreOriginalDivision(crestElement);
        } else if (borderData.crestType === 'ranked') {
          crestElement.setAttribute('prestige-crest-id', borderData.id);
          crestElement.setAttribute('crest-type', 'ranked');
          if (borderData.rankedTier) {
            crestElement.setAttribute('ranked-tier', borderData.rankedTier.toUpperCase());
            
            const highTiers = ['MASTER', 'GRANDMASTER', 'CHALLENGER'];
            if (highTiers.includes(borderData.rankedTier.toUpperCase())) {
              crestElement.setAttribute('ranked-division', ' ');
            } else {
              this.restoreOriginalDivision(crestElement);
            }
          }
        }

      } catch (error) {}
    }

    revertBorder() {
      try {       
        // Restore the ranked profile subtitle if we changed it.
        this._restoreRankedProfileSubtitle();

        if (this.borderObservers) {
          this.borderObservers.forEach((observer, crestElement) => {
            try {
              observer.disconnect();
              delete crestElement._borderReplaced;
              this.restoreOriginalDivision(crestElement);
            } catch (e) {}
          });
          this.borderObservers.clear();
        }
        
        this.currentBorderPath = null;
        this.currentBorderData = null;
        this.setCurrentBorderCSS(null);
        
      } catch (error) {}
    }

    async getCurrentBorder() {
      try {
        return await window.DataStore?.get(CONFIG.DATASTORE_KEY);
      } catch (error) {
        return null;
      }
    }

    async setCurrentBorder(borderData) {
      try {
        await window.DataStore?.set(CONFIG.DATASTORE_KEY, borderData);
        this.setCurrentBorderCSS(borderData);
      } catch (error) {}
    }

    async showBorderModal() {
      await this.loadBordersFromAPI();
      
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
      
      const signature = document.createElement('div');
      signature.style.position = 'absolute';
      signature.style.bottom = '10px';
      signature.style.right = '10px';
      signature.style.backgroundColor = 'transparent';
      signature.style.color = 'var(--plug-scrollable-color)';
      signature.style.fontSize = '9px';
      signature.style.fontWeight = 'bold';
      signature.style.fontFamily = 'var(--font-JADE)';
      signature.style.textAlign = 'right';
      signature.style.padding = '5px';
      signature.style.zIndex = '10001';
      signature.style.pointerEvents = 'none';
      signature.textContent = 'by @kyewyve';
      modal.appendChild(signature);

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
      
      const logoUrl = 'https://plugins/ROSE-Jade/assets/logo.png';
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
      reminder.style.fontFamily = 'var(--font-JADE)';
      reminder.style.textAlign = 'right';
      reminder.style.padding = '10px';
      reminder.style.marginRight = '30px';
      reminder.style.marginBottom = '0px';
      reminder.textContent = 'REMEMBER: ONLY YOU CAN SEE CHANGES';
      reminder.className = 'soft-text-glow';

      content.appendChild(reminder);
      
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
      
      closeBtn.addEventListener('click', () => {
        document.body.removeChild(modal);
      });
      
      const tabsContainer = document.createElement('div');
      tabsContainer.style.display = 'flex';
      tabsContainer.style.gap = '0px';
      tabsContainer.style.marginBottom = '20px';
      tabsContainer.style.padding = '0px';
      tabsContainer.style.width = '100%';
      tabsContainer.style.border = '1px solid #2a2a2a';
      tabsContainer.style.borderRadius = '6px';
      tabsContainer.style.border = 'none';
      tabsContainer.style.overflow = 'hidden';
      tabsContainer.style.position = 'relative';

      const activeTabBg = document.createElement('div');
      activeTabBg.style.position = 'absolute';
      activeTabBg.style.top = '0';
      activeTabBg.style.left = this.currentTab === 'classic' ? '0' : '50%';
      activeTabBg.style.width = '50%';
      activeTabBg.style.height = '100%';
      activeTabBg.style.backgroundColor = 'var(--plug-color-buttonHover)';
      activeTabBg.style.transition = 'all 0.65s cubic-bezier(.785, .135, .15, .86)';
      activeTabBg.style.zIndex = '1';

      const classicTab = document.createElement('button');
      classicTab.textContent = 'Classic';
      classicTab.style.padding = '12px 0';
      classicTab.style.backgroundColor = 'transparent';
      classicTab.style.color = this.currentTab === 'classic' ? 'var(--plug-color1)' : 'var(--plug-color-buttonHover)';
      classicTab.style.border = 'none';
      classicTab.style.borderRadius = '0px';
      classicTab.style.cursor = 'pointer';
      classicTab.style.fontFamily = 'var(--font-display)';
      classicTab.style.fontWeight = 'bold';
      classicTab.style.flex = '1';
      classicTab.style.width = '50%';
      classicTab.style.position = 'relative';
      classicTab.style.zIndex = '2';
      classicTab.style.transition = 'color 0.65s cubic-bezier(.785, .135, .15, .86), transform 0.65s cubic-bezier(.785, .135, .15, .86)';

      const rankedTab = document.createElement('button');
      rankedTab.textContent = 'Ranked';
      rankedTab.style.padding = '12px 0';
      rankedTab.style.backgroundColor = 'transparent';
      rankedTab.style.color = this.currentTab === 'ranked' ? 'var(--plug-color1)' : 'var(--plug-color-buttonHover)';
      rankedTab.style.border = 'none';
      rankedTab.style.borderRadius = '0px';
      rankedTab.style.cursor = 'pointer';
      rankedTab.style.fontFamily = 'var(--font-display)';
      rankedTab.style.fontWeight = 'bold';
      rankedTab.style.flex = '1';
      rankedTab.style.width = '50%';
      rankedTab.style.position = 'relative';
      rankedTab.style.zIndex = '2';
      rankedTab.style.transition = 'color 0.65s cubic-bezier(.785, .135, .15, .86), transform 0.65s cubic-bezier(.785, .135, .15, .86)';

      const updateTabs = () => {
        activeTabBg.style.left = this.currentTab === 'classic' ? '0' : '50%';
        
        classicTab.style.color = this.currentTab === 'classic' ? 'var(--plug-color1)' : 'var(--plug-color-buttonHover)';
        rankedTab.style.color = this.currentTab === 'ranked' ? 'var(--plug-color1)' : 'var(--plug-color-buttonHover)';
        
        if (this.currentTab === 'classic') {
          classicTab.style.transform = 'scale(1.02)';
          rankedTab.style.transform = 'scale(1)';
        } else {
          classicTab.style.transform = 'scale(1)';
          rankedTab.style.transform = 'scale(1.02)';
        }
      };

      classicTab.addEventListener('click', () => {
        this.currentTab = 'classic';
        updateTabs();
        this.loadBordersIntoModal(list, modal);
      });

      rankedTab.addEventListener('click', () => {
        this.currentTab = 'ranked';
        updateTabs();
        this.loadBordersIntoModal(list, modal);
      });

      updateTabs();
      tabsContainer.appendChild(activeTabBg);
      tabsContainer.appendChild(classicTab);
      tabsContainer.appendChild(rankedTab);

      const listContainer = document.createElement('div');
      listContainer.style.flex = '1';
      listContainer.style.overflowY = 'auto';
      listContainer.style.overflowX = 'hidden';
      listContainer.style.marginTop = '-15px';
      listContainer.style.paddingRight = '10px';
            
      const list = document.createElement('div');
      list.style.display = 'grid';
      list.style.gridTemplateColumns = 'repeat(auto-fill, minmax(120px, 1fr))';
      list.style.marginTop = '10px';
      list.style.gap = '15px';
      list.style.width = '100%';
      list.style.boxSizing = 'border-box';

      listContainer.appendChild(list);
      content.appendChild(closeBtn);
      content.appendChild(tabsContainer);
      content.appendChild(listContainer);
      modal.appendChild(content);
      document.body.appendChild(modal);

      this.loadBordersIntoModal(list, modal);

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
    }

    async loadBordersIntoModal(list, modal) {
      try {
        list.innerHTML = '';

        const currentBorder = await this.getCurrentBorder();
		
        const filteredBorders = this.borderList.filter(border => {
          if (this.currentTab === 'classic') {
            return border.crestType === 'prestige';
          } else if (this.currentTab === 'ranked') {
            return border.crestType === 'ranked';
          }
          return false;
        });

        if (filteredBorders.length === 0) {
          list.innerHTML = `
            <div style="grid-column: 1 / -1; text-align: center; padding: 40px;">
              <p style="color: #e63946; font-size: 16px; margin: 0;">NOT FOUND 404</p>
              <p style="color: #3a6158; font-size: 12px; margin: 10px 0 0 0;">No ${this.currentTab} borders found</p>
            </div>
          `;
          return;
        }

		const items = filteredBorders.map((border) => {
		  const item = document.createElement('div');
		  item.style.padding = '10px';
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
		  
		  const isCurrentBorder = currentBorder && 
			currentBorder.uniqueId === border.uniqueId;
		  
		  const borderImg = new Image();
		  
		  list.appendChild(item);
		  
		  return { item, borderImg, border, isCurrentBorder };
		});

		const loadPromises = items.map(({ item, borderImg, border, isCurrentBorder }) => {
		  return new Promise((resolve) => {
			borderImg.onload = () => {
			  borderImg.style.width = '100%';
			  borderImg.style.height = '100%';
			  borderImg.style.objectFit = 'contain';
			  borderImg.style.borderRadius = '4px';
			  borderImg.style.boxSizing = 'border-box';
			  
			  if (isCurrentBorder) {
				borderImg.classList.add('selected-item-img');
				item.classList.add('selected-item-border');
			  }
			  
			  borderImg.addEventListener('mouseenter', () => {
				if (!isCurrentBorder) {
				  borderImg.style.animation = 'scaleUp 1s ease forwards';
				}
			  });

			  borderImg.addEventListener('mouseleave', () => {
				if (!isCurrentBorder) {
				  borderImg.style.animation = 'scaleDown 0.5s ease forwards';
				}
			  });
			  
			  item.addEventListener('mouseenter', () => {
				if (!isCurrentBorder) {
				  item.style.animation = 'BorderColorUp 1s ease forwards';
				}
			  });
			  
			  item.addEventListener('mouseleave', () => {
				if (!isCurrentBorder) {
				  item.style.animation = 'BorderColorDown 0.5s ease forwards';
				}
			  });
			  
			  item.addEventListener('click', async () => {
				await this.setCurrentBorder(border);
				await this.applyCustomBorder();
				document.body.removeChild(modal);
			  });
			  
			  item.appendChild(borderImg);
			  resolve();
			};
			borderImg.onerror = () => {
			  resolve();
			};
			borderImg.src = border.previewPath;
		  });
		});

		await Promise.all(loadPromises);

      } catch (error) {}
    }
  }
  
  window.addEventListener("load", () => {
    window.RegaliaBorder = new RegaliaBorder();
  });
})();