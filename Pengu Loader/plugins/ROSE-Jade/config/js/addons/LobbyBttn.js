import "https://plugins/Rose/config/css/LobbyBttn.css";

(() => {
  const CONFIG = {
    DATASTORE_KEY: "simple.button-shift-state"
  };

  class LobbyBttn {
    constructor() {
      this.buttonCreated = false;
      this.customBttn = null;
      this.isShifted = false;
      this.isActivated = false;
      this.observerInterval = null;
      this.transformInterval = null;
      this.init();
    }

    async init() {
      this.isShifted = await this.loadState();
      this.startObserver();
    }

    async loadState() {
      try {
        const savedState = await window.DataStore.get(CONFIG.DATASTORE_KEY);
        return savedState === true;
      } catch (error) {
        return false;
      }
    }

    async saveState() {
      try {
        await window.DataStore.set(CONFIG.DATASTORE_KEY, this.isShifted);
      } catch (error) {}
    }

    startObserver() {
      this.observerInterval = setInterval(() => {
        const container = document.querySelector('.lol-social-sidebar');
        const isContainerVisible = container && container.offsetParent !== null;
        
        if (isContainerVisible) {
          if (!this.buttonCreated) {
            this.customBttn = this.createButton();
            this.insertButtonIntoContainer(container);
            this.buttonCreated = true;
            this.updateButtonAppearance();
            
            if (!this.transformInterval) {
              this.startTransformObserver();
            }
          }
        } else {
          if (this.buttonCreated && this.customBttn) {
            this.customBttn.remove();
            this.customBttn = null;
            this.buttonCreated = false;
          }
        }
      }, 250);
    }

    startTransformObserver() {
      this.transformInterval = setInterval(() => {
        if (this.isActivated && this.isShifted) {
          this.applyTransformations();
        }
      }, 500);
    }

    insertButtonIntoContainer(container) {
      if (!this.customBttn || !container) return;

      container.style.overflow = 'visible';
      container.style.position = 'relative';
      container.appendChild(this.customBttn);
      
      this.customBttn.style.position = 'absolute';
      this.customBttn.style.left = '-24px';
      this.customBttn.style.top = '50%';
      this.customBttn.style.transform = 'translateY(-50%)';
    }

    async toggleContainerPosition() {
      if (!this.isActivated) {
        this.isActivated = true;
      }
      
      this.isShifted = !this.isShifted;
      await this.saveState();
      this.applyTransformations();
      this.rotateImage();
    }

    applyTransformations() {
      if (!this.isActivated) return;

      const pickPhaseElement = document.querySelector('.pick-phase');
      if (pickPhaseElement && pickPhaseElement.offsetParent !== null) {
        this.applyZeroTransform();
        return;
      }

      const flyoutTitleLabel = document.querySelector('.flyout-title-label');
      if (flyoutTitleLabel && flyoutTitleLabel.offsetParent !== null) {
        this.applyZeroTransform();
        return;
      }

      const elementsConfig = {
        container: '.lol-social-sidebar',
        identityElement: '.lol-social-identity',
        lobbyRoot: '.v2-lobby-root-component, .tft-cards-container, .parties-lower-section, .match-history-main, .lol-highlights-panel, .loading-container',
        partiesBg: '.parties-background',
        profileElement: '.style-profile-overview-component',
        profileBg: '.style-profile-backdrop-container',
        spbc: '.season-pass-body-container',
        ehspr: '.event-hub-season-pass-root',
        spf: '.season-pass-footer',
        ycw: '.yourshop-content-wrapper',
        simpleTrans: '.clash-tab-hub, .clash-tab-winners-content, .clash-tab-awards, .control-panel, .parties-game-select-wrapper',
        simpleTrans2: '.collections-sub-nav-container, .collection-side-panel',
        simpleTrans3: '.item-grid, .skins-grid, .emotes-root, .runes-route, .collections__items-route, .collection-spell-icons',
        champGrid: '.champion-grid',
        simpleTrans4: '.collection-spell-description, .loot-contents, .moon-skin-contents, .shoppefront-main-area, .activity-center-default-activity__footer--flex-end, .activity-center-metagame-activity__footer, .activity-center-ranked-activity__footer--flex-end, .activity-center-battlepass-activity__footer',
        tftHome: '.rcp-fe-lol-tft-application',
        tftStore: '.rcp-fe-lol-tft-rotational-shop',
        tftMatchH: '.tft-match-history-list',
        emblemProfile: '.style-profile-emblems-container',
        CCG: '.challenges-collection-component .content .grid',
        LLC: '.lol-leagues .lol-leagues-container',
		PMC: '.party-members-container'
      };

      const transformations = this.isShifted ? {
        container: 'translateX(225px)',
        identityElement: 'translateX(-225px)',
        lobbyRoot: 'translateX(100px)',
        partiesBg: 'translateX(100px) scale(1.5)',
        profileElement: 'translateX(50px)',
        profileBg: 'scale(1.5) translateY(75px) translateX(50px)',
        spbc: 'scale(0.65) translateY(-9px) translateX(19px)',
        ehspr: 'translateX(100px) scale(1.5)',
        spf: 'translateX(100px)',
        ycw: 'translateX(-365px)',
        simpleTrans: 'translateX(100px)',
        simpleTrans2: 'translateX(100px)',
        simpleTrans3: 'translateX(100px)',
        champGrid: 'translateX(25px)',
        simpleTrans4: 'translateX(100px)',
        tftHome: 'scale(0.67) translateX(-50px)',
        tftStore: 'scale(0.65) translateX(-70px)',
        tftMatchH: 'scale(0.7) translateX(30px) translateY(-30px)',
        emblemProfile: 'scale(0.9) translateX(-50px)',
        CCG: 'translateX(100px)',
        LLC: 'translateX(100px)',
		PMC: 'translateX(-100px)'
      } : {
        container: 'translateX(0)',
        identityElement: 'translateX(0)',
        lobbyRoot: 'translateX(0)',
        partiesBg: 'translateX(0) scale(1.5)',
        profileElement: 'translateX(0px)',
        profileBg: 'scale(1.5) translateY(75px) translateX(0px)',
        spbc: 'scale(0.65) translateY(-9px) translateX(-81px)',
        ehspr: 'translateX(0) scale(1.5)',
        spf: 'translateX(0)',
        ycw: 'translateX(-465px)',
        simpleTrans: 'translateX(0)',
        simpleTrans2: 'translateX(0px)',
        simpleTrans3: 'translateX(0px)',
        champGrid: 'translateX(25px)',
        simpleTrans4: 'translateX(0px)',
        tftHome: 'scale(0.67) translateX(-150px)',
        tftStore: 'scale(0.65) translateX(-170px)',
        tftMatchH: 'scale(0.7) translateX(-70px) translateY(-30px)',
        emblemProfile: 'scale(1) translateX(0px)',
        CCG: 'translateX(0px)',
        LLC: 'translateX(0px)',
		PMC: 'translateX(0px)'
      };

      Object.keys(elementsConfig).forEach(key => {
        const selector = elementsConfig[key];
        const elements = document.querySelectorAll(selector);
        
        elements.forEach(element => {
          if (element && transformations[key]) {
            element.style.transform = transformations[key];
            element.style.transition = 'transform 0.3s ease';
          }
        });
      });
    }

    applyZeroTransform() {
      const elementsConfig = {
        container: '.lol-social-sidebar',
        identityElement: '.lol-social-identity',
        lobbyRoot: '.v2-lobby-root-component, .tft-cards-container, .parties-lower-section, .match-history-main, .lol-highlights-panel, .loading-container',
        partiesBg: '.parties-background',
        profileElement: '.style-profile-overview-component',
        profileBg: '.style-profile-backdrop-container',
        spbc: '.season-pass-body-container',
        ehspr: '.event-hub-season-pass-root',
        spf: '.season-pass-footer',
        ycw: '.yourshop-content-wrapper',
        simpleTrans: '.clash-tab-hub, .clash-tab-winners-content, .clash-tab-awards, .control-panel, .parties-game-select-wrapper',
        simpleTrans2: '.collections-sub-nav-container, .collection-side-panel',
        simpleTrans3: '.item-grid, .skins-grid, .emotes-root, .runes-route, .collections__items-route, .collection-spell-icons',
        champGrid: '.champion-grid',
        simpleTrans4: '.collection-spell-description, .loot-contents, .moon-skin-contents, .shoppefront-main-area, .activity-center-default-activity__footer--flex-end, .activity-center-metagame-activity__footer, .activity-center-ranked-activity__footer--flex-end, .activity-center-battlepass-activity__footer',
        tftHome: '.rcp-fe-lol-tft-application',
        tftStore: '.rcp-fe-lol-tft-rotational-shop',
        tftMatchH: '.tft-match-history-list',
        emblemProfile: '.style-profile-emblems-container',
        CCG: '.challenges-collection-component .content .grid',
        LLC: '.lol-leagues .lol-leagues-container'
      };

      const zeroTransformations = {
        container: 'translateX(0)',
        identityElement: 'translateX(0)',
        lobbyRoot: 'translateX(0)',
        partiesBg: 'translateX(0) scale(1.5)',
        profileElement: 'translateX(0px)',
        profileBg: 'scale(1.5) translateY(75px) translateX(0px)',
        spbc: 'scale(0.65) translateY(-9px) translateX(-81px)',
        ehspr: 'translateX(0) scale(1.5)',
        spf: 'translateX(0)',
        ycw: 'translateX(-465px)',
        simpleTrans: 'translateX(0)',
        simpleTrans2: 'translateX(0px)',
        simpleTrans3: 'translateX(0px)',
        champGrid: 'translateX(25px)',
        simpleTrans4: 'translateX(0px)',
        tftHome: 'scale(0.67) translateX(-150px)',
        tftStore: 'scale(0.65) translateX(-170px)',
        tftMatchH: 'scale(0.7) translateX(-70px) translateY(-30px)',
        emblemProfile: 'scale(1) translateX(0px)',
        CCG: 'translateX(0px)',
        LLC: 'translateX(0px)'
      };

      Object.keys(elementsConfig).forEach(key => {
        const selector = elementsConfig[key];
        const elements = document.querySelectorAll(selector);
        
        elements.forEach(element => {
          if (element && zeroTransformations[key]) {
            element.style.transform = zeroTransformations[key];
            element.style.transition = 'transform 0.3s ease';
          }
        });
      });
    }

    updateButtonAppearance() {
      this.rotateImage();
    }

    rotateImage() {
      if (!this.customBttn) return;
      
      const img = this.customBttn.querySelector('img');
      if (img) {
        img.style.transform = this.isShifted ? 'rotate(180deg)' : 'rotate(0deg)';
        img.style.transition = 'transform 0.3s ease';
      }
    }

    createButton() {
      const button = document.createElement('button');
      const img = document.createElement('img');
      img.src = '/fe/lol-uikit/images/border-arrow-up.png';
      img.style.width = '15px';
      img.style.height = '15px';
      img.style.display = 'block';
      img.style.transition = 'transform 0.3s ease';
      button.appendChild(img);
      button.style.zIndex = '9999';
      button.style.backgroundColor = 'transparent';
      button.style.border = 'none';
      button.style.cursor = 'pointer';
      button.style.transition = 'all 0.3s ease';
      button.style.whiteSpace = 'nowrap';
	  button.style.filter = 'var(--Rose-filter2)';
      
      button.addEventListener('click', () => {
        this.toggleContainerPosition();
      });
      
      return button;
    }

    destroy() {
      if (this.observerInterval) {
        clearInterval(this.observerInterval);
      }
      if (this.transformInterval) {
        clearInterval(this.transformInterval);
      }
      if (this.customBttn) {
        this.customBttn.remove();
      }
    }
  }
  
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      window.LobbyBttn = new LobbyBttn();
    });
  } else {
    window.LobbyBttn = new LobbyBttn();
  }
})();