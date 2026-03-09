/**
 * app.js - Inicialização, auth e config
 */
(function () {
  const userLoading = document.getElementById("user-loading");
  const userGuest = document.getElementById("user-guest");
  const userLogged = document.getElementById("user-logged");
  const userNameEmail = document.getElementById("user-name-email");
  const conversationsPanel = document.getElementById("conversations-panel");

  window.ChatApp = {
    currentUser: null,
    currentConversationId: null,
    allowAnonymousChat: false,
    bypassAuth: false,
    fetchOpts: { credentials: "include" },
    conversations: [],
    appendMessage: function () {},
    loadConversations: function () {},
    updateConvTitleInList: function () {},
  };

  function shouldShowConversationsWithoutLogin() {
    return !ChatApp.currentUser && ChatApp.allowAnonymousChat;
  }

  async function loadConfig() {
    try {
      const res = await fetch("/", ChatApp.fetchOpts);
      const data = await res.json();
      ChatApp.allowAnonymousChat = !!data.allow_anonymous_chat;
      ChatApp.bypassAuth = !!data.bypass_auth;
    } catch (_) {}
  }

  async function checkAuth() {
    userLoading.style.display = "block";
    userGuest.style.display = "none";
    userLogged.style.display = "none";
    try {
      const res = await fetch("/me", { ...ChatApp.fetchOpts });
      if (res.status === 401 && !ChatApp.bypassAuth) {
        userLoading.style.display = "none";
        userGuest.style.display = "flex";
        ChatApp.currentUser = null;
        conversationsPanel.style.display = shouldShowConversationsWithoutLogin() ? "block" : "none";
        if (shouldShowConversationsWithoutLogin()) await ChatApp.loadConversations();
        return;
      }
      if (!res.ok && !ChatApp.bypassAuth) throw new Error(res.statusText);
      const me = res.ok ? await res.json() : (ChatApp.bypassAuth ? { id: 0, role: "admin" } : null);
      ChatApp.currentUser = me;
      userLoading.style.display = "none";
      if (ChatApp.bypassAuth) {
        userGuest.style.display = "none";
        userLogged.style.display = "none";
      } else if (me) {
        userLogged.style.display = "flex";
        userNameEmail.textContent = (me.name || me.email || "Usuário") + (me.email ? " (" + me.email + ")" : "");
      } else {
        userGuest.style.display = "flex";
      }
      conversationsPanel.style.display = "block";
      await ChatApp.loadConversations();
    } catch (e) {
      userLoading.style.display = "none";
      if (!ChatApp.bypassAuth) {
        userGuest.style.display = "flex";
        ChatApp.currentUser = null;
        conversationsPanel.style.display = shouldShowConversationsWithoutLogin() ? "block" : "none";
        if (shouldShowConversationsWithoutLogin()) await ChatApp.loadConversations();
      } else {
        ChatApp.currentUser = { id: 0, role: "admin" };
        conversationsPanel.style.display = "block";
      }
    }
  }

  ChatApp.loadConfig = loadConfig;
  ChatApp.checkAuth = checkAuth;

  function initSidebar() {
    const wrapper = document.getElementById("sidebar-wrapper");
    const toggle = document.getElementById("sidebar-toggle");
    const appRoot = document.querySelector(".app");
    if (!wrapper || !toggle) return;
    const syncCollapsedState = () => {
      if (!appRoot) return;
      appRoot.classList.toggle("sidebar-collapsed", wrapper.classList.contains("collapsed"));
    };
    const stored = localStorage.getItem("cd2-sidebar-collapsed");
    if (stored === "true") wrapper.classList.add("collapsed");
    syncCollapsedState();
    toggle.addEventListener("click", () => {
      wrapper.classList.toggle("collapsed");
      syncCollapsedState();
      toggle.setAttribute("title", wrapper.classList.contains("collapsed") ? "Expandir painel" : "Recolher painel");
      localStorage.setItem("cd2-sidebar-collapsed", wrapper.classList.contains("collapsed"));
    });
    toggle.setAttribute("title", wrapper.classList.contains("collapsed") ? "Expandir painel" : "Recolher painel");
  }

  function initTheme() {
    const themeStored = localStorage.getItem("cd2-theme");
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const wantDark = themeStored === "dark" || (!themeStored && prefersDark);
    if (wantDark) document.body.classList.add("dark-mode");
    else document.body.classList.remove("dark-mode");
    updateThemeIcons(wantDark);

    const themeBtn = document.getElementById("theme-toggle");
    const toggleTheme = () => {
      const isDark = document.body.classList.toggle("dark-mode");
      localStorage.setItem("cd2-theme", isDark ? "dark" : "light");
      updateThemeIcons(isDark);
    };
    if (themeBtn) themeBtn.addEventListener("click", toggleTheme);
  }

  function updateThemeIcons(isDark) {
    const sun = document.querySelector(".theme-toggle .icon-sun");
    const moon = document.querySelector(".theme-toggle .icon-moon");
    if (sun) sun.style.display = isDark ? "none" : "block";
    if (moon) moon.style.display = isDark ? "block" : "none";
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      initTheme();
      initSidebar();
      loadConfig().then(() => checkAuth());
    });
  } else {
    initTheme();
    initSidebar();
    loadConfig().then(() => checkAuth());
  }
})();
