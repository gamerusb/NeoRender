const state = {
  tenantId: localStorage.getItem("neoTenantId") || "default",
  files: [],
  profiles: [],
  tasks: [],
  analytics: [],
  health: null,
  system: null,
  adspower: null,
  groq: null,
  uniqualizer: null,
  preset: "deep",
  template: "default",
  activeSection: "dashboard",
  pipelineRunning: false,
  renderDest: localStorage.getItem("neoRenderDest") || "download",
  subtitleSrtPath: "",
  /** Результат GET /api/integrations/ping (только при полной загрузке, не каждые 5 с) */
  integrationsPing: null,
  /** Последний успешный ответ /api/ai/preview (для вставки текста на видео) */
  lastAiPreview: null,
  /** Абсолютный путь к файлу слоя (с сервера); пусто = data/overlay.png */
  overlayMediaPath: "",
  /** setInterval id для опроса GET /api/pipeline/render-progress */
  renderProgressTimer: null,
  /** Пользователь закрыл модалку вручную — не открывать снова, пока задачи не завершены */
  renderProgressDismissed: false,
};

const geoProfiles = {
  busan: { lat: "35.1796° N", lng: "129.0756° E", city: "Busan, KR" },
  seoul: { lat: "37.5665° N", lng: "126.9780° E", city: "Seoul, KR" },
  incheon: { lat: "37.4563° N", lng: "126.7052° E", city: "Incheon, KR" },
};

const $ = (id) => document.getElementById(id);

/**
 * UI: http://host/prefix/ui/ → API: http://host/prefix/api/...
 * UI: http://host/ui/ → API: /api/...
 */
function apiPrefix() {
  const path = window.location.pathname || "/";
  const m = path.match(/^(.+)\/ui(?:\/|$)/i);
  return m ? m[1] : "";
}

function apiUrl(relPath) {
  const p = relPath.startsWith("/") ? relPath : `/${relPath}`;
  return `${apiPrefix()}${p}`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString("ru-RU");
}

function statusClass(status) {
  if (status === "success" || status === "active") return "status-active";
  if (status === "rendering" || status === "uploading" || status === "shadowban") return "status-frozen";
  if (status === "error" || status === "banned") return "status-banned";
  return "status-frozen";
}

function showToast(message, kind = "ok") {
  const toast = $("toast");
  toast.textContent = message;
  toast.className = `toast show ${kind}`;
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => {
    toast.className = "toast";
  }, 3800);
}

function tasksLookBusy(tasks) {
  return (tasks || []).some(
    (t) => t.status === "rendering" || t.status === "uploading"
  );
}

function hideRenderProgressModal() {
  const m = $("render-progress-modal");
  if (!m) return;
  m.classList.remove("visible");
  m.setAttribute("aria-hidden", "true");
  const bar = $("render-progress-bar");
  if (bar) bar.classList.remove("render-progress-modal__bar--pulse");
}

function applyRenderProgressPayload(j) {
  const m = $("render-progress-modal");
  if (!m) return;
  m.classList.add("visible");
  m.setAttribute("aria-hidden", "false");
  const t = $("render-progress-title");
  const p = $("render-progress-percent");
  const d = $("render-progress-detail");
  const f = $("render-progress-fill");
  const bar = $("render-progress-bar");
  if (t) t.textContent = j.title || "Идёт обработка";
  const pct = Math.min(100, Math.max(0, Number(j.percent) || 0));
  if (p) p.textContent = `${Math.round(pct)}%`;
  if (d) d.textContent = j.detail || "";
  if (f) f.style.width = `${pct}%`;
  if (bar) bar.classList.toggle("render-progress-modal__bar--pulse", !j.encoding);
}

async function fetchRenderProgressOnce() {
  const res = await fetch(apiUrl("/api/pipeline/render-progress"), {
    headers: { "X-Tenant-ID": state.tenantId },
  });
  const j = await res.json().catch(() => ({}));
  if (j.status !== "ok" || !j.visible) {
    hideRenderProgressModal();
    state.renderProgressDismissed = false;
    return false;
  }
  if (!state.renderProgressDismissed) {
    applyRenderProgressPayload(j);
  }
  return true;
}

function userDismissRenderProgressModal() {
  state.renderProgressDismissed = true;
  if (state.renderProgressTimer != null) {
    clearInterval(state.renderProgressTimer);
    state.renderProgressTimer = null;
  }
  hideRenderProgressModal();
  showToast("Окно закрыто. Прогресс смотрите в таблице задач.", "ok");
}

function startRenderProgressPolling() {
  if (state.renderProgressTimer != null) return;
  state.renderProgressTimer = setInterval(async () => {
    try {
      const on = await fetchRenderProgressOnce();
      if (!on) {
        clearInterval(state.renderProgressTimer);
        state.renderProgressTimer = null;
      }
    } catch {
      hideRenderProgressModal();
      if (state.renderProgressTimer != null) {
        clearInterval(state.renderProgressTimer);
        state.renderProgressTimer = null;
      }
    }
  }, 480);
}

function stopRenderProgressPolling() {
  if (state.renderProgressTimer != null) {
    clearInterval(state.renderProgressTimer);
    state.renderProgressTimer = null;
  }
  hideRenderProgressModal();
}

async function api(path, options = {}) {
  if (window.location.protocol === "file:") {
    throw new Error(
      "Откройте интерфейс через сервер, например http://127.0.0.1:8765/ui/ (не файл с диска)."
    );
  }
  const url = path.startsWith("http") ? path : apiUrl(path);
  const headers = new Headers(options.headers || {});
  headers.set("X-Tenant-ID", state.tenantId);
  if (!headers.has("Content-Type") && !(options.body instanceof FormData) && options.body) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(url, { ...options, headers });
  const raw = await response.text();
  let data = {};
  if (raw.trim()) {
    try {
      data = JSON.parse(raw);
    } catch {
      throw new Error(
        `Ошибка ${response.status}: ${raw.slice(0, 200) || response.statusText || "не JSON"}`
      );
    }
  }
  if (!response.ok || data.status === "error") {
    const detail = formatApiDetail(data.detail);
    const msg = data.message || detail || `HTTP ${response.status}`;
    throw new Error(msg);
  }
  return data;
}

function formatApiDetail(detail) {
  if (detail == null || detail === "") return "";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((e) => {
        if (e && typeof e === "object" && e.msg) return String(e.msg);
        if (e && typeof e === "object" && e.message) return String(e.message);
        return String(e);
      })
      .filter(Boolean)
      .join("; ");
  }
  return String(detail);
}

function setActiveSection(section) {
  state.activeSection = section;
  document.querySelectorAll(".nav-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.section === section);
  });
  document.querySelectorAll(".side-panel").forEach((el) => {
    el.classList.toggle("visible", el.dataset.panel === section);
  });
  document.querySelectorAll(".tab").forEach((el) => {
    el.classList.toggle("active", el.dataset.target === section);
  });
}

function bindNavigation() {
  document.querySelectorAll(".nav-item").forEach((el) => {
    el.addEventListener("click", () => setActiveSection(el.dataset.section));
  });
  document.querySelectorAll(".tab").forEach((el) => {
    el.addEventListener("click", () => setActiveSection(el.dataset.target));
  });
  $("go-unique-btn").addEventListener("click", () => setActiveSection("uniqualizer"));
  $("go-accounts-btn").addEventListener("click", () => setActiveSection("accounts"));
  $("go-settings-btn").addEventListener("click", () => setActiveSection("settings"));
}

function renderTenant() {
  const tenantSelect = $("tenant-id-select");
  if (![...tenantSelect.options].some((opt) => opt.value === state.tenantId)) {
    const opt = document.createElement("option");
    opt.value = state.tenantId;
    opt.textContent = state.tenantId;
    tenantSelect.appendChild(opt);
  }
  tenantSelect.value = state.tenantId;
  $("tenant-input").value = state.tenantId;
  $("tenant-badge").textContent = state.tenantId.slice(0, 1).toUpperCase();
  $("tenant-status-text").textContent = `Tenant: ${state.tenantId}`;
}

function renderDestSelector() {
  const isDownload = state.renderDest === "download";
  $("dest-download-btn").classList.toggle("active", isDownload);
  $("dest-antidetect-btn").classList.toggle("active", !isDownload);
  const antiRow = $("antidetect-row");
  if (antiRow) antiRow.style.display = isDownload ? "none" : "grid";
  const runBtn = $("run-uniqualizer-btn");
  if (runBtn) {
    runBtn.textContent = isDownload
      ? "▶  Запустить рендер"
      : "▶  Рендер + залив в антидетект";
  }
  updateSettingsSummary();
}

// ─── Thumbnail generator ──────────────────────────────────────────────────────
function releaseVideoBlob(video, url) {
  try {
    video.pause();
    video.removeAttribute("src");
    video.load();
  } catch (_) {
    /* ignore */
  }
  // Сразу после seeked revoke даёт net::ERR_FILE_NOT_FOUND — декодер ещё держит blob
  setTimeout(() => {
    try {
      URL.revokeObjectURL(url);
    } catch (_) {
      /* ignore */
    }
  }, 400);
}

async function generateThumbnail(file) {
  return new Promise((resolve) => {
    const video = document.createElement("video");
    video.muted = true;
    video.playsInline = true;
    video.preload = "auto";
    const url = URL.createObjectURL(file);
    video.src = url;

    let settled = false;
    const finish = (dataUrl) => {
      if (settled) return;
      settled = true;
      resolve(dataUrl);
    };

    const fail = () => {
      releaseVideoBlob(video, url);
      finish(null);
    };

    const draw = () => {
      try {
        const canvas = $("thumb-canvas");
        if (!canvas) {
          fail();
          return;
        }
        canvas.width = 180;
        canvas.height = 320;
        const ctx = canvas.getContext("2d");
        if (!ctx) {
          fail();
          return;
        }
        ctx.drawImage(video, 0, 0, 180, 320);
        releaseVideoBlob(video, url);
        finish(canvas.toDataURL("image/jpeg", 0.82));
      } catch {
        fail();
      }
    };

    // Таймаут: .mov / кодеки без seeked — не висеть вечно
    const timer = setTimeout(() => {
      video.removeEventListener("seeked", onSeeked);
      video.removeEventListener("loadeddata", onLoaded);
      fail();
    }, 12000);

    function onSeeked() {
      clearTimeout(timer);
      video.removeEventListener("seeked", onSeeked);
      draw();
    }

    function onLoaded() {
      const d = video.duration;
      const t =
        Number.isFinite(d) && d > 0 ? Math.min(1, Math.max(0.05, d * 0.1)) : 0.05;
      try {
        video.currentTime = t;
      } catch {
        clearTimeout(timer);
        fail();
      }
    }

    video.addEventListener("seeked", onSeeked);
    video.addEventListener("loadeddata", onLoaded, { once: true });
    video.addEventListener("error", () => {
      clearTimeout(timer);
      fail();
    });
  });
}

async function updateThumbnail() {
  const img = $("thumb-img");
  const empty = $("thumb-empty");
  const overlay = $("thumb-overlay");
  if (!state.files.length) {
    img.style.display = "none";
    if (overlay) overlay.style.display = "none";
    if (empty) empty.style.display = "flex";
    return;
  }
  const dataUrl = await generateThumbnail(state.files[0]);
  if (dataUrl) {
    img.src = dataUrl;
    img.style.display = "block";
    if (empty) empty.style.display = "none";
    if (overlay) {
      overlay.textContent = state.files[0].name.split(/[\\/]/).pop();
      overlay.style.display = "block";
    }
  }
}

// ─── Wizard step indicator ────────────────────────────────────────────────────
function updateWizardSteps() {
  const hasFiles = state.files.length > 0;
  $("wstep-1")?.classList.toggle("active", true);
  $("wstep-2")?.classList.toggle("active", hasFiles);
  $("wstep-3")?.classList.toggle("active", hasFiles);
  $("wstep-4")?.classList.toggle("active", hasFiles);
}

function renderOverlayFilePill() {
  const el = $("overlay-file-pill");
  if (!el) return;
  const p = (state.overlayMediaPath || "").trim();
  el.textContent = p
    ? `Слой: ${p.split(/[/\\\\]/).pop()}`
    : "Слой: стандартный data/overlay.png";
}

function renderSrtFilePill() {
  const el = $("srt-file-pill");
  if (!el) return;
  const p = (state.subtitleSrtPath || "").trim();
  el.textContent = p ? `SRT: ${p.split(/[/\\\\]/).pop()}` : "SRT не выбран";
}

function fillOverlayBlendSelect(blends) {
  const sel = $("overlay-blend-select");
  if (!sel) return;
  const keep = sel.value;
  sel.innerHTML = "";
  const entries =
    blends && typeof blends === "object" ? Object.entries(blends) : [];
  if (!entries.length) {
    sel.innerHTML = '<option value="normal">Обычное наложение</option>';
    return;
  }
  entries.sort((a, b) => String(a[1]).localeCompare(String(b[1]), "ru"));
  for (const [k, label] of entries) {
    const o = document.createElement("option");
    o.value = k;
    o.textContent = label;
    sel.appendChild(o);
  }
  if (keep && [...sel.options].some((x) => x.value === keep)) sel.value = keep;
}

async function uploadOverlayLayerFile() {
  const inp = $("overlay-file-input");
  if (!inp?.files?.length) {
    showToast("Сначала выберите файл (картинка или видео).", "err");
    return;
  }
  try {
    const form = new FormData();
    form.append("file", inp.files[0]);
    form.append("purpose", "overlay");
    const headers = new Headers();
    headers.set("X-Tenant-ID", state.tenantId);
    const res = await fetch(apiUrl("/api/upload"), {
      method: "POST",
      headers,
      body: form,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.status === "error") {
      throw new Error(data.message || `Ошибка ${res.status}`);
    }
    state.overlayMediaPath = data.overlay_media_path || data.path || "";
    inp.value = "";
    renderOverlayFilePill();
    await saveUniqualizerSettings(true);
    showToast("Слой загружен и применён.", "ok");
    updateSettingsSummary();
  } catch (e) {
    showToast(e.message || "Не удалось загрузить слой.", "err");
  }
}

async function uploadSrtFile() {
  const inp = $("srt-file-input");
  if (!inp?.files?.length) {
    showToast("Выберите файл .srt", "err");
    return;
  }
  const f = inp.files[0];
  if (!String(f.name || "").toLowerCase().endsWith(".srt")) {
    showToast("Нужен файл с расширением .srt", "err");
    inp.value = "";
    return;
  }
  try {
    const form = new FormData();
    form.append("file", f);
    form.append("purpose", "srt");
    const headers = new Headers();
    headers.set("X-Tenant-ID", state.tenantId);
    const res = await fetch(apiUrl("/api/upload"), { method: "POST", headers, body: form });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.status === "error") {
      throw new Error(data.message || `Ошибка ${res.status}`);
    }
    state.subtitleSrtPath = data.subtitle_srt_path || data.path || "";
    inp.value = "";
    renderSrtFilePill();
    await saveUniqualizerSettings(true);
    showToast("SRT загружен и будет вшит при рендере (нужен FFmpeg с libass).", "ok");
    updateSettingsSummary();
  } catch (e) {
    showToast(e.message || "Не удалось загрузить SRT.", "err");
  }
}

// ─── Template big preview ─────────────────────────────────────────────────────
function updateTemplateBigPreview(tmpl) {
  const top = $("tpb-top");
  const bot = $("tpb-bot");
  const bar = $("tpb-bar");
  const sub = $("tpb-sub");
  if (!top) return;

  top.style.display = "block";
  bot.style.display = "none";
  bar.style.display = "none";
  sub.style.display = "none";
  top.style.background = "rgba(255,71,87,0.22)";
  top.style.flex = "1";

  if (tmpl === "reaction") {
    top.style.flex = "1";
    bot.style.display = "block";
    bot.style.flex = "1";
    bot.style.background = "rgba(80,80,110,0.4)";
  } else if (tmpl === "news") {
    bar.style.display = "block";
    const hasText = ($("subtitle-input")?.value || "").trim();
    if (hasText) sub.style.display = "block";
  } else if (tmpl === "story") {
    top.style.background = "linear-gradient(to right, rgba(0,0,0,0.4) 15%, rgba(255,71,87,0.28) 15% 85%, rgba(0,0,0,0.4) 85%)";
  } else if (tmpl === "ugc") {
    top.style.background = "radial-gradient(ellipse at center, rgba(255,71,87,0.35) 35%, rgba(255,71,87,0.06) 100%)";
  }

  const hasSubtitle = ($("subtitle-input")?.value || "").trim();
  if (hasSubtitle && tmpl !== "news") sub.style.display = "block";
}

// ─── Settings summary ─────────────────────────────────────────────────────────
const presetLabels = { standard: "Стандарт", soft: "Мягко", deep: "Глубокий", ultra: "Ультра" };
const overlayModeLabels = {
  on_top: "Поверх",
  under_video: "Под видео",
};
const overlayPositionLabels = {
  center: "центр",
  top: "сверху",
  bottom: "снизу",
  top_left: "верх-слева",
  top_right: "верх-справа",
  bottom_left: "низ-слева",
  bottom_right: "низ-справа",
};
const subtitleStyleLabels = {
  default: "Обычный",
  readable: "Крупнее + обводка",
};
const templateLabels = {
  default: "Стандарт", reaction: "Реакция",
  news: "Новости", story: "Story", ugc: "UGC",
};

function updateSettingsSummary() {
  try {
    const sub = ($("subtitle-input")?.value || "").trim();
    const geo = $("geo-city-select")?.value || "busan";
    const geoLabel = { busan: "Busan, KR", seoul: "Seoul, KR", incheon: "Incheon, KR" }[geo] || geo;
    const geoOn = !$("geo-toggle")?.classList.contains("off");
    const isDownload = state.renderDest === "download";
    const srtOk = Boolean(state.subtitleSrtPath);

    const setVal = (id, val) => { const el = $(id); if (el) el.textContent = val; };
    setVal("sum-preset",   presetLabels[state.preset] || state.preset);
    setVal("sum-template", templateLabels[state.template] || state.template);
    const om = $("overlay-mode-select")?.value || "on_top";
    const op = $("overlay-position-select")?.value || "center";
    const blendShort = ($("overlay-blend-select")?.value || "normal").slice(0, 12);
    const opct = $("overlay-opacity-range")?.value || "100";
    const ovLine =
      om === "under_video"
        ? `${overlayModeLabels.under_video || om} · ${blendShort} · ${opct}%`
        : `${overlayModeLabels.on_top || om} · ${overlayPositionLabels[op] || op} · ${blendShort} · ${opct}%`;
    setVal("sum-overlay", ovLine);
    const ss = $("subtitle-style-select")?.value || "default";
    setVal("sum-sub-style", subtitleStyleLabels[ss] || ss);
    let subLine = sub ? `${sub.slice(0, 72)}${sub.length > 72 ? "…" : ""}` : "—";
    if (srtOk) subLine += ` · SRT: ${state.subtitleSrtPath.split(/[/\\\\]/).pop()}`;
    setVal("sum-subtitle", subLine);
    setVal("sum-geo",      geoOn ? geoLabel : "Выключено");
    setVal("sum-files",    `${state.files.length} файл${state.files.length !== 1 ? "а" : ""}`);
    setVal("sum-dest",     isDownload ? "Скачать" : "В антидетект");

    updateTemplateBigPreview(state.template);
    updateWizardSteps();
  } catch (e) {
    console.warn("updateSettingsSummary", e);
  }
}

function renderFileSelection() {
  const files = state.files;
  const isDownload = state.renderDest === "download";
  $("copy-summary").innerHTML =
    `Видео выбрано: <span style="color:#ff4757;font-weight:600;">${files.length}</span>. ` +
    (isDownload
      ? "Рендер → файл будет готов к скачиванию."
      : "Рендер + AI + YouTube-залив через антидетект.");
  const box = $("selected-files-list");
  if (!files.length) {
    box.innerHTML = '<div class="empty-state">Файлы не выбраны</div>';
    updateSettingsSummary();
    return;
  }
  box.innerHTML = files
    .map(
      (file, idx) => `
        <div class="file-item">
          <span>${escapeHtml(file.name)}</span>
          <span class="file-mult">
            ${(file.size / 1024 / 1024).toFixed(1)} MB
            <button class="link-btn" data-remove-file="${idx}">убрать</button>
          </span>
        </div>
      `
    )
    .join("");
  box.querySelectorAll("[data-remove-file]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.files.splice(Number(btn.dataset.removeFile), 1);
      renderFileSelection();
      updateThumbnail();
    });
  });
  updateSettingsSummary();
}

function renderProfiles() {
  const profiles = state.profiles;
  const select = $("profile-select");
  const warmup = $("warmup-profiles-box");
  const accounts = $("profiles-list-box");
  if (!profiles.length) {
    select.innerHTML = '<option value="">Нет профилей</option>';
    accounts.innerHTML = '<div class="empty-state">Пока нет профилей. Нажмите «Проверить и синхронизировать».</div>';
    warmup.innerHTML = '<div class="empty-state">Сначала синхронизируйте профили из AdsPower.</div>';
    return;
  }
  select.innerHTML = profiles
    .map((p) => `<option value="${escapeHtml(p.adspower_id)}">${escapeHtml(p.name || p.adspower_id)}</option>`)
    .join("");
  accounts.innerHTML = profiles
    .map(
      (p) => `
        <div class="profile-item">
          <div><span class="profile-dot"></span>${escapeHtml(p.name || p.adspower_id)}</div>
          <span class="profile-count mono">${escapeHtml(p.adspower_id)}</span>
        </div>
      `
    )
    .join("");
  warmup.innerHTML = profiles
    .slice(0, 20)
    .map(
      (p) => `
        <div class="profile-item">
          <div><span class="profile-dot"></span>${escapeHtml(p.name || p.adspower_id)}</div>
          <span class="profile-count">${escapeHtml(p.status || "idle")}</span>
        </div>
      `
    )
    .join("");
}

function renderTasks() {
  const tasks = state.tasks;
  $("stat-tasks").textContent = String(tasks.length);
  $("stat-pending").textContent = String(tasks.filter((t) => t.status === "pending").length);
  $("stat-success").textContent = String(tasks.filter((t) => t.status === "success").length);
  $("stat-errors").textContent = String(tasks.filter((t) => t.status === "error").length);
  $("queue-pill").textContent =
    `Очередь: pending ${tasks.filter((t) => t.status === "pending").length} · rendering ${tasks.filter((t) => t.status === "rendering").length} · uploading ${tasks.filter((t) => t.status === "uploading").length}`;

  const rows = tasks.length
    ? tasks
        .map(
          (t) => {
            const canDownload = t.render_only && t.status === "success" && t.unique_video;
            const canCancel = t.status === "rendering" || t.status === "uploading";
            const cancelBtn = canCancel
              ? `<button type="button" class="action-btn danger secondary btn-cancel-task" data-task-id="${t.id}" style="padding:4px 8px;font-size:11px;margin-right:6px;vertical-align:middle;">Отменить</button>`
              : "";
            const downloadCell = canDownload
              ? `<a class="download-btn" href="${escapeHtml(apiUrl(`/api/tasks/${t.id}/download?X-Tenant-ID=${encodeURIComponent(state.tenantId)}`))}" download>⬇ Скачать</a>`
              : t.render_only
                ? `<span style="color:#666;font-size:11px;">${t.status === "pending" || t.status === "rendering" ? "..." : "—"}</span>`
                : `<span style="color:#666;font-size:11px;">антидетект</span>`;
            return `
            <tr>
              <td>${t.id}</td>
              <td class="task-title" title="${escapeHtml(t.original_video)}">${escapeHtml(t.original_video.split(/[\\/]/).pop())}</td>
              <td class="mono">${escapeHtml(t.target_profile || "—")}</td>
              <td><span class="status-badge ${statusClass(t.status)}">${escapeHtml(t.status)}</span></td>
              <td class="task-title" title="${escapeHtml(t.unique_video || "")}">${escapeHtml((t.unique_video || "").split(/[\\/]/).pop() || "—")}</td>
              <td class="task-error" title="${escapeHtml(t.error_message || "")}">${escapeHtml(t.error_message || "—")}</td>
              <td>${cancelBtn}${downloadCell}</td>
            </tr>
          `;
          }
        )
        .join("")
    : '<tr><td colspan="7"><div class="empty-state">Задач пока нет.</div></td></tr>';

  $("tasks-table-body").innerHTML = rows;
  $("dashboard-tasks-body").innerHTML = tasks.length
    ? tasks
        .slice(0, 8)
        .map(
          (t) => `
          <tr>
            <td>${t.id}</td>
            <td class="task-title">${escapeHtml(t.original_video.split(/[\\/]/).pop())}</td>
            <td class="mono">${escapeHtml(t.target_profile)}</td>
            <td><span class="status-badge ${statusClass(t.status)}">${escapeHtml(t.status)}</span></td>
            <td class="task-error" title="${escapeHtml(t.error_message || "")}">${escapeHtml(t.error_message || "—")}</td>
          </tr>
        `
        )
        .join("")
    : '<tr><td colspan="5"><div class="empty-state">Последних задач пока нет.</div></td></tr>';
}

function renderAnalytics() {
  const items = state.analytics;
  $("analytics-total-videos").textContent = String(items.length);
  $("analytics-total-views").textContent = formatNumber(items.reduce((sum, item) => sum + Number(item.views || 0), 0));
  $("analytics-total-likes").textContent = formatNumber(items.reduce((sum, item) => sum + Number(item.likes || 0), 0));
  $("analytics-shadowban").textContent = String(items.filter((i) => i.status === "shadowban").length);
  $("analytics-banned").textContent = String(items.filter((i) => i.status === "banned").length);
  $("stat-views").textContent = formatNumber(items.reduce((sum, item) => sum + Number(item.views || 0), 0));

  $("analytics-table-body").innerHTML = items.length
    ? items
        .map(
          (row) => `
          <tr>
            <td>${row.id}</td>
            <td class="task-title" title="${escapeHtml(row.video_url)}">${escapeHtml(row.video_url)}</td>
            <td class="views">${formatNumber(row.views)}</td>
            <td style="color:#ff4757;">${formatNumber(row.likes)}</td>
            <td><span class="status-badge ${statusClass(row.status)}">${escapeHtml(row.status)}</span></td>
          </tr>
        `
        )
        .join("")
    : '<tr><td colspan="5"><div class="empty-state">Пока нет аналитики.</div></td></tr>';
}

function renderHealth() {
  if (!state.health) return;
  $("tenant-badge").textContent = state.health.tenant_id.slice(0, 1).toUpperCase();
}

function renderSystemStatus() {
  const sys = state.system;
  const ads = state.adspower;
  const groq = state.groq;
  const ping = state.integrationsPing;
  if (!sys) return;

  let groqLine = sys.groq_configured ? `Ключ (${groq?.masked || "скрыт"})` : "Ключ не задан";
  let groqKind = sys.groq_configured ? "good" : "warn";
  if (ping?.status === "ok" && ping.groq) {
    groqLine += ` · ${ping.groq.live ? "✓ " : "✗ "}${ping.groq.message || ""}`;
    groqKind = ping.groq.live ? "good" : "warn";
  } else if (ping?.status === "error") {
    groqLine += " · проверка не выполнена";
    groqKind = "warn";
  }

  const adsBase = ads?.api_base || sys.adspower_api_base || "—";
  let adsApiLine = adsBase;
  let adsApiKind = "good";
  if (ping?.status === "ok" && ping.adspower) {
    adsApiLine = `${adsBase} · ${ping.adspower.live ? "✓ " : "✗ "}${ping.adspower.message || ""}`;
    if (!ping.adspower.live) adsApiKind = "warn";
    if (ping.adspower.live && ping.adspower.profiles_count != null) {
      adsApiLine += ` (${ping.adspower.profiles_count} проф.)`;
    }
  } else if (ping?.status === "error") {
    adsApiLine = `${adsBase} · проверка не выполнена`;
    adsApiKind = "warn";
  }

  let ffmpegLine = "Не найден";
  let ffmpegKind = "warn";
  if (sys.ffmpeg_runs) {
    const ver = (sys.ffmpeg_version || "OK").slice(0, 72);
    ffmpegLine = `${sys.ffmpeg_bin} · ${ver}`;
    ffmpegKind = "good";
  } else if (sys.ffmpeg_found) {
    ffmpegLine = `${sys.ffmpeg_bin} (путь есть, запуск не удался: ${(sys.ffmpeg_version || "?").slice(0, 48)})`;
    ffmpegKind = "warn";
  } else {
    ffmpegLine = `${sys.ffmpeg_bin || "ffmpeg"} не в PATH`;
  }

  const lines = [
    ["Overlay PNG", sys.overlay_exists ? "Готов" : "Не найден", sys.overlay_exists ? "good" : "warn"],
    ["FFmpeg", ffmpegLine, ffmpegKind],
    ["Groq", groqLine, groqKind],
    ["AdsPower API", adsApiLine, adsApiKind],
    ["AdsPower Auth", sys.adspower_use_auth ? "Bearer включен" : "Выключен", sys.adspower_use_auth ? "good" : "warn"],
    ["AdsPower API Key", sys.adspower_api_key_configured ? "Задан" : "Не задан", sys.adspower_api_key_configured ? "good" : "warn"],
  ];

  const html = lines
    .map(
      ([label, value, kind]) => `
        <div class="status-line">
          <span>${escapeHtml(label)}</span>
          <span class="mini-badge ${kind}">${escapeHtml(value)}</span>
        </div>
      `
    )
    .join("");

  $("system-status-lines").innerHTML = html;
  $("settings-status-lines").innerHTML = html;
  if (ping?.status === "ok" && ping.groq) {
    $("groq-status-text").textContent = ping.groq.live
      ? `Ключ OK · ${ping.groq.message || "Groq доступен"}`
      : `${sys.groq_configured ? "Ключ задан, но " : ""}${ping.groq.message || "ошибка"}`;
  } else {
    $("groq-status-text").textContent = sys.groq_configured ? "Ключ сохранён (живая проверка недоступна)" : "Ключ не задан";
  }
  $("ads-base-text").textContent = adsApiLine;
}

function renderAdsPowerDetails(message = "") {
  const ads = state.adspower || {};
  const profilesCount = state.profiles.length;
  const ping = state.integrationsPing;
  let liveLine = message || "Ещё не запускали";
  let liveKind = message ? "good" : "warn";
  if (ping?.status === "ok" && ping.adspower) {
    liveLine = ping.adspower.live
      ? `${ping.adspower.message}${ping.adspower.profiles_count != null ? ` · ${ping.adspower.profiles_count} в API` : ""}`
      : ping.adspower.message || "Нет связи";
    liveKind = ping.adspower.live ? "good" : "warn";
  } else if (ping?.status === "error") {
    liveLine = "Автопроверка не удалась";
    liveKind = "warn";
  }
  $("ads-status-lines").innerHTML = `
    <div class="status-line"><span>Текущий API</span><span class="mini-badge good mono">${escapeHtml(ads.api_base || "—")}</span></div>
    <div class="status-line"><span>API Key</span><span class="mini-badge ${ads.api_key_configured ? "good" : "warn"}">${escapeHtml(ads.api_key_masked || (ads.api_key_configured ? "Задан" : "Не задан"))}</span></div>
    <div class="status-line"><span>Проверка API</span><span class="mini-badge ${ads.use_auth ? "good" : "warn"}">${ads.use_auth ? "Включена" : "Выключена"}</span></div>
    <div class="status-line"><span>Профилей в базе</span><span class="mini-badge good">${profilesCount}</span></div>
    <div class="status-line"><span>Связь с антидетектом</span><span class="mini-badge ${liveKind}">${escapeHtml(liveLine)}</span></div>
  `;
}

function renderGeoInjection() {
  const cityKey = $("geo-city-select")?.value || "busan";
  const profile = geoProfiles[cityKey] || geoProfiles.busan;
  const jitter = Number($("geo-jitter-range")?.value || 5) / 100;
  $("geo-lat").textContent = profile.lat;
  $("geo-lng").textContent = profile.lng;
  $("geo-city-note").textContent = profile.city;
  $("geo-jitter-note").textContent = `${profile.city} jitter ${jitter.toFixed(2)}`;
}

const presetHints = {
  standard: "Стандарт: saturation 1.02–1.12, CRF 26, veryfast, audio 128k",
  soft:     "Мягко: почти без «пережима» — малые правки цвета/темпа, CRF 22, medium, tune film (x264)",
  deep:     "Глубокий: saturation 1.2–1.8, CRF 23, fast, audio 192k + unsharp",
  ultra:    "Ультра: saturation 1.35–2.0, CRF 20, slow, audio 256k + zoom",
};

const templateHints = {
  default:  "Стандарт: один видеопоток + прозрачный overlay",
  reaction: "Реакция: split-screen 9:16 — оригинал сверху, зеркало снизу",
  news:     "Новости: нижняя плашка + callout текст",
  story:    "Story: кроп центра до 9:16 + верхняя подпись",
  ugc:      "UGC: минимум фильтров + виньетка — органичный вид",
};

function applyPresetUI(preset) {
  state.preset = preset;
  document.querySelectorAll(".preset-btn[data-preset]").forEach((x) => {
    x.classList.toggle("active-preset", x.dataset.preset === preset);
  });
  const hintEl = $("preset-hint-text");
  if (hintEl) hintEl.textContent = presetHints[preset] || "";
  updateSettingsSummary();
}

function syncOverlayPositionControl() {
  const modeEl = $("overlay-mode-select");
  const posEl = $("overlay-position-select");
  if (!modeEl || !posEl) return;
  const under = modeEl.value === "under_video";
  posEl.disabled = under;
  posEl.style.opacity = under ? "0.5" : "";
}

function applyTemplateUI(tmpl) {
  state.template = tmpl;
  // template buttons use .tmpl-btn now
  document.querySelectorAll(".tmpl-btn[data-tmpl]").forEach((x) => {
    x.classList.toggle("active-preset", x.dataset.tmpl === tmpl);
  });
  const hintEl = $("template-hint-text");
  if (hintEl) hintEl.textContent = templateHints[tmpl] || "";
  updateSettingsSummary();
}

function applyUniqualizerSettingsToForm() {
  const settings = state.uniqualizer || {};
  $("niche-input").value = settings.niche || $("niche-input").value;
  $("device-select").value = settings.device_model || $("device-select").value;
  $("geo-city-select").value = settings.geo_profile || "busan";
  $("geo-toggle").classList.toggle("off", settings.geo_enabled === false);
  $("geo-jitter-range").value = String(Math.round(Number(settings.geo_jitter || 0.05) * 100));
  if (settings.preset) applyPresetUI(settings.preset);
  if (settings.template) applyTemplateUI(settings.template);
  const omSel = $("overlay-mode-select");
  if (omSel && settings.overlay_mode) omSel.value = settings.overlay_mode;
  const opSel = $("overlay-position-select");
  if (opSel && settings.overlay_position) opSel.value = settings.overlay_position;
  const ssSel = $("subtitle-style-select");
  if (ssSel && settings.subtitle_style) ssSel.value = settings.subtitle_style;
  syncOverlayPositionControl();
  state.overlayMediaPath = settings.overlay_media_path || "";
  renderOverlayFilePill();
  const bsel = $("overlay-blend-select");
  if (bsel && settings.overlay_blend_mode) bsel.value = settings.overlay_blend_mode;
  const orng = $("overlay-opacity-range");
  if (orng) {
    const pct = Math.round(Number(settings.overlay_opacity != null ? settings.overlay_opacity : 1) * 100);
    orng.value = String(Math.min(100, Math.max(5, pct)));
    const ovl = $("overlay-opacity-val");
    if (ovl) ovl.textContent = orng.value;
  }
  if (settings.subtitle !== undefined) {
    const subEl = $("subtitle-input");
    if (subEl) subEl.value = settings.subtitle;
  }
  state.subtitleSrtPath = settings.subtitle_srt_path || "";
  renderSrtFilePill();
  renderGeoInjection();
  updateSettingsSummary();
}

function renderDashboardCounts() {
  $("stat-profiles").textContent = String(state.profiles.length);
}

function renderAiPreviewBox(meta) {
  if (!meta || meta.status === "error") {
    state.lastAiPreview = null;
    $("ai-preview-box").innerHTML = '<div class="empty-state">Не удалось получить превью AI.</div>';
    return;
  }
  state.lastAiPreview = meta;
  const ov = (meta.overlay_text || "").trim();
  $("ai-preview-box").innerHTML = `
    <div class="info-box">
      <div class="info-label">Title</div>
      <div class="info-value">${escapeHtml(meta.title || "—")}</div>
    </div>
    <div class="info-box">
      <div class="info-label">Description</div>
      <div class="info-value">${escapeHtml(meta.description || "—")}</div>
    </div>
    <div class="info-box">
      <div class="info-label">Comment</div>
      <div class="info-value">${escapeHtml(meta.comment || "—")}</div>
    </div>
    <div class="info-box">
      <div class="info-label">Текст на видео</div>
      <div class="info-value">${escapeHtml(ov || "—")}</div>
    </div>
    <div class="step-actions-row" style="margin-top:8px;">
      <button type="button" class="action-btn" id="insert-overlay-ai-btn" ${ov ? "" : "disabled"}>Вставить в поле «Текст на видео» (шаг 2)</button>
    </div>
  `;
  const ins = $("insert-overlay-ai-btn");
  if (ins && ov) {
    ins.addEventListener("click", () => {
      const t = (state.lastAiPreview && state.lastAiPreview.overlay_text || "").trim();
      if (!t) return;
      const el = $("subtitle-input");
      if (el) el.value = t;
      updateSettingsSummary();
      saveUniqualizerSettings(true);
      showToast("Текст вставлен. Проверьте шаг 2 уникализатора.", "ok");
    });
  }
}

async function loadCore(silent = false) {
  const [health, system, adsStatus, groq, uniqualizer, profiles, tasks, analytics] = await Promise.all([
    api("/api/health"),
    api("/api/system/status"),
    api("/api/adspower/status"),
    api("/api/settings/groq"),
    api("/api/uniqualizer/settings"),
    api("/api/profiles"),
    api("/api/tasks?limit=100"),
    api("/api/analytics?limit=200"),
  ]);
  state.health = health;
  state.system = system;
  state.adspower = adsStatus;
  state.groq = groq;
  state.uniqualizer = uniqualizer;
  fillOverlayBlendSelect(uniqualizer.available_overlay_blends);
  if (!silent) {
    try {
      state.integrationsPing = await api("/api/integrations/ping");
    } catch (e) {
      state.integrationsPing = {
        status: "error",
        message: e.message || "ping failed",
        groq: { live: false, message: "—" },
        adspower: { live: false, message: "—" },
      };
    }
  }
  state.subtitleSrtPath = uniqualizer.subtitle_srt_path || "";
  state.overlayMediaPath = uniqualizer.overlay_media_path || "";
  state.profiles = profiles.profiles || [];
  state.tasks = tasks.tasks || [];
  state.analytics = analytics.analytics || [];
  $("adspower-api-input").value = state.adspower?.api_base || "";
  $("adspower-api-key-input").value = "";
  $("adspower-auth-toggle").classList.toggle("off", !state.adspower?.use_auth);
  $("groq-key-input").value = "";
  renderTenant();
  renderHealth();
  renderProfiles();
  renderTasks();
  renderAnalytics();
  renderSystemStatus();
  renderDashboardCounts();
  renderAdsPowerDetails();
  applyUniqualizerSettingsToForm();
  renderDestSelector();
  if (!tasksLookBusy(state.tasks)) {
    state.renderProgressDismissed = false;
  }
  if (tasksLookBusy(state.tasks) && !state.renderProgressDismissed) {
    startRenderProgressPolling();
  }
}

async function refreshAll(silent = false) {
  try {
    await loadCore(silent);
  } catch (error) {
    if (!silent) showToast(error.message || "Не удалось обновить данные.", "err");
  }
}

async function uploadAndCreateTasks() {
  if (!state.files.length) {
    showToast("Сначала выберите хотя бы один файл.", "err");
    return;
  }

  const isDownload = state.renderDest === "download";
  const profileId = $("profile-select").value;

  if (!isDownload && !profileId) {
    showToast("Для залива в антидетект выберите профиль AdsPower.", "err");
    return;
  }

  const runBtn = $("run-uniqualizer-btn");
  runBtn.disabled = true;
  runBtn.textContent = "Обработка...";
  try {
    await saveUniqualizerSettings(true);
    await api("/api/pipeline/start", { method: "POST" });
    let created = 0;
    for (const file of state.files) {
      const form = new FormData();
      form.append("file", file);
      const uploaded = await api("/api/upload", { method: "POST", body: form });
      await api("/api/tasks", {
        method: "POST",
        body: JSON.stringify({
          original_video: uploaded.path,
          target_profile: isDownload ? "" : profileId,
          render_only: isDownload,
        }),
      });
      created += 1;
    }
    const enqueue = await api("/api/pipeline/enqueue-pending", { method: "POST" });
    state.pipelineRunning = true;
    state.files = [];
    renderFileSelection();
    await refreshAll(true);
    if (isDownload) {
      $("pipeline-status-text").textContent = `Рендер запущен. Файлы появятся в таблице.`;
      showToast(`Рендер запущен: ${created} видео. Когда готово — кнопка «Скачать» в таблице.`, "ok");
    } else {
      $("pipeline-status-text").textContent = `Очередь запущена. Добавлено задач: ${enqueue.enqueued ?? created}`;
      showToast(`Готово: ${created} видео отправлено в очередь на залив.`, "ok");
    }
    state.renderProgressDismissed = false;
    startRenderProgressPolling();
    try {
      await fetchRenderProgressOnce();
    } catch (_) {
      /* ignore */
    }
    setActiveSection("uploads");
  } catch (error) {
    showToast(error.message || "Не удалось создать задачи.", "err");
  } finally {
    runBtn.disabled = false;
    renderDestSelector();
  }
}

async function generateVariantsBatch() {
  if (!state.files.length) {
    showToast("Сначала выберите один исходный файл.", "err");
    return;
  }
  const isDownload = state.renderDest === "download";
  const profileId = $("profile-select").value;
  if (!isDownload && !profileId) {
    showToast("Для залива в антидетект выберите профиль AdsPower.", "err");
    return;
  }
  const cntRaw = Number($("variants-count-input")?.value || 10);
  const count = Math.max(1, Math.min(50, Number.isFinite(cntRaw) ? Math.round(cntRaw) : 10));
  const btn = $("variants-generate-btn");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Генерация...";
  }
  try {
    await saveUniqualizerSettings(true);
    const first = state.files[0];
    const form = new FormData();
    form.append("file", first);
    const uploaded = await api("/api/upload", { method: "POST", body: form });
    const res = await api("/api/variants/generate", {
      method: "POST",
      body: JSON.stringify({
        source_video: uploaded.path,
        target_profile: isDownload ? "" : profileId,
        render_only: isDownload,
        count,
        enqueue: true,
        auto_start_pipeline: true,
      }),
    });
    state.pipelineRunning = true;
    await refreshAll(true);
    state.renderProgressDismissed = false;
    startRenderProgressPolling();
    try {
      await fetchRenderProgressOnce();
    } catch (_) {
      /* ignore */
    }
    $("pipeline-status-text").textContent =
      `Варианты: создано ${res.created ?? count}, в очереди ${res.enqueued ?? count}`;
    showToast(`Сгенерировано ${res.created ?? count} задач из одного исходника.`, "ok");
    setActiveSection("uploads");
  } catch (error) {
    showToast(error.message || "Не удалось создать пакет вариантов.", "err");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "Сделать N вариантов";
    }
  }
}

async function saveUniqualizerSettings(silent = false) {
  try {
    const geoJitter = Number($("geo-jitter-range").value || 5) / 100;
    const subtitleEl = $("subtitle-input");
    let subText = subtitleEl ? subtitleEl.value.trim() : "";
    if (subText.length > 4000) subText = subText.slice(0, 4000);
    const nicheEl = $("niche-input");
    const result = await api("/api/uniqualizer/settings", {
      method: "POST",
      body: JSON.stringify({
        geo_enabled: !$("geo-toggle").classList.contains("off"),
        geo_profile: $("geo-city-select").value || "busan",
        geo_jitter: geoJitter,
        device_model: $("device-select").value || "Samsung SM-S928N",
        niche: nicheEl ? nicheEl.value.trim() || "YouTube Shorts" : "YouTube Shorts",
        preset: state.preset || "deep",
        template: state.template || "default",
        subtitle: subText,
        subtitle_srt_path: state.subtitleSrtPath || "",
        overlay_mode: $("overlay-mode-select")?.value || "on_top",
        overlay_position: $("overlay-position-select")?.value || "center",
        subtitle_style: $("subtitle-style-select")?.value || "default",
        overlay_media_path: state.overlayMediaPath || "",
        overlay_blend_mode: $("overlay-blend-select")?.value || "normal",
        overlay_opacity: Number($("overlay-opacity-range")?.value || 100) / 100,
      }),
    });
    state.uniqualizer = result;
    if (result.subtitle_srt_path !== undefined) {
      state.subtitleSrtPath = result.subtitle_srt_path || "";
    }
    if (result.overlay_media_path !== undefined) {
      state.overlayMediaPath = result.overlay_media_path || "";
    }
    renderGeoInjection();
    if (!silent) {
      showToast("Настройки уникализатора сохранены.", "ok");
    }
    return result;
  } catch (error) {
    if (!silent) {
      showToast(error.message || "Не удалось сохранить настройки уникализатора.", "err");
    }
    throw error;
  }
}

async function verifyAds(syncDb) {
  try {
    const result = await api(`/api/adspower/verify${syncDb ? "?sync_db=true" : ""}`);
    await refreshAll(false);
    showToast(result.message || "Проверка AdsPower завершена.", "ok");
  } catch (error) {
    showToast(error.message || "Проверка AdsPower не удалась.", "err");
    await refreshAll(false);
  }
}

async function saveAdsSettings() {
  try {
    const apiBase = $("adspower-api-input").value.trim();
    const apiKey = $("adspower-api-key-input").value.trim();
    const useAuth = !$("adspower-auth-toggle").classList.contains("off");
    const result = await api("/api/adspower/settings", {
      method: "POST",
      body: JSON.stringify({ api_base: apiBase, api_key: apiKey, use_auth: useAuth }),
    });
    state.adspower = {
      api_base: result.api_base,
      use_auth: result.use_auth,
      api_key_masked: result.api_key_masked,
      api_key_configured: Boolean(result.api_key_masked),
    };
    await refreshAll(false);
    showToast(result.message || "Настройки AdsPower сохранены.", "ok");
  } catch (error) {
    showToast(error.message || "Не удалось сохранить AdsPower URL.", "err");
  }
}

async function saveGroq(clear = false) {
  try {
    const key = clear ? "" : $("groq-key-input").value.trim();
    const result = await api("/api/settings/groq", {
      method: "POST",
      body: JSON.stringify({ key }),
    });
    await refreshAll(false);
    showToast(result.cleared ? "Ключ Groq очищен." : "Ключ Groq сохранён.", "ok");
  } catch (error) {
    showToast(error.message || "Не удалось сохранить ключ Groq.", "err");
  }
}

async function verifyGroqKey() {
  const btn = $("verify-groq-btn");
  const key = $("groq-key-input")?.value.trim() || "";
  try {
    if (btn) btn.disabled = true;
    const data = await api("/api/settings/groq/ping", {
      method: "POST",
      body: JSON.stringify({ key }),
    });
    if (state.integrationsPing && state.integrationsPing.status === "ok") {
      state.integrationsPing = {
        ...state.integrationsPing,
        groq: { live: data.live, message: data.message },
      };
    } else {
      state.integrationsPing = {
        status: "ok",
        groq: { live: data.live, message: data.message },
        adspower: state.integrationsPing?.adspower || { live: false, message: "—" },
      };
    }
    renderSystemStatus();
    const prefix = data.used_trial_key ? "Ключ из поля (не сохранён): " : "";
    $("groq-status-text").textContent = data.live
      ? `${prefix}${data.message || "Groq доступен"}`
      : `${prefix}${data.message || "Ошибка"}`;
    showToast(
      `${data.live ? "Groq OK" : "Groq"}: ${data.message || ""}${data.used_trial_key ? " (не забудьте сохранить)" : ""}`,
      data.live ? "ok" : "err"
    );
  } catch (error) {
    showToast(error.message || "Проверка Groq не удалась.", "err");
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function previewAI() {
  try {
    const niche = $("ai-niche-preview-input").value.trim() || $("niche-input").value.trim() || "YouTube Shorts";
    const meta = await api("/api/ai/preview", {
      method: "POST",
      body: JSON.stringify({ niche }),
    });
    renderAiPreviewBox(meta);
    if (meta.used_fallback) {
      showToast("AI ответил через fallback. Это безопасно для пайплайна.", "ok");
    } else {
      showToast("AI превью готово.", "ok");
    }
  } catch (error) {
    showToast(error.message || "Не удалось получить AI превью.", "err");
  }
}

async function checkAnalyticsUrl() {
  const url = $("check-url-input").value.trim();
  if (!url) {
    showToast("Введите ссылку на YouTube-видео.", "err");
    return;
  }
  try {
    const result = await api("/api/analytics/check", {
      method: "POST",
      body: JSON.stringify({ url }),
    });
    const msg =
      result.status === "active"
        ? `Видео активно. Просмотры: ${formatNumber(result.views)}`
        : result.status === "shadowban"
          ? "Возможен shadowban."
          : result.status === "banned"
            ? "Видео недоступно или заблокировано."
            : result.message || "Проверка завершена.";
    showToast(msg, result.status === "error" ? "err" : "ok");
  } catch (error) {
    showToast(error.message || "Не удалось проверить ссылку.", "err");
  }
}

async function startPipeline() {
  try {
    const result = await api("/api/pipeline/start", { method: "POST" });
    state.pipelineRunning = true;
    $("pipeline-status-text").textContent = result.message || "Очередь запущена";
    showToast(result.message || "Пайплайн запущен.", "ok");
    state.renderProgressDismissed = false;
    startRenderProgressPolling();
    try {
      await fetchRenderProgressOnce();
    } catch (_) {
      /* ignore */
    }
  } catch (error) {
    showToast(error.message || "Не удалось запустить пайплайн.", "err");
  }
}

async function stopPipeline() {
  try {
    await api("/api/pipeline/stop", { method: "POST" });
    state.pipelineRunning = false;
    state.renderProgressDismissed = false;
    stopRenderProgressPolling();
    $("pipeline-status-text").textContent = "Очередь остановлена";
    showToast("Пайплайн остановлен.", "ok");
  } catch (error) {
    showToast(error.message || "Не удалось остановить пайплайн.", "err");
  }
}

async function enqueuePending() {
  try {
    const result = await api("/api/pipeline/enqueue-pending", { method: "POST" });
    await refreshAll(true);
    showToast(`В очередь добавлено: ${result.enqueued || 0}`, "ok");
    state.renderProgressDismissed = false;
    startRenderProgressPolling();
    try {
      await fetchRenderProgressOnce();
    } catch (_) {
      /* ignore */
    }
  } catch (error) {
    showToast(error.message || "Не удалось добавить pending-задачи.", "err");
  }
}

function bindFileDrop() {
  const dropZone = $("drop-zone");
  const fileInput = $("video-input");

  const addFiles = (list) => {
    const incoming = Array.from(list || []);
    state.files.push(...incoming);
    renderFileSelection();
    updateThumbnail();
  };

  dropZone.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => addFiles(fileInput.files));
  ["dragenter", "dragover"].forEach((evt) =>
    dropZone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropZone.style.borderColor = "rgba(255, 71, 87, 0.7)";
    })
  );
  ["dragleave", "drop"].forEach((evt) =>
    dropZone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropZone.style.borderColor = "rgba(255, 71, 87, 0.3)";
    })
  );
  dropZone.addEventListener("drop", (e) => addFiles(e.dataTransfer.files));
  $("pick-files-btn").addEventListener("click", () => fileInput.click());
  $("clear-files-btn").addEventListener("click", () => {
    state.files = [];
    fileInput.value = "";
    renderFileSelection();
    updateThumbnail();
  });
}

function bindControls() {
  bindNavigation();
  bindFileDrop();

  $("run-uniqualizer-btn").addEventListener("click", uploadAndCreateTasks);
  $("variants-generate-btn")?.addEventListener("click", generateVariantsBatch);
  $("preview-ai-btn").addEventListener("click", previewAI);
  $("ai-preview-settings-btn").addEventListener("click", previewAI);
  $("save-ads-btn").addEventListener("click", saveAdsSettings);
  $("device-select").addEventListener("change", () => saveUniqualizerSettings(true));
  $("niche-input").addEventListener("change", () => saveUniqualizerSettings(true));
  $("verify-ads-btn").addEventListener("click", () => verifyAds(false));
  $("sync-ads-btn").addEventListener("click", () => verifyAds(true));
  $("dashboard-verify-ads").addEventListener("click", () => verifyAds(false));
  $("dashboard-sync-ads").addEventListener("click", () => verifyAds(true));
  $("dashboard-start-pipeline").addEventListener("click", startPipeline);
  $("start-pipeline-btn").addEventListener("click", startPipeline);
  $("stop-pipeline-btn").addEventListener("click", stopPipeline);
  $("enqueue-pending-btn").addEventListener("click", enqueuePending);

  const tasksTableBody = $("tasks-table-body");
  if (tasksTableBody) {
    tasksTableBody.addEventListener("click", async (e) => {
      const btn = e.target.closest?.(".btn-cancel-task");
      if (!btn) return;
      const id = Number(btn.dataset.taskId);
      if (!id) return;
      e.preventDefault();
      if (
        !window.confirm(
          "Остановить эту задачу? Текущий этап (рендер или загрузка) будет прерван; частичный файл может быть удалён."
        )
      ) {
        return;
      }
      try {
        await api(`/api/tasks/${id}/cancel`, { method: "POST" });
        showToast("Запрос на отмену отправлен.", "ok");
        await refreshAll(true);
      } catch (err) {
        showToast(err.message || "Не удалось отменить задачу.", "err");
      }
    });
  }

  $("save-groq-btn").addEventListener("click", () => saveGroq(false));
  $("verify-groq-btn")?.addEventListener("click", () => verifyGroqKey());
  $("clear-groq-btn").addEventListener("click", () => saveGroq(true));
  $("check-url-btn").addEventListener("click", checkAnalyticsUrl);
  $("refresh-app-btn").addEventListener("click", () => refreshAll(false));
  $("open-docs-btn").addEventListener("click", () => window.open(apiUrl("/docs"), "_blank"));
  $("warmup-start-btn").addEventListener("click", () => {
    showToast("Экран прогрева готов. Движок прогрева добавим следующим модулем.", "ok");
  });

  $("render-progress-dismiss-btn")?.addEventListener("click", userDismissRenderProgressModal);
  $("render-progress-close-btn")?.addEventListener("click", userDismissRenderProgressModal);
  $("render-progress-backdrop")?.addEventListener("click", userDismissRenderProgressModal);

  $("tenant-id-select").addEventListener("change", (e) => {
    state.tenantId = e.target.value || "default";
    localStorage.setItem("neoTenantId", state.tenantId);
    renderTenant();
    refreshAll(false);
  });

  $("save-tenant-btn").addEventListener("click", () => {
    const tenant = ($("tenant-input").value || "default").trim().toLowerCase();
    state.tenantId = tenant || "default";
    localStorage.setItem("neoTenantId", state.tenantId);
    renderTenant();
    showToast(`Tenant переключён на ${state.tenantId}`, "ok");
    refreshAll(false);
  });


  document.querySelectorAll(".preset-btn[data-preset]").forEach((el) => {
    el.addEventListener("click", () => {
      applyPresetUI(el.dataset.preset);
      saveUniqualizerSettings(true);
      showToast(`Пресет: ${el.querySelector(".preset-name").textContent}`, "ok");
    });
  });

  document.querySelectorAll(".tmpl-btn[data-tmpl]").forEach((el) => {
    el.addEventListener("click", () => {
      applyTemplateUI(el.dataset.tmpl);
      saveUniqualizerSettings(true);
      showToast(`Шаблон: ${el.querySelector(".tmpl-name").textContent}`, "ok");
    });
  });

  $("dest-download-btn").addEventListener("click", () => {
    state.renderDest = "download";
    localStorage.setItem("neoRenderDest", "download");
    renderDestSelector();
    renderFileSelection();
  });
  $("dest-antidetect-btn").addEventListener("click", () => {
    state.renderDest = "antidetect";
    localStorage.setItem("neoRenderDest", "antidetect");
    renderDestSelector();
    renderFileSelection();
  });

  $("adspower-auth-toggle").addEventListener("click", () => {
    $("adspower-auth-toggle").classList.toggle("off");
  });

  $("geo-toggle").addEventListener("click", () => {
    $("geo-toggle").classList.toggle("off");
    saveUniqualizerSettings(true);
    updateSettingsSummary();
  });
  $("geo-city-select").addEventListener("change", () => {
    renderGeoInjection();
    saveUniqualizerSettings(true);
    updateSettingsSummary();
  });
  $("geo-jitter-range").addEventListener("input", renderGeoInjection);
  $("geo-jitter-range").addEventListener("change", () => saveUniqualizerSettings(true));

  $("overlay-pick-btn")?.addEventListener("click", () => $("overlay-file-input")?.click());
  $("overlay-file-input")?.addEventListener("change", () => uploadOverlayLayerFile());
  $("srt-pick-btn")?.addEventListener("click", () => $("srt-file-input")?.click());
  $("srt-file-input")?.addEventListener("change", () => uploadSrtFile());
  $("srt-clear-btn")?.addEventListener("click", async () => {
    state.subtitleSrtPath = "";
    renderSrtFilePill();
    try {
      await saveUniqualizerSettings(true);
      showToast("SRT сброшен.", "ok");
      updateSettingsSummary();
    } catch (e) {
      showToast(e.message || "Не удалось сохранить.", "err");
    }
  });
  $("overlay-reset-btn")?.addEventListener("click", async () => {
    state.overlayMediaPath = "";
    renderOverlayFilePill();
    try {
      await saveUniqualizerSettings(true);
      showToast("Слой сброшен на data/overlay.png", "ok");
      updateSettingsSummary();
    } catch (e) {
      showToast(e.message || "Не удалось сохранить.", "err");
    }
  });
  $("overlay-blend-select")?.addEventListener("change", () => {
    saveUniqualizerSettings(true);
    updateSettingsSummary();
  });
  $("overlay-opacity-range")?.addEventListener("input", () => {
    const v = $("overlay-opacity-range")?.value || "100";
    const ovl = $("overlay-opacity-val");
    if (ovl) ovl.textContent = v;
  });
  $("overlay-opacity-range")?.addEventListener("change", () => {
    saveUniqualizerSettings(true);
    updateSettingsSummary();
  });
  $("overlay-mode-select")?.addEventListener("change", () => {
    syncOverlayPositionControl();
    saveUniqualizerSettings(true);
    updateSettingsSummary();
  });
  $("overlay-position-select")?.addEventListener("change", () => {
    saveUniqualizerSettings(true);
    updateSettingsSummary();
  });
  $("subtitle-style-select")?.addEventListener("change", () => {
    saveUniqualizerSettings(true);
    updateSettingsSummary();
  });

  // Гео-коллапс
  const geoCollapser = $("geo-collapse-btn");
  if (geoCollapser) {
    geoCollapser.addEventListener("click", () => {
      const body = $("geo-body");
      const arrow = $("geo-arrow");
      const open = body.style.display === "none";
      body.style.display = open ? "block" : "none";
      arrow.classList.toggle("open", open);
    });
  }

  // Субтитры → обновить сводку и превью
  const subtitleInput = $("subtitle-input");
  if (subtitleInput) {
    subtitleInput.addEventListener("input", updateSettingsSummary);
    subtitleInput.addEventListener("change", () => saveUniqualizerSettings(true));
  }
}

async function init() {
  renderTenant();
  bindControls();
  renderFileSelection();
  renderDestSelector();
  updateSettingsSummary();
  setActiveSection("dashboard");
  try {
    await refreshAll(false);
    showToast("Приложение готово к работе.", "ok");
  } catch (error) {
    showToast(error.message || "Не удалось загрузить приложение.", "err");
  }
  const panelQ = new URLSearchParams(window.location.search).get("panel");
  if (panelQ && /^[a-z0-9_-]+$/i.test(panelQ)) {
    const sec = document.querySelector(`section.side-panel[data-panel="${panelQ}"]`);
    if (sec) setActiveSection(panelQ);
  }
  const embedPoll = new URLSearchParams(window.location.search).get("embed") === "1";
  setInterval(() => refreshAll(true), embedPoll ? 15000 : 5000);
}

window.addEventListener("DOMContentLoaded", init);
