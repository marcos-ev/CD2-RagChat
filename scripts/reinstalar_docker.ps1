# Reinstalar Docker Desktop do zero
# Execute como Administrador para garantir

$ErrorActionPreference = "Stop"

Write-Host "=== Reinstalacao Docker Desktop ===" -ForegroundColor Cyan

# 1. Parar Docker e WSL
Write-Host "`n1. Parando WSL e processos Docker..." -ForegroundColor Yellow
Get-Process "Docker Desktop" -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process "com.docker" -ErrorAction SilentlyContinue | Stop-Process -Force
wsl --shutdown 2>$null
Start-Sleep -Seconds 5

# 2. Desinstalar Docker Desktop
Write-Host "`n2. Desinstalando Docker Desktop..." -ForegroundColor Yellow
winget uninstall "Docker Desktop" --silent 2>$null
if ($LASTEXITCODE -ne 0) {
    # Alternativa: usar o instalador
    $installer = "C:\Program Files\Docker\Docker\Docker Desktop Installer.exe"
    if (Test-Path $installer) {
        & $installer uninstall --quiet
    }
}
Start-Sleep -Seconds 5

# 3. Limpar pastas residuais
Write-Host "`n3. Limpando pastas residuais em C:..." -ForegroundColor Yellow
Remove-Item "$env:LOCALAPPDATA\Docker" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item "$env:APPDATA\Docker" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item "$env:APPDATA\Docker Desktop" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item "C:\ProgramData\DockerDesktop" -Recurse -Force -ErrorAction SilentlyContinue

# 4. Limpar E:\DockerData (dados antigos)
Write-Host "`n4. Limpando E:\DockerData..." -ForegroundColor Yellow
Remove-Item "E:\DockerData\*" -Recurse -Force -ErrorAction SilentlyContinue

# 5. Recriar pasta para novo Docker
New-Item -ItemType Directory -Path "E:\DockerData" -Force | Out-Null

# 6. Instalar Docker Desktop
Write-Host "`n5. Instalando Docker Desktop (pode demorar)..." -ForegroundColor Yellow
winget install --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements

Write-Host "`n=== Concluido ===" -ForegroundColor Green
Write-Host "Proximos passos:" -ForegroundColor Cyan
Write-Host "1. Abra o Docker Desktop"
Write-Host "2. Settings > Resources > Advanced > Disk image location = E:\DockerData"
Write-Host "3. Apply and Restart"
Write-Host "4. Depois: cd E:\Rag && docker compose up -d --build"
