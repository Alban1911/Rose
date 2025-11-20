(() => {
    class PlayButtonPlugin {
        constructor() {
            this.playButtonCreated = false;
            this.playButton = null;
            this.observerInterval = null;
            this.isMinimized = false;
            this.minimizedButton = null;
            this.minimizedModal = null;
            this.init();
        }

        init() {
            this.startPlayButtonObserver();
        }

        startPlayButtonObserver() {
            this.observerInterval = setInterval(() => {
                const isQueueVisible = this.isQueueClassVisible();
                
                if (isQueueVisible) {
                    if (!this.playButtonCreated) {
                        this.createPlayButton();
                        this.playButtonCreated = true;
                    }
                } else {
                    if (this.playButtonCreated && this.playButton) {
                        this.removePlayButton();
                        this.playButtonCreated = false;
                    }
                }
            }, 250);
        }

        isQueueClassVisible() {
            const queueElement = document.querySelector('.party-members-container'); // "queue" or "lobby" or "party-members-container"
            return queueElement && queueElement.offsetParent !== null;
        }

        createPlayButton() {
            this.playButton = document.createElement('button');
            this.playButton.textContent = 'IDDQD';
            
            this.playButton.style.position = 'fixed';
            this.playButton.style.bottom = '560px';
            this.playButton.style.right = '240px';
            this.playButton.style.zIndex = '9999';
            this.playButton.style.padding = '6px 12px';
            this.playButton.style.backgroundColor = '#1e292c';
            this.playButton.style.border = '2px solid #81602b';
            this.playButton.style.borderRadius = '4px';
            this.playButton.style.cursor = 'pointer';
            
            this.playButton.style.color = '#cdbe91';
            this.playButton.style.fontFamily = 'var(--font-display)';
            this.playButton.style.fontSize = '10px';
            this.playButton.style.fontWeight = 'bold';
            this.playButton.style.letterSpacing = '1px';
            this.playButton.style.textTransform = 'uppercase';
            
            this.playButton.style.boxShadow = '0 2px 10px rgba(0,0,0,0.3)';
            this.playButton.style.transition = 'all 0.3s ease';
            
            this.playButton.addEventListener('mouseenter', () => {
                this.playButton.style.color = '#f0e6d2';
                this.playButton.style.animation = 'HoverTextShadow 600ms cubic-bezier(0, 0, 0.33, 1) 1 forwards';
            });
            
            this.playButton.addEventListener('mouseleave', () => {
                this.playButton.style.color = '#cdbe91';
            });
            
            this.playButton.addEventListener('click', () => {
                this.showIddqdModal();
            });
            
            document.body.appendChild(this.playButton);
        }

        removePlayButton() {
            if (this.playButton && this.playButton.parentNode) {
                document.body.removeChild(this.playButton);
                this.playButton = null;
            }
            this.removeMinimizedButton();
        }

        showIddqdModal() {
            const modal = document.createElement('div');
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
            content.style.maxWidth = '900px';
            content.style.width = '80%';
            content.style.maxHeight = '600px';
            content.style.height = '100%';
            content.style.overflow = 'hidden';
            content.style.boxShadow = '0 0 30px rgba(0,0,0,0.7)';
            content.style.position = 'relative';
            content.style.boxSizing = 'border-box';
            content.style.display = 'flex';
            content.style.flexDirection = 'column';

            const iframe = document.createElement('iframe');
            iframe.src = 'https://plugins/Jade/config/html/egg.html';
            iframe.style.width = '100%';
            iframe.style.height = '100%';
            iframe.style.border = 'none';
            iframe.style.flex = '1';
            
            const closeBtn = document.createElement('button');
            closeBtn.style.position = 'absolute';
            closeBtn.style.top = '15px';
            closeBtn.style.right = '15px';
            closeBtn.style.width = '16px';
            closeBtn.style.height = '16px';
            closeBtn.style.backgroundColor = '#3a2842';
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
                this.removeMinimizedButton();
                this.isMinimized = false;
            });

            const minimizeBtn = document.createElement('button');
            minimizeBtn.style.position = 'absolute';
            minimizeBtn.style.top = '15px';
            minimizeBtn.style.right = '36px';
            minimizeBtn.style.width = '16px';
            minimizeBtn.style.height = '16px';
            minimizeBtn.style.backgroundColor = '#423e28';
            minimizeBtn.style.borderRadius = '50%';
            minimizeBtn.style.border = 'none';
            minimizeBtn.style.cursor = 'pointer';
            minimizeBtn.style.display = 'flex';
            minimizeBtn.style.alignItems = 'center';
            minimizeBtn.style.justifyContent = 'center';
            minimizeBtn.style.color = '#000';
            minimizeBtn.style.fontSize = '12px';
            minimizeBtn.style.fontWeight = 'bold';
            
            minimizeBtn.addEventListener('mouseenter', () => {
                minimizeBtn.style.animation = 'ColorUpYellow 0.3s forwards';
            });

            minimizeBtn.addEventListener('mouseleave', () => {
                minimizeBtn.style.animation = 'ColorDownYellow 0.25s forwards';
            });
            
            minimizeBtn.addEventListener('click', () => {
                this.minimizeModal(modal, content);
            });

            content.appendChild(minimizeBtn);
            content.appendChild(closeBtn);
            content.appendChild(iframe);
            modal.appendChild(content);
            document.body.appendChild(modal);

            this.minimizedModal = { modal, content, iframe };

            modal.addEventListener('click', (e) => {
				if (e.target === modal) {
					this.minimizeModal(modal, content);
				}
			});
            
            const handleEscape = (e) => {
				if (e.key === 'Escape') {
					this.minimizeModal(modal, content);
					document.removeEventListener('keydown', handleEscape);
				}
			};
            
            document.addEventListener('keydown', handleEscape);
            
            modal.addEventListener('DOMNodeRemoved', () => {
				document.removeEventListener('keydown', handleEscape);
				this.removeMinimizedButton();
				this.isMinimized = false;
			});
        }

        minimizeModal(modal, content) {
            modal.style.display = 'none';
            this.isMinimized = true;
            
            this.createMinimizedButton();
        }

        createMinimizedButton() {
            this.removeMinimizedButton();
            
            this.minimizedButton = document.createElement('button');
            this.minimizedButton.textContent = 'Resume';
            
            this.minimizedButton.style.position = 'fixed';
            this.minimizedButton.style.bottom = '560px';
            this.minimizedButton.style.right = '310px';
            this.minimizedButton.style.zIndex = '9999';
            this.minimizedButton.style.padding = '6px 6px';
            this.minimizedButton.style.backgroundColor = '#1e292c';
            this.minimizedButton.style.border = '2px solid #81602b';
            this.minimizedButton.style.borderRadius = '4px';
            this.minimizedButton.style.cursor = 'pointer';
            
            this.minimizedButton.style.color = '#cdbe91';
            this.minimizedButton.style.fontFamily = 'var(--font-display)';
            this.minimizedButton.style.fontSize = '10px';
            this.minimizedButton.style.fontWeight = 'bold';
            this.minimizedButton.style.letterSpacing = '1px';
			this.minimizedButton.style.textTransform = 'uppercase';
            
            this.minimizedButton.style.boxShadow = '0 2px 10px rgba(0,0,0,0.3)';
            this.minimizedButton.style.transition = 'all 0.3s ease';
            
            this.minimizedButton.addEventListener('mouseenter', () => {
				this.minimizedButton.style.color = '#f0e6d2';
                this.minimizedButton.style.animation = 'HoverTextShadow 600ms cubic-bezier(0, 0, 0.33, 1) 1 forwards';
            });
            
            this.minimizedButton.addEventListener('mouseleave', () => {
                this.minimizedButton.style.color = '#cdbe91';
            });
            
            this.minimizedButton.addEventListener('click', () => {
                this.restoreModal();
            });
            
            document.body.appendChild(this.minimizedButton);
        }

        removeMinimizedButton() {
            if (this.minimizedButton && this.minimizedButton.parentNode) {
                document.body.removeChild(this.minimizedButton);
                this.minimizedButton = null;
            }
        }

        restoreModal() {
            if (this.minimizedModal && this.minimizedModal.modal) {
                this.minimizedModal.modal.style.display = 'flex';
                this.isMinimized = false;
                
                this.removeMinimizedButton();
            }
        }

        destroy() {
            if (this.observerInterval) {
                clearInterval(this.observerInterval);
            }
            this.removePlayButton();
            this.removeMinimizedButton();
            this.isMinimized = false;
        }
    }

    window.addEventListener("load", () => {
        window.PlayButtonPlugin = new PlayButtonPlugin();
    });

    window.addEventListener("beforeunload", () => {
        if (window.PlayButtonPlugin) {
            window.PlayButtonPlugin.destroy();
        }
    });
})();