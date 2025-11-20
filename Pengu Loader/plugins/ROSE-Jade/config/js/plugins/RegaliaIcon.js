(() => {
  const CONFIG = {
    STYLE_ID: "regalia.icon-style",
    MODAL_ID: "regalia.icon-modal",
    DATASTORE_KEY: "regalia.icon-datastore",
    API_URL: "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/summoner-icons.json"
  };

  let currentIconSearchQuery = "";
  let iconSearchTimeout = null;
  let currentPage = 1;
  const ITEMS_PER_PAGE = 32;

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

  function replaceIconBackground() {
    function findAndReplaceIcon(element) {
      if (!element) return false;
      
      let found = false;
      
      if (element.shadowRoot) {
        const iconElement = element.shadowRoot.querySelector('.lol-regalia-summoner-icon');
        if (iconElement && iconElement.style.backgroundImage) {
          iconElement.style.backgroundImage = 'var(--custom-avatar)';
          found = true;
        }
        
        const shadowChildren = element.shadowRoot.querySelectorAll('*');
        shadowChildren.forEach(child => {
          if (findAndReplaceIcon(child)) {
            found = true;
          }
        });
      }
      
      return found;
    }
    
    function applyReplacement() {
      const customizerElement = document.querySelector('lol-regalia-identity-customizer-element');
      if (!customizerElement) {
        return false;
      }
      
      const crestElement = customizerElement.shadowRoot?.querySelector('lol-regalia-crest-v2-element');
      if (!crestElement) {
        return false;
      }
      
      return findAndReplaceIcon(crestElement);
    }
    
    const success = applyReplacement();
    return success;
  }

  function observeIconChanges() {
    const observer = new MutationObserver((mutations) => {
      let shouldReplace = false;
      
      for (const mutation of mutations) {
        for (const node of mutation.addedNodes) {
          if (node.nodeType === Node.ELEMENT_NODE) {
            if (node.tagName === 'LOL-REGALIA-IDENTITY-CUSTOMIZER-ELEMENT' || 
                node.querySelector('lol-regalia-identity-customizer-element')) {
              shouldReplace = true;
              break;
            }
          }
        }
        
        if (shouldReplace) break;
      }
      
      if (shouldReplace) {
        setTimeout(() => {
          replaceIconBackground();
        }, 100);
      }
    });
    
    observer.observe(document.body, {
      childList: true,
      subtree: true
    });
    
    return observer;
  }

  function checkTabVisibility() {
    const tabComponent = document.querySelector('.identity-customizer-tab-icons-component');
    const isVisible = tabComponent && tabComponent.offsetParent !== null;
    return isVisible;
  }

  function initIconReplacement() {
    if (checkTabVisibility()) {
      setTimeout(() => {
        replaceIconBackground();
      }, 100);
    }
    
    const visibilityObserver = new MutationObserver(() => {
      if (checkTabVisibility()) {
        setTimeout(() => {
          replaceIconBackground();
        }, 100);
      }
    });
    
    const domObserver = observeIconChanges();
    
    const intervalId = setInterval(() => {
      if (checkTabVisibility()) {
        replaceIconBackground();
      }
    }, 100);
    
    return {
      stop: () => {
        visibilityObserver.disconnect();
        domObserver.disconnect();
        clearInterval(intervalId);
      }
    };
  }

  const iconReplacer = initIconReplacement();

  setTimeout(() => {
    replaceIconBackground();
  }, 100);

  class RegaliaIcon {
    constructor() {
      this.summonerId = null;
      this.puuid = null;
      this.observer = null;
      this.buttonCreated = false;
      this.customButton = null;
      this.iconInterval = null;
      this.iconTimeouts = [];
      this.currentIconId = null;
      this.iconsData = null;
      this.dataLoaded = false;
      this.sortedIcons = null;
      this.init();
    }

    async init() {
      try {
        try {
          const res = await fetch("/lol-summoner/v1/current-summoner");
          const data = await res.json();
          this.summonerId = data.summonerId;
          this.puuid = data.puuid;
        } catch (e) {}

        this.applyCustomIcon();
        this.IconContainerObserver();
      } catch (error) {}
    }

    async loadIconsData() {
      if (this.dataLoaded) return;
      
      try {
        const response = await fetch(CONFIG.API_URL);
        const icons = await response.json();
        this.iconsData = icons.filter((icon) => icon.id !== -1);
        
        this.sortedIcons = [...this.iconsData].sort((a, b) => b.id - a.id);
        
        this.dataLoaded = true;
      } catch (error) {
        this.iconsData = [];
        this.sortedIcons = [];
        this.dataLoaded = true;
      }
    }
	
	IconContainerObserver() {
		const checkInterval = setInterval(() => {
			const isIconVisible = this.isIconContainerVisible();
			
			if (isIconVisible) {
				if (!this.buttonCreated) {
					this.customButton = this.createIconButton();
					this.customButton.addEventListener('click', () => this.showIconModal());
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
	
	isIconContainerVisible() {
        const IconContainer = document.querySelector('.identity-customizer-icon-header');
        return IconContainer && IconContainer.offsetParent !== null;
    }
	
    createIconButton() {
        const button = document.createElement('button');
        
        const img = document.createElement('img');
		img.src = '/fe/lol-uikit/images/icon_settings.png'
		img.style.width = '15px';
        img.style.height = '15px';
        img.style.display = 'block';
        
        button.appendChild(img);
        button.style.position = 'fixed';
        button.style.bottom = '515px';
        button.style.right = '350px';
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

    revertIcon() {
      if (this.observer) {
        this.observer.disconnect();
        this.observer = null;
      }
      if (this.iconInterval) {
        clearInterval(this.iconInterval);
        this.iconInterval = null;
      }
      if (this.iconTimeouts) {
        this.iconTimeouts.forEach(timeout => clearTimeout(timeout));
        this.iconTimeouts = [];
      }
      const styleElement = document.getElementById(CONFIG.STYLE_ID);
      if (styleElement) {
        styleElement.remove();
      }
      this.currentIconId = null;
    }

    async applyCustomIcon() {
      this.revertIcon();
      const selectedId = await window.DataStore.get(CONFIG.DATASTORE_KEY);

      if (!selectedId) {
        return;
      }

      this.currentIconId = selectedId;

      const iconUrl = `/lol-game-data/assets/v1/profile-icons/${selectedId}.jpg`;

      const style = document.createElement("style");
      style.id = CONFIG.STYLE_ID;
      style.innerHTML = `
        :root { --custom-avatar: url("${iconUrl}"); }
        .top > .icon-image.has-icon, summoner-icon {
          content: var(--custom-avatar) !important;
        }
        .lol-regalia-summoner-icon {
          background-image: var(--custom-avatar) !important;
        }
      `;
      document.head.appendChild(style);

      const applyIcons = () => {
        if (this.currentIconId !== selectedId) return;

        const updateAndFreezeIcon = (element) => {
          const iconElement = element.shadowRoot
            ?.querySelector("lol-regalia-crest-v2-element")
            ?.shadowRoot?.querySelector(".lol-regalia-summoner-icon");
          if (iconElement) {
            iconElement.style.backgroundImage = "var(--custom-avatar)";
            StopTimeProp(iconElement.style, ["backgroundImage"]);
            return;
          }

          if (element.tagName === "LOL-REGALIA-CREST-V2-ELEMENT") {
            const crestIcon = element.shadowRoot?.querySelector(
              ".lol-regalia-summoner-icon"
            );
            if (crestIcon) {
              crestIcon.style.backgroundImage = "var(--custom-avatar)";
              StopTimeProp(crestIcon.style, ["backgroundImage"]);
            }
          }
        };

        const regaliaIcons = document.querySelectorAll('.lol-regalia-summoner-icon');
        regaliaIcons.forEach(icon => {
          icon.style.backgroundImage = "var(--custom-avatar)";
          StopTimeProp(icon.style, ["backgroundImage"]);
        });

        const selectors = [
          `lol-regalia-hovercard-v2-element[summoner-id="${this.summonerId}"]`,
          `lol-regalia-profile-v2-element[summoner-id="${this.summonerId}"]`,
          `lol-regalia-parties-v2-element[summoner-id="${this.summonerId}"]`,
          `lol-regalia-crest-v2-element[voice-puuid="${this.puuid}"]`,
        ];
        const combinedSelector = selectors.join(", ");

        const existingElements = document.querySelectorAll(combinedSelector);
        existingElements.forEach(updateAndFreezeIcon);
      };

      applyIcons();

      const delays = [200, 500, 1000, 2000];
      this.iconTimeouts = delays.map(delay => 
        setTimeout(() => {
          if (this.currentIconId === selectedId) {
            applyIcons();
          }
        }, delay)
      );

      this.iconInterval = setInterval(() => {
        if (this.currentIconId === selectedId) {
          applyIcons();
        }
      }, 2000);

      this.observeDOM();
    }

    observeDOM() {
      const updateAndFreezeIcon = (element) => {
        const iconElement = element.shadowRoot
          ?.querySelector("lol-regalia-crest-v2-element")
          ?.shadowRoot?.querySelector(".lol-regalia-summoner-icon");
        if (iconElement) {
          iconElement.style.backgroundImage = "var(--custom-avatar)";
          StopTimeProp(iconElement.style, ["backgroundImage"]);
          return;
        }

        if (element.tagName === "LOL-REGALIA-CREST-V2-ELEMENT") {
          const crestIcon = element.shadowRoot?.querySelector(
            ".lol-regalia-summoner-icon"
          );
          if (crestIcon) {
            crestIcon.style.backgroundImage = "var(--custom-avatar)";
            StopTimeProp(crestIcon.style, ["backgroundImage"]);
          }
        }

        if (element.classList && element.classList.contains('lol-regalia-summoner-icon')) {
          element.style.backgroundImage = "var(--custom-avatar)";
          StopTimeProp(element.style, ["backgroundImage"]);
        }
      };

      const selectors = [
        `lol-regalia-hovercard-v2-element[summoner-id="${this.summonerId}"]`,
        `lol-regalia-profile-v2-element[summoner-id="${this.summonerId}"]`,
        `lol-regalia-parties-v2-element[summoner-id="${this.summonerId}"]`,
        `lol-regalia-crest-v2-element[voice-puuid="${this.puuid}"]`,
        '.lol-regalia-summoner-icon'
      ];
      const combinedSelector = selectors.join(", ");

      this.observer = new MutationObserver((mutations) => {
        for (const mutation of mutations) {
          for (const node of mutation.addedNodes) {
            if (node instanceof Element) {
              if (node.matches(combinedSelector)) {
                updateAndFreezeIcon(node);
              }
              const matchingElements = node.querySelectorAll(combinedSelector);
              if (matchingElements.length > 0) {
                matchingElements.forEach(updateAndFreezeIcon);
              }
            }
          }
        }
      });

      this.observer.observe(document.body, { childList: true, subtree: true });
      const existingElements = document.querySelectorAll(combinedSelector);
      existingElements.forEach(updateAndFreezeIcon);
    }

	async showIconModal() {
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
	  reminder.style.padding = '10px'
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
        currentIconSearchQuery = '';
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
			<p style="color: #728581; font-size: 16px; margin: 0;">Loading icons...</p>
		  </div>
		`;
		
		await this.loadIconsData();
	  }

	  let totalPages = 0;
	  let pageInput = null;

	  const updatePagination = (filteredIcons) => {
        totalPages = Math.ceil(filteredIcons.length / ITEMS_PER_PAGE);
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

	  const loadCurrentPage = (filteredIcons) => {
        const startIndex = (currentPage - 1) * ITEMS_PER_PAGE;
        const endIndex = startIndex + ITEMS_PER_PAGE;
        const pageIcons = filteredIcons.slice(startIndex, endIndex);
        
        this.loadIconsIntoModal(list, pageIcons);
        updatePagination(filteredIcons);
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
				const filteredIcons = this.getFilteredIcons();
				loadCurrentPage(filteredIcons);
				
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
          const filteredIcons = this.getFilteredIcons();
          loadCurrentPage(filteredIcons);
        }
      });

      nextButton.addEventListener('click', () => {
        const filteredIcons = this.getFilteredIcons();
        const totalPages = Math.ceil(filteredIcons.length / ITEMS_PER_PAGE);
        if (currentPage < totalPages) {
          currentPage++;
          loadCurrentPage(filteredIcons);
        }
      });

      searchInput.addEventListener('input', () => {
        if (iconSearchTimeout) {
          clearTimeout(iconSearchTimeout);
        }
        
        iconSearchTimeout = setTimeout(() => {
          currentIconSearchQuery = searchInput.value.toLowerCase().trim();
          currentPage = 1;
          const filteredIcons = this.getFilteredIcons();
          loadCurrentPage(filteredIcons);
        }, 500);
      });

	  const filteredIcons = this.getFilteredIcons();
      loadCurrentPage(filteredIcons);

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

    getFilteredIcons() {
      if (!this.sortedIcons || !this.dataLoaded) return [];
      
      let filteredIcons = this.sortedIcons;
      
      if (currentIconSearchQuery) {
        filteredIcons = this.sortedIcons.filter(icon => 
          icon && icon.title && icon.title.toLowerCase().includes(currentIconSearchQuery)
        );
      }

      return filteredIcons;
    }

    async loadIconsIntoModal(list, iconsToLoad) {
	  try {
        if (!this.dataLoaded) {
          list.innerHTML = `
            <div style="grid-column: 1 / -1; text-align: center; padding: 40px;">
              <p style="color: #728581; font-size: 16px; margin: 0;">Loading icons...</p>
            </div>
          `;
          return;
        }
		
		list.innerHTML = '';

		const validIcons = [];
		const currentIconId = await window.DataStore.get(CONFIG.DATASTORE_KEY);
		
		const iconPromises = iconsToLoad.map((icon) => {
		  return new Promise((resolve) => {
			const img = new Image();
			img.onload = () => {
			  validIcons.push({ 
				...icon, 
				element: img
			  });
			  resolve();
			};
			img.onerror = () => {
			  resolve();
			};
			img.src = `/lol-game-data/assets/v1/profile-icons/${icon.id}.jpg`;
			img.style.width = '100%';
			img.style.height = '100%';
			img.style.objectFit = 'cover';
			img.style.borderRadius = '4px';
			img.style.boxSizing = 'border-box';
		  });
		});

		await Promise.all(iconPromises);

		if (validIcons.length === 0) {
		  list.innerHTML = `
            <div style="grid-column: 1 / -1; text-align: center; padding: 40px;">
              <p style="color: #728581; font-size: 16px; margin: 0;">
                ${this.iconsData ? 'No icons found matching your search.' : 'Loading icons...'}
              </p>
            </div>
          `;
		  return;
		}

		validIcons.forEach(icon => {
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
		  
		  const iconImg = icon.element.cloneNode(true);
		  
		  if (icon.id === currentIconId) {
			iconImg.classList.add('selected-item-img');
			item.classList.add('selected-item-border');
		  }
		  
		  iconImg.addEventListener('mouseenter', () => {
			if (icon.id !== currentIconId) {
			  iconImg.style.animation = 'scaleUp 1s ease forwards';
			}
		  });

		  iconImg.addEventListener('mouseleave', () => {
			if (icon.id !== currentIconId) {
			  iconImg.style.animation = 'scaleDown 0.5s ease forwards';
			}
		  });
		  
		  item.addEventListener('mouseenter', () => {
			if (icon.id !== currentIconId) {
			  item.style.animation = 'BorderColorUp 1s ease forwards';
			}
		  });
		  
		  item.addEventListener('mouseleave', () => {
			if (icon.id !== currentIconId) {
			  item.style.animation = 'BorderColorDown 0.5s ease forwards';
			}
		  });
		  
		  item.addEventListener('click', async () => {
			await window.DataStore.set(CONFIG.DATASTORE_KEY, icon.id);
			await this.applyCustomIcon();
			currentIconSearchQuery = '';
			currentPage = 1;
			document.body.removeChild(document.getElementById(CONFIG.MODAL_ID));
		  });
		  
		  item.appendChild(iconImg);
		  list.appendChild(item);
		});

	  } catch (error) {
		list.innerHTML = '<div style="grid-column: 1 / -1; text-align: center; padding: 40px;"><p style="color: #e63946; font-size: 16px; margin: 0;">Failed to load icons. Please try again later.</p></div>';
	  }
	}
  }

  window.addEventListener("load", () => {
    window.RegaliaIcon = new RegaliaIcon();
  });
})();