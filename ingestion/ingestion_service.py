"""
Serviço de ingestão de documentos
Monitora diretório e processa novos arquivos automaticamente
"""

import os
import time
import requests
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from dotenv import load_dotenv

# Carregar variáveis de ambiente
load_dotenv()

# Configurações
API_URL = os.getenv("API_URL", "http://api:8000")
WATCH_DIRECTORY = os.getenv("WATCH_DIRECTORY", "/data")
SUPPORTED_EXTENSIONS = {'.txt', '.md', '.pdf', '.docx'}


class DocumentHandler(FileSystemEventHandler):
    """Handler para eventos do sistema de arquivos"""
    
    def __init__(self, api_url: str):
        self.api_url = api_url
        self.processed_files = set()
    
    def on_created(self, event):
        """Chamado quando um arquivo é criado"""
        if event.is_directory:
            return
        
        file_path = Path(event.src_path)
        
        # Verificar extensão
        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            print(f"Arquivo ignorado (extensão não suportada): {file_path.name}")
            return
        
        # Aguardar um pouco para garantir que o arquivo está completamente escrito
        time.sleep(2)
        
        # Processar arquivo
        self.process_file(file_path)
    
    def process_file(self, file_path: Path):
        """Processar arquivo enviando para API"""
        # Verificar se já foi processado
        file_id = f"{file_path.name}_{file_path.stat().st_mtime}"
        if file_id in self.processed_files:
            print(f"Arquivo já processado: {file_path.name}")
            return
        
        try:
            print(f"Processando arquivo: {file_path.name}")
            
            # Ler arquivo
            with open(file_path, 'rb') as f:
                file_content = f.read()
            
            # Enviar para API (endpoint interno - sem auth, rede Docker)
            files = {'file': (file_path.name, file_content)}
            response = requests.post(
                f"{self.api_url}/internal/upload",
                files=files,
                timeout=60
            )
            
            if response.status_code == 201:
                result = response.json()
                print(f"✓ Arquivo processado com sucesso: {file_path.name}")
                print(f"  Document ID: {result.get('document_id')}")
                self.processed_files.add(file_id)
            else:
                print(f"✗ Erro ao processar {file_path.name}: {response.status_code}")
                print(f"  Resposta: {response.text}")
        
        except Exception as e:
            print(f"✗ Erro ao processar {file_path.name}: {str(e)}")


def wait_for_api(api_url: str, max_attempts: int = 30):
    """Aguarda a API estar pronta (leva ~1-2 min para carregar modelo)."""
    import urllib.request
    for i in range(max_attempts):
        try:
            req = urllib.request.Request(f"{api_url}/health", method="GET")
            with urllib.request.urlopen(req, timeout=5) as _:
                print("API pronta.")
                return True
        except Exception:
            if (i + 1) % 5 == 0:
                print(f"Aguardando API... tentativa {i + 1}/{max_attempts}")
            time.sleep(10)
    print("AVISO: API não respondeu. Pulando processamento inicial.")
    return False


def process_existing_files(directory: Path, handler: DocumentHandler):
    """Processar arquivos existentes no diretório"""
    print(f"Verificando arquivos existentes em: {directory}")
    
    for file_path in directory.rglob('*'):
        if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
            handler.process_file(file_path)


def main():
    """Função principal"""
    print("=" * 60)
    print("Serviço de Ingestão de Documentos - RAG Data Platform")
    print("=" * 60)
    print(f"API URL: {API_URL}")
    print(f"Diretório monitorado: {WATCH_DIRECTORY}")
    print(f"Extensões suportadas: {SUPPORTED_EXTENSIONS}")
    print("=" * 60)
    
    # Criar diretório se não existir
    watch_path = Path(WATCH_DIRECTORY)
    watch_path.mkdir(parents=True, exist_ok=True)
    
    # Criar handler e observer
    handler = DocumentHandler(API_URL)
    observer = Observer()
    observer.schedule(handler, str(watch_path), recursive=True)
    
    # Aguardar API e disparar sincronização (API processa /data)
    print("\nAguardando API ficar pronta...")
    if wait_for_api(API_URL):
        try:
            print("Disparando sincronização em /internal/sync...")
            r = requests.post(f"{API_URL}/internal/sync", timeout=600)
            data = r.json() if r.status_code == 200 else {}
            print(f"Sincronização: {data.get('message', r.text)}")
        except Exception as e:
            print(f"Falling back para processamento local: {e}")
            process_existing_files(watch_path, handler)
    
    # Iniciar monitoramento
    observer.start()
    print(f"\n✓ Monitoramento iniciado em: {watch_path}")
    print("Aguardando novos arquivos...\n")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\nParando serviço de ingestão...")
        observer.stop()
    
    observer.join()
    print("Serviço de ingestão finalizado.")


if __name__ == "__main__":
    main()

