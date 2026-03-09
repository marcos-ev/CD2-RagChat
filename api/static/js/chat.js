/**
 * chat.js - Mensagens e envio
 */
(function () {
  const messagesEl = document.getElementById("messages");
  const inputEl = document.getElementById("chat-input");
  const sendBtn = document.getElementById("send-btn");
  const convCurrent = document.getElementById("conv-current");
  const convMeta = document.getElementById("conv-meta");

  function escapeHtml(str) {
    if (str == null) return "";
    const div = document.createElement("div");
    div.textContent = String(str);
    return div.innerHTML;
  }

  function simpleMarkdown(html) {
    const blocks = [];
    let s = html.replace(/```([\s\S]*?)```/g, function (_, code) {
      blocks.push(code);
      return "\x00CB" + (blocks.length - 1) + "\x00";
    });
    s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
    s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/_([^_]+)_/g, "<em>$1</em>");
    s = s.replace(/\n/g, "<br>");
    blocks.forEach(function (code, i) {
      s = s.replace("\x00CB" + i + "\x00", "<pre><code>" + code + "</code></pre>");
    });
    return s;
  }

  function appendMessage(role, text, sources, scroll) {
    if (typeof scroll === "undefined") scroll = true;
    const msg = document.createElement("div");
    msg.classList.add("msg", role);

    const icon = document.createElement("div");
    icon.className = "msg-icon";
    icon.innerHTML = role === "user" ? "&#127919;" : role === "bot" ? "&#128196;" : "&#9881;";
    msg.appendChild(icon);

    const body = document.createElement("div");
    body.className = "msg-body";
    body.innerHTML = simpleMarkdown(escapeHtml(text));
    msg.appendChild(body);

    messagesEl.appendChild(msg);
    if (scroll !== false) messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function setMessagesFromConversation(msgs, showPlaceholder) {
    if (typeof showPlaceholder === "undefined") showPlaceholder = true;
    const system = messagesEl.querySelector(".msg.system");
    messagesEl.innerHTML = "";
    if (!msgs || msgs.length === 0) {
      if (showPlaceholder && system) messagesEl.appendChild(system);
      convMeta.textContent = "0 perguntas • 0 mensagens";
      return;
    }
    let userCount = 0, botCount = 0;
    msgs.forEach((m) => {
      const role = m.role === "user" ? "user" : m.role === "assistant" ? "bot" : "system";
      if (role === "user") userCount++;
      if (role === "bot") botCount++;
      appendMessage(role, m.content || "", m.sources || [], false);
    });
    convMeta.textContent = userCount + " perguntas • " + (userCount + botCount) + " mensagens";
  }

  function clearMessages() {
    const system = messagesEl.querySelector(".msg.system");
    messagesEl.innerHTML = "";
    if (system) messagesEl.appendChild(system);
    convCurrent.textContent = "Nova Conversa";
    convMeta.textContent = "0 perguntas • 0 mensagens";
  }

  function isDefaultConversationTitle(title) {
    return String(title || "").trim().toLowerCase() === "nova conversa";
  }

  function summarizeConversationTitle(text, maxWords) {
    const limit = maxWords || 6;
    const cleaned = String(text || "")
      .replace(/\s+/g, " ")
      .replace(/[\"'`]/g, "")
      .trim();
    if (!cleaned) return "Nova conversa";
    const words = cleaned.split(" ").filter(Boolean).slice(0, limit);
    if (words.length === 0) return "Nova conversa";
    let title = words.join(" ").replace(/[.,;:!?]+$/g, "");
    if (title.length > 80) title = title.slice(0, 80).trim();
    return title || "Nova conversa";
  }

  function isAnonymousMode() {
    return !ChatApp.currentUser && !!ChatApp.allowAnonymousChat;
  }

  function ensureAnonymousConversation(titleHint) {
    const convs = (ChatApp.getAnonymousConversations && ChatApp.getAnonymousConversations()) || [];
    const current = convs.find((c) => String(c.id) === String(ChatApp.currentConversationId));
    if (current) return current;
    const id = "anon-" + Date.now();
    const conv = {
      id: id,
      title: titleHint || "Nova conversa",
      created_at: new Date().toISOString(),
      messages: [],
    };
    convs.unshift(conv);
    if (ChatApp.saveAnonymousConversations) ChatApp.saveAnonymousConversations(convs);
    ChatApp.currentConversationId = id;
    if (ChatApp.prependConversationIfNew) ChatApp.prependConversationIfNew(id, conv.title);
    return conv;
  }

  async function sendMessage() {
    const text = inputEl.value.trim();
    if (!text) return;
    const optimisticTitle = summarizeConversationTitle(text, 6);

    const canSend = ChatApp.currentUser || ChatApp.allowAnonymousChat;
    if (!canSend) {
      appendMessage("system", "Faça login para usar o chat ou ative ALLOW_ANONYMOUS_CHAT para teste.");
      return;
    }

    appendMessage("user", text);
    inputEl.value = "";
    inputEl.focus();
    sendBtn.disabled = true;

    appendMessage("bot", "Gerando resposta...", [], true);
    const loadingEl = messagesEl.lastElementChild;
    if (loadingEl) loadingEl.classList.add("loading");

    try {
      if (ChatApp.currentUser) {
        const body = { query: text };
        if (ChatApp.currentConversationId) body.conversation_id = ChatApp.currentConversationId;
        const res = await fetch("/chat", {
          ...ChatApp.fetchOpts,
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!res.ok) {
          if (loadingEl) loadingEl.remove();
          const errText = await res.text();
          appendMessage("system", "Erro: " + res.status + " – " + errText.slice(0, 200));
          return;
        }
        const data = await res.json();
        if (loadingEl) loadingEl.remove();
        ChatApp.currentConversationId = data.conversation_id;
        appendMessage("bot", data.answer || "(sem resposta)", data.sources || []);
        const resolvedTitle = data.title || optimisticTitle || "Nova conversa";
        convCurrent.textContent = resolvedTitle;
        ChatApp.updateConvTitleInList(data.conversation_id, resolvedTitle);
        ChatApp.prependConversationIfNew(data.conversation_id, resolvedTitle);
        if (isDefaultConversationTitle(data.title) && ChatApp.renameConversation) {
          await ChatApp.renameConversation(data.conversation_id, resolvedTitle);
        }
        await ChatApp.loadConversations();
        const userMsgs = messagesEl.querySelectorAll(".msg.user");
        const botMsgs = messagesEl.querySelectorAll(".msg.bot");
        convMeta.textContent = userMsgs.length + " perguntas • " + (userMsgs.length + botMsgs.length) + " mensagens";
      } else {
        const anonConv = ensureAnonymousConversation(optimisticTitle);
        const res = await fetch("/rag", {
          ...ChatApp.fetchOpts,
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query: text }),
        });
        if (!res.ok) {
          if (loadingEl) loadingEl.remove();
          const errText = await res.text();
          appendMessage("system", "Erro: " + res.status + " – " + errText.slice(0, 200));
          return;
        }
        const data = await res.json();
        if (loadingEl) loadingEl.remove();
        appendMessage("bot", data.answer || "(sem resposta)", data.sources || []);
        const convs = (ChatApp.getAnonymousConversations && ChatApp.getAnonymousConversations()) || [];
        const idx = convs.findIndex((c) => String(c.id) === String(anonConv.id));
        if (idx >= 0) {
          const conv = convs[idx];
          if (!conv.messages) conv.messages = [];
          conv.messages.push({ role: "user", content: text, created_at: new Date().toISOString(), sources: [] });
          conv.messages.push({
            role: "assistant",
            content: data.answer || "(sem resposta)",
            created_at: new Date().toISOString(),
            sources: data.sources || [],
          });
          if (!conv.title || String(conv.title).trim().toLowerCase() === "nova conversa") {
            conv.title = optimisticTitle;
          }
          convs.splice(idx, 1);
          convs.unshift(conv);
          if (ChatApp.saveAnonymousConversations) ChatApp.saveAnonymousConversations(convs);
          convCurrent.textContent = conv.title || optimisticTitle || "Nova conversa";
          if (ChatApp.updateConvTitleInList) ChatApp.updateConvTitleInList(conv.id, convCurrent.textContent);
          if (ChatApp.loadConversations) await ChatApp.loadConversations();
          document.querySelectorAll(".conv-item").forEach((el) => {
            el.classList.toggle("active", el.dataset.convId === String(conv.id));
          });
        }
        const userMsgs = messagesEl.querySelectorAll(".msg.user");
        const botMsgs = messagesEl.querySelectorAll(".msg.bot");
        convMeta.textContent = userMsgs.length + " perguntas • " + (userMsgs.length + botMsgs.length) + " mensagens";
      }
    } catch (e) {
      if (loadingEl) loadingEl.remove();
      appendMessage("system", "Falha de rede: " + e.message);
    } finally {
      sendBtn.disabled = false;
    }
  }

  inputEl.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && !ev.shiftKey) {
      ev.preventDefault();
      sendMessage();
    }
  });
  sendBtn.addEventListener("click", sendMessage);

  ChatApp.appendMessage = appendMessage;
  ChatApp.setMessagesFromConversation = setMessagesFromConversation;
  ChatApp.clearMessages = clearMessages;
  ChatApp.sendMessage = sendMessage;
})();
