(() => {
  const CONFIG = {
    STYLE_ID: "regalia.banner-style",
    MODAL_ID: "regalia.banner-modal",
    DATASTORE_KEY: "regalia.banner-datastore",
    API_URL: "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/regalia.json",
  };

  class RegaliaBanner {
    constructor() {
      this.buttonCreated = false;
      this.customButton = null;
      this.bannerInterval = null;
      this.bannerTimeouts = [];
      this.currentBannerPath = null;
      this.bannerObservers = new Map();
      this.init();
    }

    async init() {
      try {
        this.applyCustomBanner();
        this.startButtonObserver();
      } catch (error) {}
    }

    startButtonObserver() {
      const checkInterval = setInterval(() => {
        const isBannerVisible = this.isBannerContainerVisible();
        const isPlayerVisible = this.isPlayerActive();
        
        if (isPlayerVisible) {
          this.applyCustomBanner();
        }
        
        if (isBannerVisible) {
          if (!this.buttonCreated) {
            this.customButton = this.createBannerButton();
            this.customButton.addEventListener('click', () => this.showBannerModal());
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

    isBannerContainerVisible() {
      const bannerContainer = document.querySelector('.identity-customizer-banner-wrapper');
      return bannerContainer && bannerContainer.offsetParent !== null;
    }

    isPlayerActive() {
      const lobbyContainer = document.querySelector('.v2-banner-component.local-player');
      const profileInfo = document.querySelector('.style-profile-summoner-info-component');
      
      return (lobbyContainer && lobbyContainer.offsetParent !== null) || 
             (profileInfo && profileInfo.offsetParent !== null);
    }

    createBannerButton() {
      const button = document.createElement('button');
      
      const img = document.createElement('img');
      img.src = '/fe/lol-uikit/images/icon_settings.png';
      img.style.width = '15px';
      img.style.height = '15px';
      img.style.display = 'block';
      
      button.appendChild(img);
      button.style.position = 'fixed';
      button.style.bottom = '514px';
      button.style.right = '300px';
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

    async applyCustomBanner() {
      try {
        this.revertBanner();
        const selectedBannerPath = await window.DataStore.get(CONFIG.DATASTORE_KEY);

        if (!selectedBannerPath) {
          return;
        }

        this.currentBannerPath = selectedBannerPath;

        const replaceBanners = () => {
          try {
            if (this.currentBannerPath !== selectedBannerPath) return;

            const targetContainers = [
              '.style-profile-summoner-info-component',
              '.challenges-identity-customizer-banner-container', 
              '.v2-banner-component.local-player'
            ];
            
            targetContainers.forEach(containerSelector => {
              const containers = document.querySelectorAll(containerSelector);
              
              containers.forEach(container => {
                const findAndReplace = (element) => {
                  const banners = element.querySelectorAll('.regalia-banner-asset-static-image');
                  banners.forEach(banner => {
                    if (!banner._bannerReplaced) {
                      banner.src = selectedBannerPath;
                      banner._bannerReplaced = true;
                      this.observeBannerChanges(banner, selectedBannerPath);
                    }
                  });
                  
                  if (element.shadowRoot) {
                    const shadowBanners = element.shadowRoot.querySelectorAll('.regalia-banner-asset-static-image');
                    shadowBanners.forEach(banner => {
                      if (!banner._bannerReplaced) {
                        banner.src = selectedBannerPath;
                        banner._bannerReplaced = true;
                        this.observeBannerChanges(banner, selectedBannerPath);
                      }
                    });
                    
                    element.shadowRoot.querySelectorAll('*').forEach(child => {
                      findAndReplace(child);
                    });
                  }
                  
                  element.querySelectorAll('*').forEach(child => {
                    if (child.shadowRoot) {
                      findAndReplace(child);
                    }
                  });
                };
                
                findAndReplace(container);
              });
            });
            
          } catch (error) {}
        };

        replaceBanners();
        
        const delays = [200, 500, 1000, 2000];
        this.bannerTimeouts = delays.map(delay => 
          setTimeout(() => {
            if (this.currentBannerPath === selectedBannerPath) {
              replaceBanners();
            }
          }, delay)
        );

        this.bannerInterval = setInterval(() => {
          if (this.currentBannerPath === selectedBannerPath) {
            replaceBanners();
          }
        }, 2000);

      } catch (error) {}
    }

    observeBannerChanges(banner, targetPath) {
      try {
        const observer = new MutationObserver((mutations) => {
          mutations.forEach((mutation) => {
            if (mutation.type === 'attributes' && mutation.attributeName === 'src') {
              const currentSrc = banner.getAttribute('src');
              if (currentSrc !== targetPath) {
                banner.src = targetPath;
              }
            }
          });
        });
        
        observer.observe(banner, {
          attributes: true,
          attributeFilter: ['src']
        });
        
        this.bannerObservers.set(banner, observer);
        
      } catch (error) {}
    }
	
    revertBanner() {
      try {
        if (this.bannerInterval) {
          clearInterval(this.bannerInterval);
          this.bannerInterval = null;
        }
        
        if (this.bannerTimeouts) {
          this.bannerTimeouts.forEach(timeout => clearTimeout(timeout));
          this.bannerTimeouts = [];
        }
        
        if (this.bannerObservers) {
          this.bannerObservers.forEach((observer, banner) => {
            try {
              observer.disconnect();
              delete banner._bannerReplaced;
            } catch (e) {}
          });
          this.bannerObservers.clear();
        }
        
        this.currentBannerPath = null;
        
      } catch (error) {}
    }
	
    async getCurrentBanner() {
      return await window.DataStore.get(CONFIG.DATASTORE_KEY);
    }

    async showBannerModal() {
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
      reminder.style.marginBottom = '10px';
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
      
      const listContainer = document.createElement('div');
      listContainer.style.flex = '1';
      listContainer.style.overflowY = 'auto';
      listContainer.style.overflowX = 'hidden';
      listContainer.style.marginTop = '-10px';
	  listContainer.style.scrollbarWidth = 'none';
	  listContainer.style.msOverflowStyle = 'none';
	  listContainer.id = 'banner-list-content';
	  
	  const scrollbarStyle = document.createElement('style');
		scrollbarStyle.textContent = `
		  #banner-list-content::-webkit-scrollbar {
			display: none;
		  }
		`;
		document.head.appendChild(scrollbarStyle);
            
      const list = document.createElement('div');
      list.style.display = 'grid';
      list.style.gridTemplateColumns = 'repeat(auto-fill, minmax(120px, 1fr))';
	  list.style.marginTop = '10px';
      list.style.gap = '15px';
      list.style.width = '100%';
      list.style.boxSizing = 'border-box';

      listContainer.appendChild(list);
      content.appendChild(closeBtn);
      content.appendChild(listContainer);
      modal.appendChild(content);
      document.body.appendChild(modal);

      this.loadBannersIntoModal(list, modal);

      modal.addEventListener('click', (e) => {
		  if (e.target === modal) {
			document.body.removeChild(modal);
			if (scrollbarStyle && scrollbarStyle.parentNode) {
			  document.head.removeChild(scrollbarStyle);
			}
		  }
		});
      
      const handleEscape = (e) => {
		  if (e.key === 'Escape') {
			document.body.removeChild(modal);
			document.removeEventListener('keydown', handleEscape);
			if (scrollbarStyle && scrollbarStyle.parentNode) {
			  document.head.removeChild(scrollbarStyle);
			}
		  }
		};
      
      modal.addEventListener('DOMNodeRemoved', () => {
		  document.removeEventListener('keydown', handleEscape);
		  if (scrollbarStyle && scrollbarStyle.parentNode) {
			document.head.removeChild(scrollbarStyle);
		  }
		});
    }

    async loadBannersIntoModal(list, modal) {
      try {
        const response = await fetch(CONFIG.API_URL);
        const regaliaData = await response.json();
        
        list.innerHTML = '';

        const validBanners = [];
        const currentBannerPath = await window.DataStore.get(CONFIG.DATASTORE_KEY);
        
        const extractAllBanners = (data) => {
          const banners = [];
          const processedPaths = new Set();

          function traverse(obj) {
            if (!obj) return;

            if (obj.assetPath && typeof obj.assetPath === 'string') {
              const assetPath = obj.assetPath.toLowerCase();
              if (assetPath.includes('bannerskins') && assetPath.endsWith('.png')) {
                const fullPath = obj.assetPath.startsWith('/') ? 
                  obj.assetPath : `/lol-game-data/assets/ASSETS/Regalia/BannerSkins/${obj.assetPath}`;
                
                if (!processedPaths.has(fullPath)) {
                  banners.push({
                    id: obj.id || fullPath,
                    name: obj.name || obj.internalName || `Banner ${banners.length + 1}`,
                    assetPath: fullPath
                  });
                  processedPaths.add(fullPath);
                }
              }
            }

            if (typeof obj === 'object') {
              for (let key in obj) {
                if (obj.hasOwnProperty(key)) {
                  traverse(obj[key]);
                }
              }
            }

            if (Array.isArray(obj)) {
              obj.forEach(item => traverse(item));
            }
          }

          traverse(data);
          return banners;
        };

        const allBanners = extractAllBanners(regaliaData);

        const bannerPromises = allBanners.map((banner) => {
          return new Promise((resolve) => {
            const img = new Image();
            img.onload = () => {
              validBanners.push({ 
                ...banner, 
                element: img
              });
              resolve();
            };
            img.onerror = () => {
              resolve();
            };
            img.src = banner.assetPath;
            img.style.width = '100%';
            img.style.height = '100%';
            img.style.objectFit = 'cover';
            img.style.borderRadius = '4px';
            img.style.boxSizing = 'border-box';
          });
        });

        await Promise.all(bannerPromises);

        validBanners.sort((a, b) => a.name.localeCompare(b.name));

        validBanners.forEach(banner => {
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
          
          const bannerImg = banner.element.cloneNode(true);
          
          if (banner.assetPath === currentBannerPath) {
			bannerImg.classList.add('selected-item-img');
			item.classList.add('selected-item-border');
          }
          
          bannerImg.addEventListener('mouseenter', () => {
            if (banner.assetPath !== currentBannerPath) {
              bannerImg.style.animation = 'scaleUp 1s ease forwards';
            }
          });

          bannerImg.addEventListener('mouseleave', () => {
            if (banner.assetPath !== currentBannerPath) {
              bannerImg.style.animation = 'scaleDown 0.5s ease forwards';
            }
          });
		  
		  item.addEventListener('mouseenter', () => {
			if (banner.assetPath !== currentBannerPath) {
			  item.style.animation = 'BorderColorUp 1s ease forwards';
			}
		  });
		  
		  item.addEventListener('mouseleave', () => {
			if (banner.assetPath !== currentBannerPath) {
			  item.style.animation = 'BorderColorDown 0.5s ease forwards';
			}
		  });
          
          item.addEventListener('click', async () => {
            await window.DataStore.set(CONFIG.DATASTORE_KEY, banner.assetPath);
            await this.applyCustomBanner();
            document.body.removeChild(modal);
          });
          
          item.appendChild(bannerImg);
          list.appendChild(item);
        });

        if (validBanners.length === 0) {
          list.innerHTML = '<div style="grid-column: 1 / -1; text-align: center; padding: 40px;"><p style="color: #e63946; font-size: 16px; margin: 0;">No valid banners found. Please try again later.</p></div>';
        }
      } catch (error) {
        list.innerHTML = '<div style="grid-column: 1 / -1; text-align: center; padding: 40px;"><p style="color: #e63946; font-size: 16px; margin: 0;">Failed to load banners. Please try again later.</p></div>';
      }
    }
  }

  window.addEventListener("load", () => {
    window.RegaliaBanner = new RegaliaBanner();
  });
})();