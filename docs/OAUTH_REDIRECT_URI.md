# Corrigir Erro 400: redirect_uri_mismatch

Se você vê **"Erro 400: redirect_uri_mismatch"** ou **"Acesso bloqueado: a solicitação desse app é inválida"** ao fazer login com Google OAuth, o callback não está cadastrado corretamente no Google Cloud Console.

## Solução

### 1. Adicione as URIs no Google Cloud Console

1. Acesse [Google Cloud Console](https://console.cloud.google.com/) → **APIs e serviços** → **Credenciais**
2. Clique no **ID do cliente OAuth 2.0** (tipo "Aplicativo da Web")
3. Em **URIs de redirecionamento autorizados**, adicione **todas** as URLs que você pode usar:

   | Ambiente | URI a adicionar |
   |----------|----------------|
   | Local (localhost) | `http://localhost:8000/auth/callback` |
   | Local (127.0.0.1) | `http://127.0.0.1:8000/auth/callback` |
   | Cloudflare Tunnel | `https://seu-subdominio.trycloudflare.com/auth/callback` |
   | Produção | `https://seu-dominio.com/auth/callback` |

4. Em **Origens JavaScript autorizadas** (se aparecer), adicione a origem:
   - `http://localhost:8000`
   - `http://127.0.0.1:8000`

5. **Salve** (clique em SALVAR no rodapé).

### 2. Confira o .env

O `APP_URL` deve ser **exatamente** a URL que você usa no navegador:

```
# Se abre http://localhost:8000
APP_URL=http://localhost:8000

# Se abre http://127.0.0.1:8000
APP_URL=http://127.0.0.1:8000

# Se usa tunnel ou domínio externo
APP_URL=https://seu-subdominio.trycloudflare.com
```

### 3. Reinicie a API

```bash
docker compose restart api
```

**Importante:** A URI no Google Console deve ser **idêntica** à que o app envia (incluindo http/https, porta, sem barra no final).
