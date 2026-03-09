# Auditoria Visual e UX – Frontend RAG CD2

Documento de auditoria completa da interface do ChatGPT interno CD2, cobrindo design visual, experiência do usuário, acessibilidade e qualidade do código.

---

## 1. Design Visual

### 1.1 Pontos Positivos

- Paleta de cores consistente com variáveis CSS (`--accent`, `--text`, `--border`)
- Logo CD2 no sidebar com suporte a modo claro/escuro via `prefers-color-scheme`
- Sidebar colapsável com transição suave
- Ícones SVG inline, sem dependências externas
- Hierarquia visual clara (botão Nova Conversa em destaque vermelho)

### 1.2 Problemas Encontrados

| Item | Local | Descrição |
|------|-------|-----------|
| CSS duplicado | index.html ~275-290 | `.main-header` declarado duas vezes com propriedades redundantes |
| Cor hardcoded | .input-area, .btn-clear, .conv-list | `background: white` e `#f3f4f6` em vez de variáveis; quebra em dark mode |
| Tema escuro incompleto | body | Existe `body.dark-mode` para logos, mas não há variáveis CSS para dark mode em `:root` |
| user-guest/user-logged | index.html | Usam `display:none` e `display:flex` inline; `user-guest` precisa `display:flex` quando visível |
| .conv-dropdown | conversações | `background: white` fixo; em dark mode não acompanha |
| Conv-list background | .conv-list | `background: white` – não usa `var(--panel)` ou `var(--bg)` |

### 1.3 Recomendações

- Consolidar `.main-header` em uma única regra
- Substituir `white`, `#f3f4f6` por `var(--bg)`, `var(--panel)` ou novas variáveis
- Implementar bloco `body.dark-mode { ... }` com override de variáveis (--bg, --text, --border etc.)
- Garantir que dropdown e listas usem variáveis de fundo

---

## 2. Experiência do Usuário (UX)

### 2.1 Estados de Carregamento

| Elemento | Estado Atual | Recomendação |
|----------|--------------|--------------|
| Envio de mensagem | Botão desabilitado; mensagem some da tela e reaparece | Adicionar skeleton ou indicador "Gerando resposta..." na bolha do assistente |
| Verificação de login | "Verificando login..." em texto | Spinner leve ou skeleton no header |
| Carregar conversas | Lista vazia → "Carregando..." implícito | Estado explícito de loading na lista |
| Carregar mensagens ao trocar conversa | Transição abrupta | Skeleton ou fade para evitar "flash" |

### 2.2 Feedback de Erros

| Situação | Estado Atual | Melhoria |
|----------|--------------|----------|
| Erro de rede ao enviar | Mensagem system em amarelo com texto | Manter consistência; considerar toast não intrusivo |
| Erro ao renomear | Apenas `console.warn` | Mostrar feedback ao usuário (toast ou inline) |
| Erro ao reordenar | Apenas `console.warn` | Idem |
| Falha no login | Redireciona para guest sem explicar | Mensagem breve: "Falha ao verificar login" |

### 2.3 Estados Vazios

| Contexto | Estado Atual | Sugestão |
|----------|--------------|----------|
| Sem conversas | "Nenhuma conversa ainda." | Incluir call-to-action: "Clique em Nova Conversa para começar" |
| Chat sem mensagens | Mensagem system genérica | Manter; garantir que não suma ao trocar de conversa |
| Modo anônimo | Badge "Modo anônimo" | Deixar claro que conversas não são salvas |

### 2.4 Interações

| Interação | Observação |
|-----------|------------|
| Textarea | `rows="2"` – ok; falta `maxlength` ou aviso se houver limite no backend |
| Enter para enviar | Funciona; Shift+Enter para quebra documentado |
| Dropdown 3 pontos | Pode cortar na borda inferior do conv-list (overflow) |
| Drag para reordenar | Handle (≡) pouco óbvio; considerar dica visual no hover |
| Renomear inline | Blur e Enter salvam; Escape cancela – correto |
| Confirm excluir | `window.confirm` – funcional mas pouco alinhado ao restante da UI |

### 2.5 Acessibilidade Mínima

| Item | Status |
|------|--------|
| aria-label no toggle sidebar | OK – `aria-label="Recolher painel"` |
| title nos botões | OK – toggle, envio, opções |
| Foco após enviar | `inputEl.focus()` – OK |
| Contraste de texto | Texto escuro em fundo claro – adequado |
| Foco visível | Não há `:focus-visible` ou `outline` customizado em botões/links |
| Navegação por teclado | Dropdown e conv-item sem suporte a teclado (Tab, Enter, Escape) |

---

## 3. Responsividade

### 3.1 Breakpoints

- Único breakpoint: `768px`
- Entre 768px e 1024px o layout pode ficar apertado
- `max-width: 1400px` no `.app` – em telas grandes deixa faixas vazias nas laterais
- `max-width: 800px` no `.input-row` – centraliza o input; ok para desktop

### 3.2 Problemas em Mobile

| Problema | Descrição |
|----------|-----------|
| Sidebar em mobile | `flex-direction: column` – sidebar inteiro antes do chat; pode ocupar muita altura |
| Toggle escondido | `display: none` no mobile – usuário não pode recolher sidebar |
| Conv-list | `max-height: 160px` – em telas pequenas pode ser pouco |
| Dropdown | Posição `right: 8px` pode sair da tela em mobile |
| user-area | Elementos podem quebrar linha de forma estranha em telas estreitas |

### 3.3 Recomendações

- Breakpoints intermediários: 480px, 640px, 1024px
- Sidebar mobile: drawer ou accordion em vez de bloco fixo no topo
- Input: `max-width: 100%` em mobile
- Usar `clamp()` para fontes e espaçamentos
- Revisar tamanhos de botão e área de toque (mín. 44x44px)

---

## 4. Qualidade do Código

### 4.1 Estrutura

- JS modular em 3 arquivos (app, chat, conversations) – boa separação
- ChatApp global como objeto compartilhado – funcional; considerar módulos ES no futuro
- CSS inline no HTML – ~350 linhas; pode ser extraído para `chat.css`

### 4.2 Pontos de Atenção

| Arquivo | Questão |
|---------|---------|
| conversations.js | `appendMessage` local que chama `ChatApp.appendMessage` – após delete usa essa função, mas `ChatApp.clearMessages` não é atribuído no escopo; na prática chama `ChatApp.appendMessage` para a mensagem system |
| app.js | Se `loadConversations` falhar, `conversationsPanel.style.display` pode não ser atualizado em alguns fluxos |
| chat.js | `body.innerHTML = text.replace(/\n/g, "<br>")` – risco de XSS se `text` tiver HTML; ideal sanitizar ou usar `textContent` + formatação controlada |
| index.html | Uso de `innerHTML` em sources e body de mensagens – validar origem dos dados |

### 4.3 XSS

- `body.innerHTML = text.replace(...)` – conteúdo do backend deve ser confiável
- `tag.textContent = ...` para sources – correto
- Recomendação: sanitizar HTML ou usar escape antes de `innerHTML`

---

## 5. Funcionalidades Faltantes (do plano)

| Item | Status | Prioridade |
|------|--------|------------|
| Toggle tema claro/escuro | Não implementado | Alta |
| Logo minor no sidebar recolhido | Não implementado | Média |
| Painel de admin | Não implementado | Alta |
| Configurações no rodapé | Não implementado | Média |
| Nova Conversa criando card via API | Não implementado (ainda mostra mensagem system) | Alta |

---

## 6. Checklist de Melhorias

### Visual

- [x] Remover CSS duplicado de `.main-header`
- [x] Trocar cores hardcoded por variáveis CSS
- [x] Implementar tema escuro completo (variáveis + body.dark-mode)
- [x] Garantir `display: flex` em user-guest/user-logged quando visíveis
- [x] Ajustar `.input-area` para usar `var(--bg)`

### UX

- [x] Indicador de "Gerando resposta..." durante envio
- [x] Estado de loading explícito na lista de conversas
- [x] Feedback ao usuário em erros de rename/reorder
- [x] Estados vazios mais claros, com call-to-action
- [ ] Considerar modal customizado para confirmar exclusão em vez de `confirm()`

### Responsividade

- [x] Breakpoints adicionais (480, 640, 1024)
- [x] Revisar layout mobile do sidebar
- [x] Áreas de toque mínimas (44x44px) – theme-toggle
- [x] `max-width: 100%` no input em mobile

### Acessibilidade

- [x] `:focus-visible` em botões e inputs
- [x] Suporte a teclado no dropdown (Escape para fechar)
- [x] `role` e `aria-*` em lista de conversas

### Segurança

- [x] Sanitizar conteúdo antes de `innerHTML` em mensagens

---

## 7. Resumo Executivo

O frontend está funcional e bem organizado em módulos. Os principais pontos a tratar são:

1. **Tema escuro** – variáveis e componentes ainda usam cores claras fixas
2. **Estados de carregamento** – falta feedback visual explícito durante o envio e carregamento
3. **Responsividade** – ampliar breakpoints e revisar uso em mobile
4. **Código** – remover duplicações, padronizar variáveis e mitigar risco de XSS
5. **Itens do plano** – implementar tema, logo minor, painel admin, fluxo correto de Nova Conversa

Com essas correções, a interface fica mais robusta, consistente e preparada para uso corporativo.
