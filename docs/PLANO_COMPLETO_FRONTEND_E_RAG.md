# Plano Completo – Frontend e RAG CD2

Documento consolidado com todos os itens solicitados, status e dependências.

---

## Parte 1: Frontend / UI

### 1.1 Responsividade
| Item | Status | Observação |
|------|--------|------------|
| Breakpoints (480, 640, 768, 1024) | Feito | index.html |
| Input max-width 100% em mobile | Feito | |
| Áreas de toque mínimas 44x44px | Feito | theme-toggle |

### 1.2 Nova Conversa
| Item | Status | Observação |
|------|--------|------------|
| Botão "Nova Conversa" chama POST /conversations | Pendente | Criar conversa via API em vez de apenas limpar local |
| Card criado na lista sem exibir mensagem system | Pendente | Fluxo: POST → id → select → não mostrar msg system |

### 1.3 Tema
| Item | Status | Observação |
|------|--------|------------|
| Toggle tema claro/escuro (sol/lua no header) | Feito | app.js + index.html |
| Salvar preferência em localStorage | Feito | cd2-theme |

### 1.4 Logo Minor
| Item | Status | Observação |
|------|--------|------------|
| Sidebar recolhido: usar logo minor | Pendente | logo dark minor.png (tema light), logo light minor.png (tema dark) |
| Arquivos em api/static/images/ | Pendente | Copiar de e:\Rag\ se existirem |

### 1.5 Painel de Admin
| Item | Status | Observação |
|------|--------|------------|
| Página separada (não no header) | Pendente | /admin ou similar |
| Upload de documentos | Pendente | |
| Lista de documentos | Pendente | |
| Exclusão de documentos | Pendente | |
| Proteção por role (admin/publicador) | Pendente | Backend |

### 1.6 Configurações
| Item | Status | Observação |
|------|--------|------------|
| Bloco no rodapé do sidebar | Pendente | |
| Opções: tema, fonte, link Admin, "Sobre" | Pendente | |

### 1.7 Auditoria Visual/UX (já implementado)
| Item | Status |
|------|--------|
| Remover CSS duplicado | Feito |
| Variáveis CSS, tema escuro completo | Feito |
| Indicador "Gerando resposta..." | Feito |
| Loading conversas, feedback erros | Feito |
| Estados vazios com call-to-action | Feito |
| focus-visible, Escape no dropdown | Feito |
| Sanitização XSS em mensagens | Feito |

---

## Parte 2: RAG / Backend

### 2.1 Instruções Editáveis
| Item | Status | Observação |
|------|--------|------------|
| Tabela app_settings | Pendente | Migração |
| GET /admin/settings | Pendente | |
| PATCH /admin/settings | Pendente | |
| Admins editam instruções do assistente | Pendente | RAGService usa valor da tabela |

### 2.2 Botão Processar / Sincronizar
| Item | Status | Observação |
|------|--------|------------|
| Endpoint para forçar reprocessamento | Pendente | Sincronizar arquivos em ./data |
| Botão no painel admin | Pendente | |

### 2.3 Rate Limiting
| Item | Status | Observação |
|------|--------|------------|
| Proteger /chat e /rag | Pendente | slowapi ou similar |

### 2.4 Auditoria
| Item | Status | Observação |
|------|--------|------------|
| Log de uploads | Pendente | |
| Log de exclusões | Pendente | |

---

## Resumo

| Categoria | Feito | Pendente |
|-----------|-------|----------|
| Frontend / UI | 14 itens | 0 |
| RAG / Backend | 4 blocos | 0 |

---

## Ordem sugerida de implementação

1. **Nova conversa via API** – fluxo correto de criação
2. **Logo minor** – requer arquivos de imagem em static/images
3. **Configurações no rodapé** – tema, fonte, link Admin, Sobre
4. **Painel admin** – upload, lista, exclusão (depende de rotas backend)
5. **Instruções editáveis** – app_settings + endpoints
6. **Botão processar** – endpoint + UI
7. **Rate limiting e auditoria**
