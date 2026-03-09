# Restaurar Docker com dados em E:
# Execute como Administrador

Write-Host "1. Parando WSL..." -ForegroundColor Yellow
wsl --shutdown
Start-Sleep -Seconds 5

Write-Host "2. Registrando vhdx existente como docker-desktop-data..." -ForegroundColor Yellow
wsl --import-in-place docker-desktop-data "E:\DockerData\docker_data.vhdx"

if ($LASTEXITCODE -eq 0) {
    Write-Host "OK! Agora abra o Docker Desktop." -ForegroundColor Green
} else {
    Write-Host "Erro. Tentando criar link simbolico como alternativa..." -ForegroundColor Yellow
    New-Item -ItemType SymbolicLink -Path "C:\Users\marco\AppData\Local\Docker\wsl\disk\docker_data.vhdx" -Target "E:\DockerData\docker_data.vhdx" -Force
    Write-Host "Link criado. Abra o Docker Desktop." -ForegroundColor Green
}
