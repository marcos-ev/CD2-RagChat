# Script para subir ambiente e validar
# Execute quando o Docker Desktop estiver rodando

$ErrorActionPreference = "Stop"
Set-Location "E:\Rag"

Write-Host "=== Subindo ambiente RAG ===" -ForegroundColor Cyan
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host ""
Write-Host "Aguardando servicos (30s)..." -ForegroundColor Yellow
Start-Sleep -Seconds 30

Write-Host ""
Write-Host "=== Health check ===" -ForegroundColor Cyan
$health = curl -s http://localhost:8000/health 2>$null
Write-Host $health
if ($health -match "healthy") {
    Write-Host "API OK!" -ForegroundColor Green
} else {
    Write-Host "Aguarde mais - API pode ainda estar carregando embeddings." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== Baixando modelo Ollama llama3.2 ===" -ForegroundColor Cyan
docker exec rag-ollama ollama pull llama3.2

Write-Host ""
Write-Host "=== Concluido ===" -ForegroundColor Green
Write-Host "API: http://localhost:8000" -ForegroundColor White
Write-Host "Open WebUI: http://localhost:3000" -ForegroundColor White
