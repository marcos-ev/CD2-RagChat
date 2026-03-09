# Execute como Administrador: botao direito no PowerShell -> "Executar como administrador"

New-Item -ItemType SymbolicLink -Path "C:\Users\marco\AppData\Local\Docker\wsl\disk\docker_data.vhdx" -Target "E:\DockerData\docker_data.vhdx"

Write-Host "Link criado! Pode abrir o Docker Desktop agora." -ForegroundColor Green
