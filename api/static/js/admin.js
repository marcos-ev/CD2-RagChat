(function () {
  const uploadForm = document.getElementById("upload-form");
  const fileInput = document.getElementById("file-input");
  const uploadBtn = document.getElementById("upload-btn");
  const uploadStatus = document.getElementById("upload-status");
  const documentsList = document.getElementById("documents-list");
  const documentsLoading = document.getElementById("documents-loading");
  const documentsEmpty = document.getElementById("documents-empty");

  const fetchOpts = { credentials: "include" };

  async function loadSettings() {
    const instructionsEl = document.getElementById("settings-instructions");
    const statusEl = document.getElementById("settings-status");
    if (!instructionsEl) return;
    try {
      const res = await fetch("/admin/settings", fetchOpts);
      if (!res.ok) return;
      const data = await res.json();
      instructionsEl.value = data.rag_instructions || "";
    } catch (e) {
      console.warn("Erro ao carregar instruções:", e);
    }
  }

  async function saveSettings() {
    const instructionsEl = document.getElementById("settings-instructions");
    const saveBtn = document.getElementById("settings-save-btn");
    const statusEl = document.getElementById("settings-status");
    if (!instructionsEl || !saveBtn) return;
    saveBtn.disabled = true;
    statusEl.className = "upload-status";
    statusEl.textContent = "Salvando...";
    statusEl.style.display = "block";
    try {
      const res = await fetch("/admin/settings", {
        ...fetchOpts,
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rag_instructions: instructionsEl.value }),
      });
      if (!res.ok) throw new Error(await res.text());
      statusEl.className = "upload-status success";
      statusEl.textContent = "Instruções salvas.";
    } catch (e) {
      statusEl.className = "upload-status error";
      statusEl.textContent = "Erro: " + e.message;
    } finally {
      saveBtn.disabled = false;
    }
  }

  async function checkAuth() {
    const res = await fetch("/me", fetchOpts);
    if (res.status === 401) {
      window.location.href = "/login?next=/admin";
      return false;
    }
    if (!res.ok) {
      uploadStatus.textContent = "Erro ao verificar permissão.";
      uploadStatus.className = "upload-status error";
      return false;
    }
    const me = await res.json();
    const role = (me.role || "").toLowerCase();
    if (role !== "admin" && role !== "publicador") {
      uploadStatus.textContent = "Acesso negado. Apenas admin/publicador.";
      uploadStatus.className = "upload-status error";
      return false;
    }
    if (role === "admin") {
      await loadSettings();
      document.getElementById("settings-save-btn")?.addEventListener("click", saveSettings);
    } else {
      document.getElementById("admin-settings-section")?.remove();
      document.getElementById("admin-sync-section")?.remove();
    }
    return true;
  }

  async function loadDocuments() {
    documentsLoading.style.display = "block";
    documentsList.innerHTML = "";
    documentsEmpty.style.display = "none";
    try {
      const res = await fetch("/documents?limit=100", fetchOpts);
      if (!res.ok) throw new Error(res.statusText);
      const data = await res.json();
      documentsLoading.style.display = "none";
      if (!data.documents || data.documents.length === 0) {
        documentsEmpty.style.display = "block";
        return;
      }
      data.documents.forEach((doc) => {
        const item = document.createElement("div");
        item.className = "doc-item";
        item.innerHTML = `
          <span class="doc-item-name">${escapeHtml(doc.filename)}</span>
          <span class="doc-item-meta">${doc.created_at ? new Date(doc.created_at).toLocaleDateString("pt-BR") : ""}</span>
          <button type="button" class="btn-delete" data-id="${doc.id}">Excluir</button>
        `;
        item.querySelector(".btn-delete").addEventListener("click", () => deleteDocument(doc.id));
        documentsList.appendChild(item);
      });
    } catch (e) {
      documentsLoading.textContent = "Erro ao carregar: " + e.message;
    }
  }

  function escapeHtml(str) {
    if (!str) return "";
    const div = document.createElement("div");
    div.textContent = String(str);
    return div.innerHTML;
  }

  async function deleteDocument(id) {
    if (!confirm("Excluir este documento?")) return;
    try {
      const res = await fetch(`/documents/${id}`, { ...fetchOpts, method: "DELETE" });
      if (!res.ok) throw new Error(await res.text());
      await loadDocuments();
    } catch (e) {
      alert("Erro ao excluir: " + e.message);
    }
  }

  async function runSync() {
    const btn = document.getElementById("sync-btn");
    const status = document.getElementById("sync-status");
    if (!btn || !status) return;
    btn.disabled = true;
    status.className = "upload-status";
    status.textContent = "Sincronizando...";
    status.style.display = "block";
    try {
      const res = await fetch("/admin/sync", { ...fetchOpts, method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || data.message || res.statusText);
      }
      status.className = "upload-status success";
      status.textContent = data.message || `${data.processed} arquivo(s) processado(s).`;
      if (data.errors && data.errors.length) {
        status.textContent += " Erros: " + data.errors.join("; ");
      }
      await loadDocuments();
    } catch (e) {
      status.className = "upload-status error";
      status.textContent = "Erro: " + e.message;
    } finally {
      btn.disabled = false;
    }
  }

  document.getElementById("sync-btn")?.addEventListener("click", runSync);

  uploadForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const file = fileInput.files[0];
    if (!file) return;
    uploadBtn.disabled = true;
    uploadStatus.className = "upload-status";
    uploadStatus.textContent = "Enviando...";
    uploadStatus.style.display = "block";
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch("/upload", {
        ...fetchOpts,
        method: "POST",
        body: formData,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || res.statusText);
      }
      uploadStatus.className = "upload-status success";
      uploadStatus.textContent = "Documento processado: " + (data.filename || file.name);
      fileInput.value = "";
      await loadDocuments();
    } catch (e) {
      uploadStatus.className = "upload-status error";
      uploadStatus.textContent = "Erro: " + e.message;
    } finally {
      uploadBtn.disabled = false;
    }
  });

  (async function init() {
    const ok = await checkAuth();
    if (ok) await loadDocuments();
  })();
})();
