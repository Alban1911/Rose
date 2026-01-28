Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "   ROSE BUILD SCRIPT                      "      -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

Write-Host "`n[1/5] Cleaning old build folders..."
if (Test-Path "dist") { Remove-Item "dist" -Recurse -Force }
if (Test-Path "build") { Remove-Item "build" -Recurse -Force }

Write-Host "`n[2/5] Compiling with Nuitka (This may take a while)..."
python -m nuitka --standalone --mingw64 `
     --enable-plugin=tk-inter `
     --windows-console-mode=disable `
     --include-package=websockets `
     --include-data-dir=assets=assets `
     --include-data-dir="Pengu Loader"="Pengu Loader" `
     --windows-icon-from-ico=assets/icon.ico `
     --company-name="Rose" `
     --product-name="Rose" `
     --file-description="Rose - Effortless Skin Changer" `
     --product-version=1.0.0.0 `
     --output-dir=dist `
     main.py

if (-not (Test-Path "dist/main.dist/main.exe")) {
    Write-Host "Error: Nuitka compilation failed." -ForegroundColor Red
    exit
}

Write-Host "`n[3/5] Preparing folder structure..."
Rename-Item -Path "dist/main.dist" -NewName "Rose"
Rename-Item -Path "dist/Rose/main.exe" -NewName "Rose.exe"

Write-Host "`n[4/5] Copying Injection Tools & DLLs..."

New-Item -ItemType Directory -Force -Path "dist/Rose/injection" | Out-Null
Copy-Item -Path "injection\*" -Destination "dist/Rose/injection" -Recurse -Force

New-Item -ItemType Directory -Force -Path "dist/Rose/Pengu Loader" | Out-Null
Copy-Item -Path "Pengu Loader\*" -Destination "dist/Rose/Pengu Loader" -Recurse -Force

Write-Host "`n[5/5] Generating Installer..."
python create_installer.py

Write-Host "`nDone! Check the 'installer' folder." -ForegroundColor Green