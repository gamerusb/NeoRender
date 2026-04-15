import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { SystemStatusLines } from "@/components/SystemStatusLines";
import { apiFetch, type ApiJson } from "@/api";
import { buildSystemStatusLines } from "@/lib/systemStatus";
import { useTenant } from "@/tenant/TenantContext";

type CookieBackup = {
  filename: string;
  profile_id: string;
  created_at: string;
  size_kb: number;
};

export function SettingsPage() {
  const { tenantId } = useTenant();
  const qc = useQueryClient();
  const [toast, setToast] = useState<{ msg: string; kind: "ok" | "err" } | null>(null);
  const [groqKey, setGroqKey] = useState("");
  const [nichePreview, setNichePreview] = useState("Korean YouTube Shorts");
  const [previewMeta, setPreviewMeta] = useState<ApiJson | null>(null);
  const [tgToken, setTgToken] = useState("");
  const [tgChatId, setTgChatId] = useState("");

  useEffect(() => {
    if (!toast) return;
    const t = window.setTimeout(() => setToast(null), 4000);
    return () => window.clearTimeout(t);
  }, [toast]);

  const systemQ = useQuery({
    queryKey: ["system", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/system/status", { tenantId }),
    staleTime: 10_000,
  });
  const pingQ = useQuery({
    queryKey: ["integrations-ping", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/integrations/ping", { tenantId }),
    staleTime: 60_000,
    refetchInterval: 120_000,
  });
  const groqStatusQ = useQuery({
    queryKey: ["groq-status"],
    queryFn: () => apiFetch<ApiJson>("/api/settings/groq"),
    staleTime: 15_000,
  });
  const ffmpegCfgQ = useQuery({
    queryKey: ["ffmpeg-config"],
    queryFn: () => apiFetch<ApiJson>("/api/system/ffmpeg-config"),
    staleTime: 20_000,
  });
  const telegramQ = useQuery({
    queryKey: ["telegram-status"],
    queryFn: () => apiFetch<ApiJson>("/api/settings/telegram"),
    staleTime: 15_000,
  });

  useEffect(() => {
    if (!telegramQ.data) return;
    setTgChatId(String(telegramQ.data.chat_id || ""));
  }, [telegramQ.data]);

  const saveGroq = useMutation({
    mutationFn: (clear: boolean) =>
      apiFetch<ApiJson>("/api/settings/groq", {
        method: "POST",
        tenantId,
        body: JSON.stringify({ key: clear ? "" : groqKey.trim() }),
      }),
    onSuccess: async (r: ApiJson) => {
      setToast({ msg: Boolean(r.cleared) ? "Ключ Groq очищен." : "Ключ Groq сохранён.", kind: "ok" });
      setGroqKey("");
      await qc.invalidateQueries({ queryKey: ["groq-status"] });
      await qc.invalidateQueries({ queryKey: ["system", tenantId] });
      await qc.invalidateQueries({ queryKey: ["integrations-ping", tenantId] });
    },
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });

  const pingGroq = useMutation({
    mutationFn: () =>
      apiFetch<ApiJson>("/api/settings/groq/ping", {
        method: "POST",
        tenantId,
        body: JSON.stringify({ key: groqKey.trim() }),
      }),
    onSuccess: async (data: ApiJson) => {
      const live = Boolean(data.live);
      const trial = Boolean(data.used_trial_key);
      setToast({
        msg: `${live ? "Groq OK" : "Groq"}: ${String(data.message || "")}${trial ? " (сохраните ключ)" : ""}`,
        kind: live ? "ok" : "err",
      });
      await qc.invalidateQueries({ queryKey: ["integrations-ping", tenantId] });
    },
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });

  const aiPreview = useMutation({
    mutationFn: () =>
      apiFetch<ApiJson>("/api/ai/preview", {
        method: "POST",
        tenantId,
        body: JSON.stringify({ niche: nichePreview.trim() || "YouTube Shorts" }),
      }),
    onSuccess: (meta: ApiJson) => {
      setPreviewMeta(meta);
      setToast({ msg: meta.used_fallback ? "Превью через fallback." : "AI превью готово.", kind: "ok" });
    },
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });

  const saveTelegram = useMutation({
    mutationFn: () =>
      apiFetch<ApiJson>("/api/settings/telegram", {
        method: "POST",
        body: JSON.stringify({ bot_token: tgToken.trim(), chat_id: tgChatId.trim() }),
      }),
    onSuccess: async (r: ApiJson) => {
      setToast({ msg: r.saved ? "Telegram настроен." : "Telegram очищен.", kind: "ok" });
      setTgToken("");
      await qc.invalidateQueries({ queryKey: ["telegram-status"] });
    },
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });

  const pingTelegram = useMutation({
    mutationFn: () => apiFetch<ApiJson>("/api/settings/telegram/ping", { method: "POST", body: "{}" }),
    onSuccess: (r: ApiJson) => setToast({ msg: String(r.message || "Отправлено"), kind: "ok" }),
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });

  const lines = buildSystemStatusLines(systemQ.data, pingQ.data ?? undefined);
  const masked = String((groqStatusQ.data as ApiJson | undefined)?.masked || "");
  const tgConfigured = Boolean(telegramQ.data?.configured);
  const tgMasked = String(telegramQ.data?.token_masked || "");
  const ffcfg = ffmpegCfgQ.data;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Toast */}
      {toast && (
        <div
          className={`toast-v2 ${toast.kind === "err" ? "error" : "success"}`}
          style={{ position: "fixed", right: 20, bottom: 20, zIndex: 10000 }}
        >
          <span className="toast-v2-icon">{toast.kind === "err" ? "✕" : "✓"}</span>
          <span className="toast-v2-msg">{toast.msg}</span>
          <button type="button" className="toast-v2-close" onClick={() => setToast(null)}>✕</button>
        </div>
      )}

      {/* Diagnostic banner */}
      <div className="diag-banner">
        <strong>Диагностика:</strong>{" "}
        <strong>Рендер/уникализация</strong> — нужны FFmpeg и файл слоя (overlay).{" "}
        <strong>Groq</strong> — только для AI-заголовков при заливе в YouTube.{" "}
        <strong>AdsPower</strong> — только если используете антидетект, клиент должен быть запущен локально.{" "}
        <strong>Workspace:</strong>{" "}
        <span className="mono" style={{ color: "var(--text-primary)", fontSize: 12 }}>{tenantId}</span>
        {" "}— переключение только в левой панели.
      </div>

      {/* Main 2-col grid */}
      <div className="settings-page">
        {/* Left column */}
        <div className="settings-stack">

          {/* Groq */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">ИИ (Groq)</span>
              {masked && (
                <span className="badge" style={{ background: "var(--accent-green-dim)", color: "var(--accent-green)", fontSize: 11 }}>
                  Ключ задан
                </span>
              )}
            </div>
            <div className="card-body" style={{ padding: "16px 20px", display: "flex", flexDirection: "column", gap: 14 }}>
              <div className="input-group">
                <label className="label-dark" htmlFor="settings-groq-key">API ключ</label>
                <input
                  id="settings-groq-key"
                  className="form-input mono"
                  placeholder={masked ? `Сохранён: ${masked}` : "gsk_..."}
                  value={groqKey}
                  onChange={(e) => setGroqKey(e.target.value)}
                  autoComplete="off"
                />
              </div>
              <div className="input-group" style={{ marginBottom: 0 }}>
                <label className="label-dark" htmlFor="settings-ai-niche">Ниша для превью</label>
                <input
                  id="settings-ai-niche"
                  className="form-input"
                  value={nichePreview}
                  onChange={(e) => setNichePreview(e.target.value)}
                />
              </div>
              <div className="section-actions">
                <button type="button" className="action-btn" disabled={saveGroq.isPending} onClick={() => saveGroq.mutate(false)}>
                  Сохранить ключ
                </button>
                <button type="button" className="action-btn" disabled={pingGroq.isPending} onClick={() => pingGroq.mutate()}>
                  Проверить ключ
                </button>
                <button type="button" className="action-btn" disabled={saveGroq.isPending} onClick={() => saveGroq.mutate(true)}>
                  Очистить ключ
                </button>
                <button type="button" className="action-btn" disabled={aiPreview.isPending} onClick={() => aiPreview.mutate()}>
                  Сделать превью
                </button>
              </div>
              <p className="settings-footnote">
                «Проверить» — запрос к Groq; пустое поле ключа проверяет сохранённый.
                Ключи пишутся в <span className="mono" style={{ fontSize: 11 }}>data/neo_settings.json</span>.
              </p>
            </div>
          </div>

          {/* Telegram */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">Telegram-уведомления</span>
              {tgConfigured && (
                <span className="badge" style={{ background: "var(--accent-green-dim)", color: "var(--accent-green)", fontSize: 11 }}>
                  Настроен
                </span>
              )}
            </div>
            <div className="card-body" style={{ padding: "16px 20px", display: "flex", flexDirection: "column", gap: 14 }}>
              <div className="input-group">
                <label className="label-dark" htmlFor="settings-tg-token">Bot Token</label>
                <input
                  id="settings-tg-token"
                  className="form-input mono"
                  placeholder={tgMasked ? `Сохранён: ${tgMasked}` : "123456:ABC-DEF..."}
                  value={tgToken}
                  onChange={(e) => setTgToken(e.target.value)}
                  autoComplete="off"
                />
              </div>
              <div className="input-group" style={{ marginBottom: 0 }}>
                <label className="label-dark" htmlFor="settings-tg-chat">Chat ID</label>
                <input
                  id="settings-tg-chat"
                  className="form-input mono"
                  placeholder="-100123456789 или @username"
                  value={tgChatId}
                  onChange={(e) => setTgChatId(e.target.value)}
                />
              </div>
              <div className="section-actions">
                <button type="button" className="action-btn" disabled={saveTelegram.isPending} onClick={() => saveTelegram.mutate()}>
                  Сохранить
                </button>
                <button
                  type="button"
                  className="action-btn"
                  disabled={pingTelegram.isPending || !tgConfigured}
                  title={!tgConfigured ? "Сначала сохраните токен и chat_id" : ""}
                  onClick={() => pingTelegram.mutate()}
                >
                  Тест уведомления
                </button>
                <button
                  type="button"
                  className="action-btn"
                  disabled={saveTelegram.isPending}
                  onClick={() => { setTgToken(""); setTgChatId(""); saveTelegram.mutate(); }}
                >
                  Очистить
                </button>
              </div>
              <p className="settings-footnote">
                Уведомления: успех/ошибка задачи, очередь опустела, отложенная задача запущена.
                Токен — @BotFather, Chat ID — @userinfobot.
              </p>
            </div>
          </div>
        </div>

        {/* Right column */}
        <div className="settings-right-stack">

          {/* System status */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">Системный статус</span>
              {systemQ.isFetching && (
                <span style={{ fontSize: 11, color: "var(--text-tertiary)" }}>обновление...</span>
              )}
            </div>
            <div className="card-body" style={{ padding: "8px 20px 14px" }}>
              {systemQ.isError ? (
                <div className="empty-state">{(systemQ.error as Error).message}</div>
              ) : (
                <SystemStatusLines lines={lines} />
              )}
            </div>
          </div>

          {/* FFmpeg config */}
          <div className="card">
            <div className="card-header"><span className="card-title">FFmpeg конфиг</span></div>
            <div className="card-body" style={{ padding: "8px 20px 14px" }}>
              {ffmpegCfgQ.isError ? (
                <div className="empty-state">{(ffmpegCfgQ.error as Error).message}</div>
              ) : ffcfg ? (
                <div style={{ display: "flex", flexDirection: "column" }}>
                  {[
                    ["ffmpeg_bin", ffcfg.ffmpeg_bin],
                    ["ffprobe_bin", ffcfg.ffprobe_bin],
                    ["timeout", ffcfg.ffmpeg_timeout_sec],
                    ["vsync_mode", ffcfg.vsync_mode ?? "off"],
                    ["nvenc_disabled", String(Boolean(ffcfg.nvenc_disabled))],
                    ["hardened_builder", String(Boolean(ffcfg.hardened_builder))],
                  ].map(([k, v]) => (
                    <div key={String(k)} className="ffmpeg-row">
                      <span className="ffmpeg-key">{String(k)}</span>
                      <span className="ffmpeg-val">{String(v ?? "—")}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="empty-state">Загрузка…</div>
              )}
            </div>
          </div>

          {/* AI preview */}
          <div className="card">
            <div className="card-header"><span className="card-title">AI превью</span></div>
            <div className="card-body" style={{ padding: "12px 20px 16px" }}>
              {!previewMeta ? (
                <div className="empty-state" style={{ padding: "12px 0" }}>
                  Нажмите «Сделать превью» (слева), чтобы увидеть title / description / comment.
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {[
                    ["title", previewMeta.title],
                    ["description", previewMeta.description],
                    ["comment", previewMeta.comment],
                    ...(previewMeta.overlay_text != null && String(previewMeta.overlay_text).trim()
                      ? [["overlay_text", previewMeta.overlay_text]]
                      : []),
                  ].map(([k, v]) => (
                    <div key={String(k)} className="ai-preview-field">
                      <div className="ai-preview-key">{String(k)}</div>
                      <div className="ai-preview-val">{String(v ?? "—")}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Cookie Backup Section */}
      <CookieBackupSection tenantId={tenantId} />
    </div>
  );
}

function CookieBackupSection({ tenantId }: { tenantId: string }) {
  const qc = useQueryClient();
  const [backupProfileId, setBackupProfileId] = useState("");
  const [toast, setToast] = useState<{ msg: string; kind: "ok" | "err" } | null>(null);

  const backupsQ = useQuery({
    queryKey: ["cookie-backups", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/cookies/backups", { tenantId }),
    staleTime: 20_000,
  });

  const backupMut = useMutation({
    mutationFn: (profileId: string) =>
      apiFetch<ApiJson>(`/api/cookies/backup/${encodeURIComponent(profileId)}`, {
        method: "POST",
        tenantId,
      }),
    onSuccess: async (d) => {
      showToast(d.status === "ok" ? "Бэкап создан" : String(d.message || "Бэкап создан с ошибками"), d.status === "ok" ? "ok" : "err");
      await qc.invalidateQueries({ queryKey: ["cookie-backups", tenantId] });
    },
    onError: (e: Error) => showToast(e.message, "err"),
  });

  const restoreMut = useMutation({
    mutationFn: ({ profileId, filename }: { profileId: string; filename: string }) =>
      apiFetch<ApiJson>(`/api/cookies/restore/${encodeURIComponent(profileId)}`, {
        method: "POST",
        tenantId,
        body: JSON.stringify({ filename }),
      }),
    onSuccess: (d) => showToast(d.status === "ok" ? "Сессия восстановлена" : String(d.message || "Ошибка"), d.status === "ok" ? "ok" : "err"),
    onError: (e: Error) => showToast(e.message, "err"),
  });

  function showToast(msg: string, kind: "ok" | "err") {
    setToast({ msg, kind });
    setTimeout(() => setToast(null), 4000);
  }

  const backups = (backupsQ.data?.backups as CookieBackup[] | undefined) ?? [];

  return (
    <div style={{ marginTop: 24 }}>
      {toast && (
        <div className="toast-container">
          <div className={`toast-v2 ${toast.kind === "err" ? "error" : "success"}`}>
            <span className="toast-v2-icon">{toast.kind === "err" ? "✕" : "✓"}</span>
            <span className="toast-v2-msg">{toast.msg}</span>
            <button type="button" className="toast-v2-close" onClick={() => setToast(null)}>✕</button>
          </div>
        </div>
      )}
      <div className="settings-grid">
        {/* Left: backup action */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">Бэкап сессий (Cookies)</span>
          </div>
          <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>
              Создайте бэкап cookies профиля AdsPower на случай потери сессии. Восстановление доступно из списка.
            </div>
            <div className="form-group">
              <label className="form-label">ID профиля AdsPower</label>
              <input
                className="form-input mono"
                placeholder="KR_shorts_01"
                value={backupProfileId}
                onChange={(e) => setBackupProfileId(e.target.value)}
              />
            </div>
            <button
              type="button"
              className="btn btn-cyan"
              disabled={!backupProfileId.trim() || backupMut.isPending}
              onClick={() => backupMut.mutate(backupProfileId.trim())}
            >
              {backupMut.isPending ? "Создание бэкапа…" : "Создать бэкап"}
            </button>
          </div>
        </div>

        {/* Right: backup list */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">Список бэкапов</span>
            <span style={{ fontSize: 11, color: "var(--text-tertiary)", marginLeft: "auto" }}>
              {backups.length} файлов
            </span>
          </div>
          <div className="card-body" style={{ padding: 0 }}>
            {backups.length === 0 ? (
              <div style={{ padding: 20, fontSize: 12, color: "var(--text-tertiary)" }}>
                Бэкапов пока нет
              </div>
            ) : (
              <div style={{ maxHeight: 280, overflowY: "auto" }}>
                {backups.map((b) => (
                  <div
                    key={b.filename}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      gap: 8,
                      padding: "8px 16px",
                      borderBottom: "1px solid var(--border-subtle)",
                      fontSize: 12,
                    }}
                  >
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {b.profile_id}
                      </div>
                      <div style={{ color: "var(--text-tertiary)", fontSize: 11 }}>
                        {b.created_at || b.filename} · {b.size_kb} KB
                      </div>
                    </div>
                    <button
                      type="button"
                      className="action-btn"
                      disabled={restoreMut.isPending}
                      onClick={() => restoreMut.mutate({ profileId: b.profile_id, filename: b.filename })}
                      style={{ fontSize: 11 }}
                    >
                      Восстановить
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
