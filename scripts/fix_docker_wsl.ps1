# Script para tentar corrigir Docker Desktop + WSL
# Execute como Administrador se necessario

Write-Host "=== Correcao Docker Desktop / WSL ===" -ForegroundColor Cyan
Write-Host ""

Write-Host "1. Encerrando WSL..." -ForegroundColor Yellow
wsl --shutdown 2>$null
Start-Sleep -Seconds 5

Write-Host "2. Verificando atualizacao WSL..." -ForegroundColor Yellow
wsl --update 2>$null

Write-Host ""
Write-Host "3. PROXIMOS PASSOS MANUAIS:" -ForegroundColor Cyan
Write-Host "   - Feche o Docker Desktop completamente" -ForegroundColor White
Write-Host "   - Aguarde 10 segundos" -ForegroundColor White
Write-Host "   - Abra o Docker Desktop novamente" -ForegroundColor White
Write-Host ""
Write-Host "   Depois execute no terminal:" -ForegroundColor Cyan
Write-Host "   cd E:\Rag" -ForegroundColor White
Write-Host "   docker compose up -d --build" -ForegroundColor White
Write-Host "   curl http://localhost:8000/health" -ForegroundColor White
Write-Host "   docker exec rag-ollama ollama pull llama3.2" -ForegroundColor White
