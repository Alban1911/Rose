@echo off
:: Create a single installer package for LoL Skin Changer
:: This script creates a complete installer package that can be distributed

echo.
echo ================================================
echo    Creating LoL Skin Changer Single Installer
echo ================================================
echo.

:: Set package directory
set "PACKAGE_DIR=LoLSkinChanger_SingleInstaller"
set "PACKAGE_ZIP=LoLSkinChanger_SingleInstaller.zip"

:: Create package directory
echo [1/3] Creating package directory...
if exist "%PACKAGE_DIR%" rmdir /s /q "%PACKAGE_DIR%"
mkdir "%PACKAGE_DIR%"

:: Copy installer file
echo [2/3] Copying installer files...
copy "LoLSkinChanger_Installer.bat" "%PACKAGE_DIR%\install.bat"

:: Create package info file
echo [3/3] Creating package info...
(
echo LoL Skin Changer - Single File Installer Package
echo ================================================
echo.
echo This package contains everything needed to install
echo LoL Skin Changer on Windows systems.
echo.
echo Files included:
echo - install.bat (Main installer - USE THIS!)
echo.
echo Installation:
echo 1. Download this ZIP file
echo 2. Extract it to any folder
echo 3. Double-click install.bat
echo 4. Wait for installation to complete
echo 5. Done!
echo.
echo The installer will automatically:
echo - Download and install Python 3.11
echo - Download and install Tesseract OCR
echo - Download and install the LoL Skin Changer application
echo - Install all required dependencies
echo - Create desktop and start menu shortcuts
echo.
echo No user interaction required!
echo.
echo For support, see the application documentation
echo.
echo System Requirements:
echo - Windows 10/11
echo - Internet connection
echo - Administrator privileges (for system components)
) > "%PACKAGE_DIR%\README.txt"

:: Create ZIP package
echo Creating ZIP package...
powershell -Command "& {Compress-Archive -Path '%PACKAGE_DIR%\*' -DestinationPath '%PACKAGE_ZIP%' -Force}"

:: Clean up
rmdir /s /q "%PACKAGE_DIR%"

echo.
echo ================================================
echo    Package Created Successfully!
echo ================================================
echo.
echo Package file: %PACKAGE_ZIP%
echo.
echo This package contains:
echo - Complete installer (install.bat)
echo - Installation instructions (README.txt)
echo.
echo To distribute:
echo 1. Share the %PACKAGE_ZIP% file
echo 2. Users extract it and run install.bat
echo 3. Installation is completely automatic!
echo.
echo The installer will handle everything:
echo - Download Python 3.11
echo - Download Tesseract OCR
echo - Download the application from GitHub
echo - Install all dependencies
echo - Create shortcuts
echo - Set up environment
echo.
echo No user interaction required!
echo.
pause
