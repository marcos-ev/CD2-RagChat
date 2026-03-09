# Escalabilidade e produção — RAG corporativo

Este documento responde questões práticas sobre escalar a aplicação de MVP para produção com até 50 usuários (5–10 simultâneos no pico) distribuídos pelo Brasil.

## Estratégia LLM adotada

**Cascata**: Groq (1º) → Gemini Flash (2º) → Ollama 7B (3º) — custo zero, velocidade alta e estabilidade.

---

## 1. Ollama: memória, Docker e carga

### Docker resolve o consumo de memória?

**Não.** Docker só isola o processo. O Ollama continua consumindo RAM/VRAM do host. O container não reduz uso de memória.

### Requisitos de memória por modelo

| Modelo | RAM (CPU-only) | VRAM (GPU) | Tokens/seg (referência) |
|-------|----------------|------------|-------------------------|
| Llama 3.2 3B | ~4–8 GB | 3–4 GB | CPU: 7–12; GPU 8GB: 40+ |
| Llama 3.2 8B | ~16 GB | 6–8 GB | CPU: lento; GPU 8GB: 40+ |
| Mistral 7B | ~16 GB | 6–8 GB | Similar ao 8B |
| Llama 3.1 70B | ~48 GB+ | 48 GB+ | Apenas com GPU workstation |

### Concorrência

- **Padrão**: Ollama processa requisições em sequência (fila FIFO).
- **Variáveis**:
  - `OLLAMA_NUM_PARALLEL`: requisições simultâneas por modelo (aumenta uso de memória).
  - `OLLAMA_MAX_QUEUE`: tamanho da fila; acima disso retorna 503 (default: 512).
- Com 2 requisições paralelas, o uso de memória praticamente dobra.

### Configuração para 50 usuários (5–10 concurrent)

| Cenário | Configuração | Observação |
|---------|--------------|------------|
| **APIs ok (normal)** | Groq + Gemini | Resposta 1–5 s |
| **Groq limitado** | Gemini assume | Resposta 2–5 s |
| **Ambos falham (raro)** | Ollama 7B fallback | 40–60 s; serviço continua |
| **Oracle 24 GB** | Postgres + MinIO + API + Ollama 7B | ~14 GB; cabe confortavelmente |

---

## 2. Acesso remoto — equipe distribuída no Brasil

### Contexto

- Até 50 pessoas (suporte + desenvolvedores)
- 5–10 simultâneos no pico
- Diferentes regiões do Brasil
- Acesso via navegador

### Opções de exposição

| Opção | Custo | Complexidade | Segurança | Recomendação |
|-------|-------|--------------|-----------|--------------|
| **Domínio + Nginx + Let's Encrypt** | R$ 0 (domínio próprio) | Média | Alta (HTTPS) | Produção padrão |
| **Cloudflare Tunnel** | R$ 0 | Baixa | Alta | Melhor custo/benefício para começar |
| **ngrok** | R$ 0 (tier free) | Muito baixa | Média | Apenas teste/demonstração |
| **VPN (WireGuard)** | R$ 0 | Média | Muito alta | Quando não pode expor na internet |
| **VM na nuvem** (Oracle Free Tier, etc.) | R$ 0 | Média | Depende da rede | Se não houver servidor on‑prem |

### Fluxo recomendado: Cloudflare Tunnel

```
[Usuário Brasil] --HTTPS--> [Cloudflare Tunnel] --internamente--> [Nginx] --> [FastAPI :8000]
```

- Mantém conexão outbound; não precisa abrir portas nem IP fixo.
- Domínio: ex. `rag.cd2.com.br` apontando para o tunnel.
- Auth: Google OAuth + restrição `@cd2.com.br` restringe a colaboradores.

### Alternativa: servidor com IP público

- Servidor em datacenter ou VM (Oracle Free Tier, Hetzner, etc.).
- Nginx + Certbot (Let's Encrypt) para HTTPS.
- DNS: `rag.cd2.com.br` → IP do servidor.
- Usuários acessam `https://rag.cd2.com.br` de qualquer lugar.

### Latência Brasil

- Servidor em SP: usuários em SP ~10–30 ms; Norte/Nordeste ~50–100 ms.
- Com Groq/Gemini: gargalo é a API (~1–5 s), não a rede. Ollama só no fallback.
- Para chat, 50–100 ms extras são aceitáveis.

---

## 3. Justificativa da substituição completa

### Por que não evoluir o projeto atual?

| Critério | Projeto atual | rag-data-platform | Conclusão |
|----------|---------------|-------------------|-----------|
| Stack de dados | SQLite + Chroma (filesystem) | Postgres + pgvector | Postgres adequado para produção |
| LLM | Groq/Gemini (sem fallback) | Groq → Gemini → Ollama 7B | Velocidade + resiliência, custo zero |
| Ingestão | Script manual + painel síncrono | Worker automático + pasta `./data` | Worker reduz trabalho operacional |
| Deploy | Scripts .bat, sem Compose | Docker Compose | Compose padroniza ambiente |
| Armazenamento de arquivos | Pasta local | MinIO (S3) | MinIO escalável e S3-compatible |
| Complexidade do código | app.py monolítico | API + serviços separados | Manutenção mais simples |
| Modificações necessárias | Reescrever quase tudo | Adicionar auth + chat + chunking | Menor esforço partindo do rag-data-platform |

### Migração incremental vs greenfield

| Abordagem | Esforço | Risco | Resultado |
|-----------|---------|-------|-----------|
| Migração incremental | Alto — adaptadores, refatoração massiva | Médio | Arquitetura híbrida confusa |
| Greenfield (rag-data-platform + add-ons) | Médio — auth, chunking, chat, RBAC | Baixo | Código limpo, responsabilidades claras |

### O que preservar do projeto atual (somente lógica)

| Item | Onde está | Uso no novo projeto |
|------|-----------|---------------------|
| Regras de domínio | auth.py (DOMAIN, RBAC via env) | Portar para FastAPI |
| Lista de roles | ADMIN_EMAILS, PUBLICADOR_EMAILS | Mesmas variáveis de ambiente |
| Fluxo Google OAuth | app.py + Streamlit | Substituir por Authlib no FastAPI |
| Estrutura de conversas | database.py | Adaptar para schema Postgres |

### Motivos da substituição completa

1. **Custo zero + velocidade** — Groq e Gemini free tier; Ollama 7B como fallback garante estabilidade.
2. **Escala** exige Postgres e MinIO; SQLite e Chroma não suportam bem múltiplos usuários.
3. **Manutenção** é mais simples com base limpa do que com migração incremental.
4. **Deploy** padronizado com Docker Compose reduz erro de ambiente.

---

## 4. Checklist: MVP → produção (50 usuários, 5–10 concurrent)

- [ ] Conta Oracle Free Tier — VM Ampere 24 GB, região São Paulo.
- [ ] API keys: Groq, Google AI (Gemini Flash).
- [ ] Refatorar rag_service: cascata Groq → Gemini → Ollama.
- [ ] Configurar acesso: Cloudflare Tunnel ou domínio + Nginx + Let's Encrypt.
- [ ] Testar cascata: simular rate limit e validar fallback.
- [ ] Documentar URL e fluxo de login para a equipe.
