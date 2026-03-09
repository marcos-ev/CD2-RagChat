/**
 * conversations.js - Lista, dropdown, rename inline, reorder
 */
(function () {
  const conversationsList = document.getElementById("conversations-list");
  const newConvBtn = document.getElementById("new-conv-btn");
  const clearBtn = document.getElementById("clear-btn");
  const convStatus = document.getElementById("conv-status");
  const convCurrent = document.getElementById("conv-current");
  const ANON_STORAGE_KEY = "cd2-anonymous-conversations-v1";

  let dropdownOpenFor = null;
  let draggedId = null;
  let dropdownAnchorBtn = null;

  function isAnonymousMode() {
    return !ChatApp.currentUser && !!ChatApp.allowAnonymousChat;
  }

  function getAnonymousConversations() {
    try {
      const raw = localStorage.getItem(ANON_STORAGE_KEY);
      const list = raw ? JSON.parse(raw) : [];
      return Array.isArray(list) ? list : [];
    } catch (_) {
      return [];
    }
  }

  function saveAnonymousConversations(list) {
    localStorage.setItem(ANON_STORAGE_KEY, JSON.stringify(Array.isArray(list) ? list : []));
  }

  function renderConversationList(convs) {
    ChatApp.conversations = convs || [];
    conversationsList.innerHTML = "";
    if (!convs || convs.length === 0) {
      const empty = document.createElement("div");
      empty.className = "hint";
      empty.style.padding = "12px";
      empty.style.textAlign = "center";
      empty.innerHTML = "Nenhuma conversa ainda.<br><small>Clique em Nova Conversa para começar.</small>";
      conversationsList.appendChild(empty);
    } else {
      convs.forEach((c) => conversationsList.appendChild(createConvItem(c)));
    }
    convStatus.textContent = "Total: " + (convs?.length || 0) + " conversa(s).";
    convStatus.style.color = "";
  }

  async function loadConversations() {
    if (isAnonymousMode()) {
      const convs = getAnonymousConversations();
      renderConversationList(convs);
      return;
    }
    if (!ChatApp.currentUser) return;
    conversationsList.innerHTML = '<div class="hint" style="padding:12px">Carregando...</div>';
    convStatus.textContent = "";
    try {
      const res = await fetch("/conversations", ChatApp.fetchOpts);
      if (!res.ok) throw new Error(res.statusText);
      const convs = await res.json();
      renderConversationList(convs || []);
    } catch (e) {
      convStatus.textContent = "Erro ao carregar.";
      convStatus.style.color = "var(--danger)";
      conversationsList.innerHTML = "";
    }
  }

  function createConvItem(c) {
    const item = document.createElement("div");
    item.className = "conv-item" + (ChatApp.currentConversationId === c.id ? " active" : "");
    item.dataset.convId = String(c.id);
    item.draggable = true;
    item.setAttribute("role", "listitem");

    const left = document.createElement("div");
    left.className = "conv-item-left";
    left.addEventListener("click", (e) => {
      if (!e.target.closest(".conv-item-menu") && !e.target.closest(".conv-rename-input")) {
        selectConversation(c.id);
      }
    });

    const dragHandle = document.createElement("span");
    dragHandle.className = "conv-drag-handle";
    dragHandle.title = "Arrastar para reordenar";
    dragHandle.innerHTML = "&#8801;";
    dragHandle.addEventListener("mousedown", (e) => e.stopPropagation());

    const titleSpan = document.createElement("span");
    titleSpan.className = "conv-item-title";
    titleSpan.textContent = c.title || "Conversa #" + c.id;

    const menuBtn = document.createElement("button");
    menuBtn.className = "conv-item-menu";
    menuBtn.type = "button";
    menuBtn.title = "Opções";
    menuBtn.innerHTML = "&#8942;";
    menuBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleDropdown(c.id);
    });

    left.appendChild(dragHandle);
    left.appendChild(titleSpan);
    item.appendChild(left);
    item.appendChild(menuBtn);

    const dropdown = document.createElement("div");
    dropdown.className = "conv-dropdown";
    dropdown.setAttribute("role", "menu");
    dropdown.innerHTML = '<button type="button" class="conv-dropdown-item" data-action="rename" role="menuitem">Renomear</button><button type="button" class="conv-dropdown-item conv-dropdown-danger" data-action="delete" role="menuitem">Excluir</button>';
    dropdown.querySelector('[data-action="rename"]').addEventListener("click", (e) => {
      e.stopPropagation();
      closeDropdown();
      startRename(item, c);
    });
    dropdown.querySelector('[data-action="delete"]').addEventListener("click", (e) => {
      e.stopPropagation();
      closeDropdown();
      deleteConversation(c.id);
    });

    item.appendChild(dropdown);

    item.addEventListener("dragstart", (e) => {
      draggedId = c.id;
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", String(c.id));
      item.classList.add("conv-dragging");
    });
    item.addEventListener("dragend", () => {
      item.classList.remove("conv-dragging");
      draggedId = null;
    });
    item.addEventListener("dragover", (e) => {
      e.preventDefault();
      if (draggedId && draggedId !== c.id) {
        item.classList.add("conv-drag-over");
      }
    });
    item.addEventListener("dragleave", () => item.classList.remove("conv-drag-over"));
    item.addEventListener("drop", (e) => {
      e.preventDefault();
      item.classList.remove("conv-drag-over");
      if (draggedId && draggedId !== c.id) {
        reorderFromDrag(draggedId, c.id);
      }
    });

    return item;
  }

  function toggleDropdown(convId) {
    if (dropdownOpenFor === convId) {
      closeDropdown();
    } else {
      document.querySelectorAll(".conv-dropdown").forEach((d) => d.classList.remove("open"));
      const item = document.querySelector(`.conv-item[data-conv-id="${convId}"]`);
      if (item) {
        const menuBtn = item.querySelector(".conv-item-menu");
        const dd = item.querySelector(".conv-dropdown");
        if (menuBtn && dd) positionDropdown(dd, menuBtn);
        dd.classList.add("open");
        dropdownOpenFor = convId;
        dropdownAnchorBtn = menuBtn || null;
      }
    }
  }

  function positionDropdown(dropdown, anchorBtn) {
    if (!dropdown || !anchorBtn) return;
    dropdown.style.position = "fixed";
    dropdown.style.top = "0px";
    dropdown.style.left = "-9999px";
    dropdown.classList.add("open");
    const rect = anchorBtn.getBoundingClientRect();
    const ddRect = dropdown.getBoundingClientRect();
    const gap = 6;
    const viewportPadding = 8;
    let left = rect.right - ddRect.width;
    if (left < viewportPadding) left = viewportPadding;
    if (left + ddRect.width > window.innerWidth - viewportPadding) {
      left = window.innerWidth - ddRect.width - viewportPadding;
    }
    let top = rect.bottom + gap;
    if (top + ddRect.height > window.innerHeight - viewportPadding) {
      top = rect.top - ddRect.height - gap;
    }
    if (top < viewportPadding) top = viewportPadding;
    dropdown.style.left = left + "px";
    dropdown.style.top = top + "px";
  }

  function repositionOpenDropdown() {
    if (!dropdownOpenFor || !dropdownAnchorBtn) return;
    const item = document.querySelector(`.conv-item[data-conv-id="${dropdownOpenFor}"]`);
    if (!item) return closeDropdown();
    const dd = item.querySelector(".conv-dropdown");
    if (!dd) return closeDropdown();
    positionDropdown(dd, dropdownAnchorBtn);
  }

  function closeDropdown() {
    document.querySelectorAll(".conv-dropdown").forEach((d) => {
      d.classList.remove("open");
      d.style.top = "";
      d.style.left = "";
      d.style.position = "";
    });
    dropdownOpenFor = null;
    dropdownAnchorBtn = null;
  }

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".conv-dropdown") && !e.target.closest(".conv-item-menu")) {
      closeDropdown();
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeDropdown();
  });
  window.addEventListener("resize", () => closeDropdown());
  window.addEventListener("scroll", () => closeDropdown(), true);
  conversationsList.addEventListener("scroll", () => closeDropdown());

  function startRename(item, c) {
    const titleSpan = item.querySelector(".conv-item-title");
    if (!titleSpan || titleSpan.classList.contains("conv-rename-input")) return;
    const currentTitle = titleSpan.textContent || c.title || "";
    const input = document.createElement("input");
    input.type = "text";
    input.className = "conv-rename-input";
    input.value = currentTitle;
    titleSpan.replaceWith(input);
    input.focus();
    input.select();

    function finishRename(save) {
      const newTitle = save ? input.value.trim() || "Nova conversa" : currentTitle;
      input.replaceWith(titleSpan);
      titleSpan.textContent = newTitle;
      if (save && newTitle !== currentTitle) {
        patchRename(c.id, newTitle).then(() => {
          if (ChatApp.currentConversationId === c.id) convCurrent.textContent = newTitle;
        });
      }
    }

    input.addEventListener("blur", () => finishRename(true));
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        finishRename(true);
      } else if (e.key === "Escape") {
        e.preventDefault();
        finishRename(false);
      }
    });
  }

  async function patchRename(convId, title) {
    if (isAnonymousMode()) {
      const convs = getAnonymousConversations();
      const idx = convs.findIndex((c) => String(c.id) === String(convId));
      if (idx >= 0) {
        convs[idx].title = title || "Nova conversa";
        saveAnonymousConversations(convs);
        renderConversationList(convs);
        return true;
      }
      return false;
    }
    try {
      const res = await fetch(`/conversations/${convId}`, {
        ...ChatApp.fetchOpts,
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      });
      if (res.ok) {
        const item = document.querySelector(`.conv-item[data-conv-id="${convId}"] .conv-item-title`);
        if (item) item.textContent = title;
        const idx = ChatApp.conversations.findIndex((c) => c.id === convId);
        if (idx >= 0) ChatApp.conversations[idx].title = title;
        return true;
      } else {
        ChatApp.appendMessage("system", "Erro ao renomear. Tente novamente.");
      }
    } catch (e) {
      ChatApp.appendMessage("system", "Erro ao renomear: " + e.message);
    }
    return false;
  }

  async function deleteConversation(convId) {
    if (!window.confirm("Excluir esta conversa?")) return;
    if (isAnonymousMode()) {
      const convs = getAnonymousConversations().filter((c) => String(c.id) !== String(convId));
      saveAnonymousConversations(convs);
      if (String(ChatApp.currentConversationId) === String(convId)) {
        ChatApp.currentConversationId = null;
        ChatApp.clearMessages();
        ChatApp.appendMessage("system", "Nova conversa. Pergunte algo sobre os documentos da empresa.", [], true);
      }
      await loadConversations();
      return;
    }
    try {
      const res = await fetch(`/conversations/${convId}`, { ...ChatApp.fetchOpts, method: "DELETE" });
      if (res.ok) {
        if (ChatApp.currentConversationId === convId) {
          ChatApp.currentConversationId = null;
          ChatApp.clearMessages();
          ChatApp.appendMessage("system", "Nova conversa. Pergunte algo sobre os documentos da empresa.", [], true);
        }
        await loadConversations();
      }
    } catch (e) {
      ChatApp.appendMessage("system", "Erro ao excluir: " + e.message);
    }
  }

  function appendMessage() {
    ChatApp.appendMessage.apply(null, arguments);
  }

  function reorderFromDrag(draggedId, targetId) {
    const ids = ChatApp.conversations.map((c) => c.id);
    const fromIdx = ids.indexOf(draggedId);
    const toIdx = ids.indexOf(targetId);
    if (fromIdx === -1 || toIdx === -1) return;
    ids.splice(fromIdx, 1);
    ids.splice(ids.indexOf(targetId), 0, draggedId);
    reorderConversations(ids);
  }

  async function reorderConversations(order) {
    if (isAnonymousMode()) {
      const convs = getAnonymousConversations();
      const map = {};
      convs.forEach((c) => {
        map[String(c.id)] = c;
      });
      const reordered = order.map((id) => map[String(id)]).filter(Boolean);
      const tail = convs.filter((c) => !order.some((id) => String(id) === String(c.id)));
      const next = reordered.concat(tail);
      saveAnonymousConversations(next);
      renderConversationList(next);
      return;
    }
    try {
      const res = await fetch("/conversations/reorder", {
        ...ChatApp.fetchOpts,
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ order }),
      });
      if (res.ok) {
        await loadConversations();
      } else {
        ChatApp.appendMessage("system", "Erro ao reordenar. Tente novamente.");
      }
    } catch (e) {
      ChatApp.appendMessage("system", "Erro ao reordenar: " + e.message);
    }
  }

  function selectConversation(id) {
    ChatApp.currentConversationId = id;
    document.querySelectorAll(".conv-item").forEach((el) => {
      el.classList.toggle("active", el.dataset.convId === String(id));
    });
    loadConversationMessages(id);
  }

  async function loadConversationMessages(id) {
    if (isAnonymousMode()) {
      const conv = getAnonymousConversations().find((c) => String(c.id) === String(id));
      if (!conv) {
        ChatApp.clearMessages();
        return;
      }
      convCurrent.textContent = conv.title || "Nova conversa";
      ChatApp.setMessagesFromConversation(conv.messages || [], true);
      return;
    }
    try {
      const res = await fetch("/conversations/" + id, ChatApp.fetchOpts);
      if (!res.ok) throw new Error(res.statusText);
      const data = await res.json();
      convCurrent.textContent = data.title || "Conversa #" + id;
      ChatApp.setMessagesFromConversation(data.messages || [], true);
    } catch (e) {
      ChatApp.clearMessages();
      ChatApp.appendMessage("system", "Erro ao carregar conversa: " + e.message);
    }
  }

  async function newConversation() {
    if (isAnonymousMode()) {
      const convs = getAnonymousConversations();
      const id = "anon-" + Date.now();
      const newConv = { id, title: "Nova conversa", created_at: new Date().toISOString(), messages: [] };
      convs.unshift(newConv);
      saveAnonymousConversations(convs);
      ChatApp.currentConversationId = id;
      ChatApp.clearMessages();
      ChatApp.appendMessage("system", "Nova conversa. Pergunte algo sobre os documentos da empresa.", [], true);
      convCurrent.textContent = "Nova conversa";
      await loadConversations();
      document.querySelectorAll(".conv-item").forEach((el) => {
        el.classList.toggle("active", el.dataset.convId === String(id));
      });
      return;
    }
    if (!ChatApp.currentUser) {
      ChatApp.currentConversationId = null;
      document.querySelectorAll(".conv-item").forEach((el) => el.classList.remove("active"));
      ChatApp.clearMessages();
      ChatApp.appendMessage("system", "Nova conversa. Pergunte algo sobre os documentos da empresa.", [], true);
      return;
    }
    try {
      const res = await fetch("/conversations", {
        ...ChatApp.fetchOpts,
        method: "POST",
      });
      if (!res.ok) throw new Error(res.statusText);
      const data = await res.json();
      ChatApp.currentConversationId = data.id;
      document.querySelectorAll(".conv-item").forEach((el) => el.classList.remove("active"));
      if (conversationsList.children.length === 1) {
        var first = conversationsList.firstElementChild;
        if (first && first.classList.contains("hint") && first.textContent.indexOf("Nenhuma conversa") >= 0)
          first.remove();
      }
      var newItem = createConvItem({
        id: data.id,
        title: data.title || "Nova conversa",
        created_at: data.created_at,
      });
      newItem.classList.add("active");
      conversationsList.insertBefore(newItem, conversationsList.firstChild);
      convStatus.textContent = "Total: " + (ChatApp.conversations.length + 1) + " conversa(s).";
      convCurrent.textContent = data.title || "Nova conversa";
      ChatApp.setMessagesFromConversation([], false);
      await loadConversations();
    } catch (e) {
      ChatApp.appendMessage("system", "Erro ao criar conversa: " + e.message);
    }
  }

  function updateConvTitleInList(convId, title) {
    const item = document.querySelector(`.conv-item[data-conv-id="${convId}"] .conv-item-title`);
    if (item && !item.classList.contains("conv-rename-input")) item.textContent = title;
    if (isAnonymousMode()) {
      const convs = getAnonymousConversations();
      const idx = convs.findIndex((c) => String(c.id) === String(convId));
      if (idx >= 0) {
        convs[idx].title = title || "Nova conversa";
        saveAnonymousConversations(convs);
      }
    }
  }

  newConvBtn.addEventListener("click", newConversation);
  clearBtn.addEventListener("click", newConversation);

  function prependConversationIfNew(id, title) {
    if (isAnonymousMode()) {
      const convs = getAnonymousConversations();
      const idx = convs.findIndex((c) => String(c.id) === String(id));
      if (idx === -1) {
        convs.unshift({
          id: id,
          title: title || "Nova conversa",
          created_at: new Date().toISOString(),
          messages: [],
        });
      } else {
        convs[idx].title = title || convs[idx].title || "Nova conversa";
      }
      saveAnonymousConversations(convs);
      renderConversationList(convs);
      document.querySelectorAll(".conv-item").forEach(function (el) {
        el.classList.toggle("active", el.dataset.convId === String(id));
      });
      return;
    }
    if (!ChatApp.currentUser) return;
    if (document.querySelector('.conv-item[data-conv-id="' + id + '"]')) return;
    if (conversationsList.children.length === 1) {
      var first = conversationsList.firstElementChild;
      if (first && first.classList.contains("hint") && first.textContent.indexOf("Nenhuma conversa") >= 0)
        first.remove();
    }
    var item = createConvItem({ id: id, title: title || "Nova conversa", created_at: null });
    item.classList.add("active");
    conversationsList.insertBefore(item, conversationsList.firstChild);
    document.querySelectorAll(".conv-item").forEach(function (el) {
      el.classList.toggle("active", el.dataset.convId === String(id));
    });
    convStatus.textContent = "Total: " + (document.querySelectorAll(".conv-item").length) + " conversa(s).";
  }

  ChatApp.loadConversations = loadConversations;
  ChatApp.selectConversation = selectConversation;
  ChatApp.updateConvTitleInList = updateConvTitleInList;
  ChatApp.prependConversationIfNew = prependConversationIfNew;
  ChatApp.renameConversation = patchRename;
  ChatApp.getAnonymousConversations = getAnonymousConversations;
  ChatApp.saveAnonymousConversations = saveAnonymousConversations;
})();
