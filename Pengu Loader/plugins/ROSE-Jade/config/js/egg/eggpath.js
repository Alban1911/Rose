(() => {
    let challengesButtonCreated = false;
    let modalCreated = false;

    const observeProfileOverview = () => {
        const observer = new MutationObserver((mutations) => {
            for (const mutation of mutations) {
                for (const node of mutation.addedNodes) {
                    if (node.nodeType === Node.ELEMENT_NODE) {
                        if (node.classList && node.classList.contains('style-profile-overview-content')) {
                            console.log("Sometimes, it only takes 5 letters to become immortal.");
                        }
                        
                        const profileOverview = node.querySelector?.('.style-profile-overview-content');
                        if (profileOverview) {
                            console.log("Sometimes, it only takes 5 letters to become immortal.");
                        }
                    }
                }
            }
        });

        observer.observe(document.body, {
            childList: true,
            subtree: true
        });

        const existingProfileOverview = document.querySelector('.style-profile-overview-content');
        if (existingProfileOverview) {
            console.log("Sometimes, it only takes 5 letters to become immortal.");
        }
    };

    const createChallengesButton = () => {
        const observer = new MutationObserver((mutations) => {
            for (const mutation of mutations) {
                for (const node of mutation.addedNodes) {
                    if (node.nodeType === Node.ELEMENT_NODE) {
                        if (node.classList && node.classList.contains('challenges-grid')) {
                            addButtonToChallengesGrid(node);
                        }
                        
                        const challengesGrid = node.querySelector?.('.challenges-grid');
                        if (challengesGrid && !challengesGrid.querySelector('.easter-egg-button')) {
                            addButtonToChallengesGrid(challengesGrid);
                        }
                    }
                }
            }
        });

        observer.observe(document.body, {
            childList: true,
            subtree: true
        });

        const existingChallengesGrid = document.querySelector('.challenges-grid');
        if (existingChallengesGrid && !existingChallengesGrid.querySelector('.easter-egg-button')) {
            addButtonToChallengesGrid(existingChallengesGrid);
        }
    };

    const addButtonToChallengesGrid = (challengesGrid) => {
        if (challengesButtonCreated) return;

        const button = document.createElement('button');
        button.className = 'easter-egg-button';
        
        const img = document.createElement('img');
        img.src = '/fe/lol-uikit/images/icon_settings.png';
        img.style.width = '15px';
        img.style.height = '15px';
        img.style.display = 'block';
        
        button.appendChild(img);
        button.style.position = 'absolute';
        button.style.top = '10px';
        button.style.right = '10px';
        button.style.zIndex = '9999';
        button.style.padding = '5px';
        button.style.backgroundColor = '#1e292c';
        button.style.border = '2px solid #81602b';
        button.style.borderRadius = '50%';
        button.style.cursor = 'pointer';
        button.style.width = '20px';
        button.style.height = '20px';
        button.style.display = 'flex';
        button.style.alignItems = 'center';
        button.style.justifyContent = 'center';
        button.style.boxShadow = '0 2px 10px rgba(0,0,0,0.3)';
        button.style.transition = 'all 0.3s ease';
        
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

        button.addEventListener('click', () => {
            openPasswordModal();
        });

        challengesGrid.style.position = 'relative';
        challengesGrid.appendChild(button);
        challengesButtonCreated = true;
    };

    const openPasswordModal = () => {
        if (modalCreated) return;

        const MODAL_ID = "easter-egg-password-modal";

        document.getElementById(MODAL_ID)?.remove();

        const modal = document.createElement('div');
        modal.id = MODAL_ID;
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
        signature.style.color = '#543a60';
        signature.style.fontSize = '9px';
        signature.style.fontWeight = 'bold';
        signature.style.fontFamily = 'Montserrat, sans-serif';
        signature.style.textAlign = 'right';
        signature.style.padding = '5px';
        signature.style.zIndex = '10001';
        signature.style.pointerEvents = 'none';
        signature.textContent = 'by @kyewyve';
        modal.appendChild(signature);
        
        const content = document.createElement('div');
        content.style.backgroundColor = '#131312';
        content.style.padding = '30px';
        content.style.borderRadius = '15px';
        content.style.maxWidth = '500px';
        content.style.width = '90%';
        content.style.maxHeight = '400px';
        content.style.overflow = 'hidden';
        content.style.boxShadow = '0 0 30px rgba(0,0,0,0.7)';
        content.style.position = 'relative';
        content.style.boxSizing = 'border-box';
        content.style.display = 'flex';
        content.style.flexDirection = 'column';

        const logoUrl = 'https://plugins/Jade/config/img/logo.png';
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
            content.appendChild(logoBackground);
        };
        testImg.src = logoUrl;

        const title = document.createElement('h2');
        title.textContent = ' ';
        title.style.margin = '0 0 20px 0';
        title.style.textAlign = 'center';
        title.style.color = '#856ec8';
        title.style.fontSize = '24px';
        title.style.fontFamily = 'Beaufort for LOL, Arial, sans-serif';
        title.style.zIndex = '1';

        const description = document.createElement('p');
        description.textContent = 'Sometimes, it only takes 5 letters to become immortal';
        description.style.margin = '0 0 20px 0';
        description.style.textAlign = 'center';
        description.style.color = '#5f5969';
        description.style.fontSize = '14px';
        description.style.fontFamily = 'Beaufort for LOL, Arial, sans-serif';
        description.style.zIndex = '1';

        const passwordInput = document.createElement('input');
        passwordInput.type = 'password';
        passwordInput.placeholder = '...';
        passwordInput.style.cssText = `
            width: 100%;
            padding: 12px;
            margin: 10px 0;
            background: #010a13;
            border: 1px solid #5f5969;
            border-radius: 4px;
            color: #f0e6d2;
            font-size: 16px;
            outline: none;
            font-family: inherit;
            z-index: 1;
            box-sizing: border-box;
        `;

        const messageElement = document.createElement('p');
        messageElement.className = 'easter-egg-message';
        messageElement.style.cssText = `
            margin: 10px 0;
            min-height: 20px;
            color: #cdbe91;
            font-size: 12px;
            text-align: center;
            z-index: 1;
        `;

        const buttonContainer = document.createElement('div');
        buttonContainer.style.cssText = `
            display: flex;
            gap: 10px;
            margin-top: 20px;
            z-index: 1;
        `;

        const submitButton = document.createElement('button');
        submitButton.textContent = ' ';
        submitButton.style.cssText = `
            flex: 1;
            padding: 12px;
            background: linear-gradient(135deg, #5f5969, #3a2842);
            border: none;
            border-radius: 4px;
            color: #f0d5fc;
            font-weight: bold;
            cursor: pointer;
            font-size: 14px;
            font-family: inherit;
        `;

        const closeBtn = document.createElement('button');
        closeBtn.style.cssText = `
            position: absolute;
            top: 15px;
            right: 15px;
            width: 16px;
            height: 16px;
            background-color: #3a2842;
            border-radius: '50%';
            border: none;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 1;
        `;
        
        closeBtn.addEventListener('mouseenter', () => {
            closeBtn.style.animation = 'ColorUp 0.3s forwards';
        });

        closeBtn.addEventListener('mouseleave', () => {
            closeBtn.style.animation = 'ColorDown 0.25s forwards';
        });
        
        closeBtn.addEventListener('click', () => {
            document.body.removeChild(modal);
            modalCreated = false;
        });

        buttonContainer.appendChild(submitButton);
        
        content.appendChild(closeBtn);
        content.appendChild(title);
        content.appendChild(description);
        content.appendChild(passwordInput);
        content.appendChild(messageElement);
        content.appendChild(buttonContainer);
        
        modal.appendChild(content);
        document.body.appendChild(modal);
        modalCreated = true;

        passwordInput.focus();

        const checkPassword = async () => {
            const password = passwordInput.value.trim();
            if (password === 'IDDQD') {
                messageElement.textContent = 'Immortal...';
                messageElement.style.color = '#0acb6a';
                
                await window.DataStore.set('Jade-easter-egg-unlocked', 'true');
                loadEggPlugin();
                
                setTimeout(() => {
                    document.body.removeChild(modal);
                    modalCreated = false;
                }, 2000);
            } else {
                messageElement.textContent = 'Incorrect';
                messageElement.style.color = '#cd5c5c';
                passwordInput.value = '';
                passwordInput.focus();
            }
        };

        const closeModal = () => {
            document.body.removeChild(modal);
            modalCreated = false;
        };

        submitButton.addEventListener('click', checkPassword);
        
        passwordInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                checkPassword();
            }
        });

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
    };

    const loadEggPlugin = async () => {
        try {
            const eggModule = await import('https://plugins/Jade/config/js/egg/egg.js');
            
            if (eggModule.default) {
                new eggModule.default();
            } else if (typeof eggModule === 'function') {
                new eggModule();
            } else if (eggModule.init) {
                eggModule.init();
            }
        } catch (error) {}
    };

    const checkIfUnlocked = async () => {
        try {
            const isUnlocked = await window.DataStore.get('Jade-easter-egg-unlocked');
            if (isUnlocked === 'true') {
                loadEggPlugin();
            }
        } catch (error) {}
    };

    const init = () => {
        observeProfileOverview();
        createChallengesButton();
        checkIfUnlocked();
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    window.EasterEggPath = {
        init,
        openPasswordModal,
        loadEggPlugin
    };
})();