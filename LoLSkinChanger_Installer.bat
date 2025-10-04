@echo off
setlocal enabledelayedexpansion

:: LoL Skin Changer - Single File Installer
:: This installer downloads and installs everything automatically

echo.
echo ================================================
echo    LoL Skin Changer - Installer
echo ================================================
echo.
echo This installer will automatically download and install:
echo - Python 3.11 (if not already installed)
echo - Tesseract OCR
echo - LoL Skin Changer application
echo - All required dependencies
echo.
echo Please wait while the installation proceeds...
echo.

:: Set installation directory
set "INSTALL_DIR=%LOCALAPPDATA%\LoLSkinChanger"
set "TESSERACT_DIR=%PROGRAMFILES%\Tesseract-OCR"

:: Create installation directory
echo [1/6] Creating installation directory...
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

:: Check if Python is already installed
echo [2/6] Checking Python installation...
python --version >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo Python is already installed.
    set "PYTHON_CMD=python"
    set "PIP_CMD=pip"
) else (
    echo Python not found. Downloading Python 3.11...
    
    :: Download Python 3.11 installer
    echo Downloading Python 3.11 installer...
    powershell -Command "& {Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe' -OutFile '%TEMP%\python-installer.exe'}"
    
    if not exist "%TEMP%\python-installer.exe" (
        echo [ERROR] Failed to download Python installer.
        echo Please check your internet connection and try again.
        pause
        exit /b 1
    )
    
    :: Install Python silently
    echo Installing Python 3.11...
    "%TEMP%\python-installer.exe" /quiet InstallAllUsers=1 PrependPath=1 Include_test=0
    
    :: Wait for installation to complete
    timeout /t 15 /nobreak >nul
    
    :: Clean up installer
    del "%TEMP%\python-installer.exe"
    
    :: Set Python commands
    set "PYTHON_CMD=python"
    set "PIP_CMD=pip"
)

:: Verify Python installation
echo Verifying Python installation...
%PYTHON_CMD% --version
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python installation failed.
    pause
    exit /b 1
)

:: Check if Tesseract is already installed
echo [3/6] Checking Tesseract OCR installation...
if exist "%TESSERACT_DIR%\tesseract.exe" (
    echo Tesseract OCR is already installed.
) else (
    echo Tesseract OCR not found. Downloading and installing...
    
    :: Download Tesseract installer
    echo Downloading Tesseract OCR installer...
    powershell -Command "& {Invoke-WebRequest -Uri 'https://github.com/UB-Mannheim/tesseract/releases/download/v5.3.3.20231005/tesseract-ocr-w64-setup-5.3.3.20231005.exe' -OutFile '%TEMP%\tesseract-installer.exe'}"
    
    if not exist "%TEMP%\tesseract-installer.exe" (
        echo [ERROR] Failed to download Tesseract installer.
        echo Please check your internet connection and try again.
        pause
        exit /b 1
    )
    
    :: Install Tesseract silently
    echo Installing Tesseract OCR...
    "%TEMP%\tesseract-installer.exe" /S /D=%TESSERACT_DIR%
    
    :: Wait for installation to complete
    timeout /t 15 /nobreak >nul
    
    :: Clean up installer
    del "%TEMP%\tesseract-installer.exe"
)

:: Verify Tesseract installation
echo Verifying Tesseract installation...
"%TESSERACT_DIR%\tesseract.exe" --version
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Tesseract installation failed.
    pause
    exit /b 1
)

:: Download and install the application
echo [4/6] Downloading LoL Skin Changer application...
set "APP_ZIP=%TEMP%\LoLSkinChanger.zip"

:: Download the application from GitHub
echo Downloading application files...
:: Note: Replace 'your-username' with your actual GitHub username
powershell -Command "& {Invoke-WebRequest -Uri 'https://github.com/your-username/LoLSkinChanger/archive/main.zip' -OutFile '%APP_ZIP%'}"

if not exist "%APP_ZIP%" (
    echo [ERROR] Failed to download application.
    echo Please check your internet connection and try again.
    pause
    exit /b 1
)

:: Extract the application
echo Extracting application files...
powershell -Command "& {Expand-Archive -Path '%APP_ZIP%' -DestinationPath '%TEMP%' -Force}"

:: Copy files to installation directory
echo Installing application files...
xcopy "%TEMP%\LoLSkinChanger-main\*" "%INSTALL_DIR%\" /E /H /Y >nul

:: Clean up
del "%APP_ZIP%"
rmdir /s /q "%TEMP%\LoLSkinChanger-main"

:: Verify installation
if not exist "%INSTALL_DIR%\main.py" (
    echo [ERROR] Failed to install application files.
    pause
    exit /b 1
)

:: Install Python dependencies
echo [5/6] Installing Python dependencies...
cd /d "%INSTALL_DIR%"

:: Upgrade pip first
%PYTHON_CMD% -m pip install --upgrade pip

:: Install dependencies
%PIP_CMD% install -r requirements.txt

if %ERRORLEVEL% NEQ 0 (
    echo [WARNING] Some dependencies may have failed to install.
    echo The application may still work, but some features might be limited.
)

:: Create desktop shortcut
echo [6/6] Creating shortcuts...
set "DESKTOP=%USERPROFILE%\Desktop"
set "SHORTCUT_PATH=%DESKTOP%\LoL Skin Changer.lnk"

:: Create VBS script to create shortcut
echo Set oWS = WScript.CreateObject("WScript.Shell") > "%TEMP%\CreateShortcut.vbs"
echo sLinkFile = "%SHORTCUT_PATH%" >> "%TEMP%\CreateShortcut.vbs"
echo Set oLink = oWS.CreateShortcut(sLinkFile) >> "%TEMP%\CreateShortcut.vbs"
echo oLink.TargetPath = "%PYTHON_CMD%" >> "%TEMP%\CreateShortcut.vbs"
echo oLink.Arguments = ""%INSTALL_DIR%\main.py"" >> "%TEMP%\CreateShortcut.vbs"
echo oLink.WorkingDirectory = "%INSTALL_DIR%" >> "%TEMP%\CreateShortcut.vbs"
echo oLink.Description = "LoL Skin Changer" >> "%TEMP%\CreateShortcut.vbs"
echo oLink.IconLocation = ""%INSTALL_DIR%\icon.ico"" >> "%TEMP%\CreateShortcut.vbs"
echo oLink.Save >> "%TEMP%\CreateShortcut.vbs"

cscript "%TEMP%\CreateShortcut.vbs" >nul
del "%TEMP%\CreateShortcut.vbs"

:: Create start menu entry
set "START_MENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs"
if not exist "%START_MENU%\LoL Skin Changer" mkdir "%START_MENU%\LoL Skin Changer"

:: Create start menu shortcut
echo Set oWS = WScript.CreateObject("WScript.Shell") > "%TEMP%\CreateStartMenuShortcut.vbs"
echo sLinkFile = "%START_MENU%\LoL Skin Changer\LoL Skin Changer.lnk" >> "%TEMP%\CreateStartMenuShortcut.vbs"
echo Set oLink = oWS.CreateShortcut(sLinkFile) >> "%TEMP%\CreateStartMenuShortcut.vbs"
echo oLink.TargetPath = "%PYTHON_CMD%" >> "%TEMP%\CreateStartMenuShortcut.vbs"
echo oLink.Arguments = ""%INSTALL_DIR%\main.py"" >> "%TEMP%\CreateStartMenuShortcut.vbs"
echo oLink.WorkingDirectory = "%INSTALL_DIR%" >> "%TEMP%\CreateStartMenuShortcut.vbs"
echo oLink.Description = "LoL Skin Changer" >> "%TEMP%\CreateStartMenuShortcut.vbs"
echo oLink.IconLocation = ""%INSTALL_DIR%\icon.ico"" >> "%TEMP%\CreateStartMenuShortcut.vbs"
echo oLink.Save >> "%TEMP%\CreateStartMenuShortcut.vbs"

cscript "%TEMP%\CreateStartMenuShortcut.vbs" >nul
del "%TEMP%\CreateStartMenuShortcut.vbs"

:: Create uninstaller
(
echo @echo off
echo echo Uninstalling LoL Skin Changer...
echo echo.
echo echo This will remove:
echo echo - LoL Skin Changer application files
echo echo - Desktop shortcut
echo echo - Start menu entry
echo echo.
echo echo Python and Tesseract OCR will NOT be removed.
echo echo.
echo pause
echo.
echo echo Removing application files...
echo if exist "%INSTALL_DIR%" rmdir /s /q "%INSTALL_DIR%"
echo.
echo echo Removing shortcuts...
echo if exist "%SHORTCUT_PATH%" del "%SHORTCUT_PATH%"
echo if exist "%START_MENU%\LoL Skin Changer" rmdir /s /q "%START_MENU%\LoL Skin Changer"
echo.
echo echo Uninstallation complete!
echo pause
) > "%INSTALL_DIR%\uninstall.bat"

:: Set environment variables
echo Setting up environment variables...
setx TESSERACT_CMD "%TESSERACT_DIR%\tesseract.exe" >nul 2>&1
setx TESSDATA_PREFIX "%TESSERACT_DIR%\tessdata" >nul 2>&1

:: Installation complete
echo.
echo ================================================
echo    Installation Complete!
echo ================================================
echo.
echo LoL Skin Changer has been successfully installed!
echo.
echo Installation location: %INSTALL_DIR%
echo.
echo You can now:
echo 1. Double-click the desktop shortcut to start the application
echo 2. Or use the Start Menu entry
echo.
echo To uninstall, run: %INSTALL_DIR%\uninstall.bat
echo.
echo The application will automatically:
echo - Connect to League of Legends
echo - Detect skins during champion select
echo - Inject skins before the game starts
echo.
echo Enjoy your custom skins!
echo.
pause
