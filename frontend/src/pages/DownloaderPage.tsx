import { useState, useRef } from "react";
import { Check, Clipboard, Download, Link2, Smartphone, X } from "lucide-react";
import { apiUrl } from "@/api";
import { uiIconProps } from "@/components/icons/uiIconProps";
import { useTenant } from "@/tenant/TenantContext";
import { SiYoutube, SiYoutubeshorts, SiTiktok, SiKick } from "react-icons/si";

const D14 = uiIconProps(14);
const D15 = uiIconProps(15);

// ── Platform detection ────────────────────────────────────────────────────────
type Platform = "youtube" | "shorts" | "tiktok" | "kick" | "unknown";

interface PlatformInfo {
  id: Platform;
  label: string;
  color: string;
  bg: string;
  icon: React.ReactNode;
  hint: string;
}

function PlatformIcon({ platform, size = 18 }: { platform: Platform; size?: number }) {
  const iconSize = Math.max(12, Math.floor(size * 0.62));
  const iconMap: Record<Platform, { Comp?: React.ComponentType<{ size?: number; color?: string }>; tile: string; fg: string }> = {
    youtube: { Comp: SiYoutube, tile: "#FF0000", fg: "#FFFFFF" },
    shorts: { Comp: SiYoutubeshorts, tile: "#FF0050", fg: "#FFFFFF" },
    tiktok: { Comp: SiTiktok, tile: "#111111", fg: "#FFFFFF" },
    kick: { Comp: SiKick, tile: "#53FC18", fg: "#0B0F0A" },
    unknown: { tile: "var(--bg-elevated)", fg: "var(--text-tertiary)" },
  };
  const conf = iconMap[platform];
  const Comp = conf.Comp;
  return (
    <span
      style={{
        width: size,
        height: size,
        borderRadius: Math.max(6, Math.round(size * 0.22)),
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        background: conf.tile,
        boxShadow: "inset 0 1px 0 rgba(255,255,255,0.2), 0 3px 10px rgba(0,0,0,0.35)",
      }}
    >
      {Comp ? (
        <Comp size={iconSize} color={conf.fg} />
      ) : (
        <Link2 size={iconSize} color={conf.fg} strokeWidth={2.1} aria-hidden />
      )}
    </span>
  );
}

const PLATFORMS: Record<Platform, PlatformInfo> = {
  youtube: {
    id: "youtube",
    label: "YouTube",
    color: "#FF4444",
    bg: "rgba(255,0,0,0.1)",
    hint: "youtube.com/watch",
    icon: <PlatformIcon platform="youtube" />,
  },
  shorts: {
    id: "shorts",
    label: "YT Shorts",
    color: "#FF0050",
    bg: "rgba(255,0,80,0.1)",
    hint: "youtube.com/shorts",
    icon: <PlatformIcon platform="shorts" />,
  },
  tiktok: {
    id: "tiktok",
    label: "TikTok",
    color: "#69C9D0",
    bg: "rgba(105,201,208,0.1)",
    hint: "tiktok.com/@user/video/...",
    icon: <PlatformIcon platform="tiktok" />,
  },
  kick: {
    id: "kick",
    label: "Kick",
    color: "#53FC18",
    bg: "rgba(83,252,24,0.1)",
    hint: "kick.com/username/clips/...",
    icon: <PlatformIcon platform="kick" />,
  },
  unknown: {
    id: "unknown",
    label: "Ссылка",
    color: "var(--text-tertiary)",
    bg: "var(--bg-elevated)",
    hint: "",
    icon: <PlatformIcon platform="unknown" />,
  },
};

function detectPlatform(url: string): Platform {
  const u = url.toLowerCase();
  if (u.includes("youtube.com/shorts") || u.includes("youtu.be/")) {
    // youtu.be could be either but treat as shorts-compatible
    if (u.includes("youtube.com/shorts")) return "shorts";
    return "youtube";
  }
  if (u.includes("youtube.com") || u.includes("youtu.be")) return "youtube";
  if (u.includes("tiktok.com")) return "tiktok";
  if (u.includes("kick.com")) return "kick";
  return "unknown";
}

function isValidUrl(url: string) {
  try {
    const u = new URL(url.trim());
    return u.protocol === "http:" || u.protocol === "https:";
  } catch {
    return false;
  }
}

// ── History entry ─────────────────────────────────────────────────────────────
type HistoryEntry = {
  id: string;
  url: string;
  platform: Platform;
  status: "pending" | "downloading" | "done" | "error";
  filename?: string;
  error?: string;
  ts: number;
};

// ── Format helpers ────────────────────────────────────────────────────────────
function timeAgo(ts: number) {
  const d = (Date.now() - ts) / 1000;
  if (d < 60) return "только что";
  if (d < 3600) return `${Math.floor(d / 60)} мин назад`;
  return `${Math.floor(d / 3600)} ч назад`;
}

function shortUrl(url: string) {
  try {
    const u = new URL(url);
    return (u.hostname + u.pathname).replace(/^www\./, "").slice(0, 55) + (url.length > 60 ? "…" : "");
  } catch {
    return url.slice(0, 55) + (url.length > 60 ? "…" : "");
  }
}

// ── Supported platforms tile ──────────────────────────────────────────────────
const SUPPORTED: { platform: Platform; examples: string[] }[] = [
  { platform: "shorts", examples: ["youtube.com/shorts/…"] },
  { platform: "youtube", examples: ["youtube.com/watch?v=…", "youtu.be/…"] },
  { platform: "tiktok", examples: ["tiktok.com/@user/video/…"] },
  { platform: "kick", examples: ["kick.com/user/clips/…"] },
];

// ── Page ──────────────────────────────────────────────────────────────────────
export function DownloaderPage() {
  const { tenantId } = useTenant();
  const [url, setUrl] = useState("");
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [toast, setToast] = useState<{ msg: string; kind: "ok" | "err" } | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const platform = url.trim() ? detectPlatform(url.trim()) : "unknown";
  const platformInfo = PLATFORMS[platform];
  const valid = isValidUrl(url.trim());

  function showToast(msg: string, kind: "ok" | "err") {
    setToast({ msg, kind });
    setTimeout(() => setToast(null), 5000);
  }

  async function handleDownload(inputUrl?: string) {
    const target = (inputUrl ?? url).trim();
    if (!target || !isValidUrl(target)) return;

    const plat = detectPlatform(target);
    const entry: HistoryEntry = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
      url: target,
      platform: plat,
      status: "downloading",
      ts: Date.now(),
    };

    setHistory((prev) => [entry, ...prev.slice(0, 29)]);
    if (inputUrl === undefined) setUrl("");

    try {
      const resp = await fetch(apiUrl("/api/research/download/browser"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Tenant-ID": tenantId,
        },
        body: JSON.stringify({ url: target }),
      });

      if (!resp.ok) {
        let msg = `HTTP ${resp.status}`;
        try { const j = await resp.json(); msg = String(j?.message || msg); } catch { /* noop */ }
        throw new Error(msg);
      }

      const blob = await resp.blob();
      const cd = resp.headers.get("content-disposition") || "";
      const m = cd.match(/filename="?([^";]+)"?/i);
      const filename = (m?.[1] || `video_${Date.now()}.mp4`).trim();

      const objectUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = objectUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(objectUrl), 2000);

      setHistory((prev) => prev.map((e) =>
        e.id === entry.id ? { ...e, status: "done", filename } : e
      ));
      showToast(`${filename} — скачан`, "ok");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Ошибка скачивания";
      setHistory((prev) => prev.map((e) =>
        e.id === entry.id ? { ...e, status: "error", error: msg } : e
      ));
      showToast(msg, "err");
    }
  }

  async function pasteFromClipboard() {
    try {
      const text = await navigator.clipboard.readText();
      if (text.trim()) {
        setUrl(text.trim());
        inputRef.current?.focus();
      }
    } catch {
      showToast("Нет доступа к буферу обмена", "err");
    }
  }

  return (
    <div className="page">
      {toast && (
        <div className="toast-container">
          <div className={`toast-v2 ${toast.kind === "err" ? "error" : "success"}`}>
            <span className="toast-v2-icon">{toast.kind === "err" ? "✕" : "✓"}</span>
            <span className="toast-v2-msg">{toast.msg}</span>
            <button type="button" className="toast-v2-close" onClick={() => setToast(null)}>✕</button>
          </div>
        </div>
      )}

      {/* ── Header ── */}
      <div style={{ marginBottom: 4 }}>
        <div style={{ fontSize: 20, fontWeight: 800, color: "var(--text-primary)", letterSpacing: "-0.4px" }}>
          Загрузчик видео
        </div>
        <div style={{ fontSize: 13, color: "var(--text-tertiary)", marginTop: 3 }}>
          Вставьте ссылку на видео — оно скачается прямо в браузер
        </div>
      </div>

      {/* ── Main download card ── */}
      <div className="card" style={{ overflow: "visible" }}>
        <div className="card-body" style={{ padding: "20px 20px 22px" }}>

          {/* Platform indicator */}
          {url.trim() && (
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
              <div style={{
                display: "flex", alignItems: "center", gap: 7,
                padding: "4px 12px 4px 6px", borderRadius: 20,
                background: platformInfo.bg,
                border: `1px solid ${platformInfo.color}40`,
                color: platformInfo.color,
                fontSize: 12, fontWeight: 700,
              }}>
                <span style={{ display: "flex", filter: "drop-shadow(0 1px 3px rgba(0,0,0,0.4))" }}>
                  <PlatformIcon platform={platform} size={20} />
                </span>
                {platformInfo.label}
              </div>
              {valid
                ? <span style={{ fontSize: 11, color: "var(--accent-green)" }}>✓ Ссылка распознана</span>
                : <span style={{ fontSize: 11, color: "var(--accent-amber)" }}>Неполный URL…</span>}
            </div>
          )}

          {/* Input row */}
          <div style={{ display: "flex", gap: 8 }}>
            <div style={{ position: "relative", flex: 1 }}>
              <input
                ref={inputRef}
                className="form-input"
                placeholder="Вставьте ссылку на YouTube Shorts, TikTok, Kick..."
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && valid) void handleDownload(); }}
                style={{ paddingRight: 36, fontSize: 13 }}
                autoFocus
              />
              {url && (
                <button type="button"
                  onClick={() => { setUrl(""); inputRef.current?.focus(); }}
                  style={{
                    position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)",
                    background: "none", border: "none", cursor: "pointer",
                    color: "var(--text-tertiary)", lineHeight: 1, display: "flex", alignItems: "center",
                  }} aria-label="Очистить"><X {...D14} /></button>
              )}
            </div>

            {/* Paste button */}
            <button type="button" className="btn-v3 btn-v3-ghost"
              onClick={pasteFromClipboard}
              title="Вставить из буфера обмена"
              style={{ flexShrink: 0, gap: 6, padding: "0 13px" }}>
              <Clipboard {...D14} aria-hidden />
              Вставить
            </button>

            {/* Download button */}
            <button type="button"
              className={`btn-v3 ${valid ? "btn-v3-primary" : ""}`}
              disabled={!valid}
              onClick={() => void handleDownload()}
              style={{ flexShrink: 0, minWidth: 160, fontWeight: 700, fontSize: 13 }}>
              <Download {...D15} aria-hidden />
              Скачать видео
            </button>
          </div>

          {/* Supported platforms */}
          <div style={{ display: "flex", gap: 10, marginTop: 16, flexWrap: "wrap" }}>
            {SUPPORTED.map(({ platform: p, examples }) => {
              const info = PLATFORMS[p];
              return (
                <div key={p} className="dl-platform-chip">
                  <span className="dl-chip-icon">
                    <PlatformIcon platform={p} size={28} />
                  </span>
                  <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
                    <span style={{ color: "var(--text-primary)", fontWeight: 700, fontSize: 12 }}>{info.label}</span>
                    <span style={{ color: "var(--text-tertiary)", fontSize: 10 }}>{examples[0]}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* ── History ── */}
      {history.length > 0 && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">История загрузок</span>
            <button type="button" className="btn-v3 btn-v3-sm btn-v3-ghost"
              onClick={() => setHistory([])}>
              Очистить
            </button>
          </div>
          <div className="card-body" style={{ padding: 0 }}>
            <table className="data-table" style={{ width: "100%" }}>
              <thead>
                <tr>
                  <th style={{ width: 110 }}>Платформа</th>
                  <th>Ссылка</th>
                  <th>Файл</th>
                  <th style={{ width: 130 }}>Статус</th>
                  <th style={{ width: 110 }}>Время</th>
                  <th style={{ width: 80 }} />
                </tr>
              </thead>
              <tbody>
                {history.map((entry) => {
                  const info = PLATFORMS[entry.platform];
                  return (
                    <tr key={entry.id}>
                      <td>
                        <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                          <span style={{ display: "flex", filter: "drop-shadow(0 1px 3px rgba(0,0,0,0.5))" }}>
                            <PlatformIcon platform={entry.platform} size={22} />
                          </span>
                          <span style={{ color: info.color, fontWeight: 700, fontSize: 12 }}>{info.label}</span>
                        </div>
                      </td>
                      <td>
                        <a href={entry.url} target="_blank" rel="noreferrer"
                          style={{ fontSize: 12, color: "var(--text-secondary)",
                            textDecoration: "none", maxWidth: 360, display: "block",
                            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                          title={entry.url}>
                          {shortUrl(entry.url)}
                        </a>
                      </td>
                      <td>
                        <span className="mono" style={{ fontSize: 11, color: "var(--text-tertiary)" }}>
                          {entry.filename || "—"}
                        </span>
                      </td>
                      <td>
                        {entry.status === "downloading" && (
                          <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--accent-cyan)" }}>
                            <span className="spinner-sm" />
                            Загрузка…
                          </span>
                        )}
                        {entry.status === "done" && (
                          <span style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 12, color: "var(--accent-green)", fontWeight: 600 }}>
                            <Check {...uiIconProps(13)} strokeWidth={2.5} aria-hidden />
                            Скачан
                          </span>
                        )}
                        {entry.status === "error" && (
                          <span style={{ fontSize: 12, color: "var(--accent-red)" }} title={entry.error}>
                            ⚠ Ошибка
                          </span>
                        )}
                        {entry.status === "pending" && (
                          <span style={{ fontSize: 12, color: "var(--text-tertiary)" }}>В очереди</span>
                        )}
                      </td>
                      <td style={{ fontSize: 11, color: "var(--text-tertiary)" }}>
                        {timeAgo(entry.ts)}
                      </td>
                      <td>
                        {entry.status === "error" && (
                          <button type="button" className="btn-v3 btn-v3-sm btn-v3-danger"
                            onClick={() => void handleDownload(entry.url)}
                            style={{ fontSize: 10 }}>
                            Повторить
                          </button>
                        )}
                        {entry.status === "done" && (
                          <button type="button" className="btn-v3 btn-v3-sm btn-v3-ghost"
                            onClick={() => void handleDownload(entry.url)}
                            style={{ fontSize: 10 }}>
                            Ещё раз
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Tips ── */}
      <div className="card">
        <div className="card-header">
          <span className="card-title" style={{ fontSize: 12 }}>Советы по использованию</span>
        </div>
        <div className="card-body" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          {[
            { icon: <PlatformIcon platform="shorts" size={20} />, title: "Shorts", text: "Открой видео в браузере, скопируй URL из адресной строки" },
            { icon: <PlatformIcon platform="tiktok" size={20} />, title: "TikTok", text: "Зайди в видео, нажми «Поделиться» → «Копировать ссылку»" },
            { icon: <PlatformIcon platform="kick" size={20} />, title: "Kick", text: "На странице клипа нажми «Ещё» → «Копировать ссылку на клип»" },
            {
              icon: (
                <span style={{
                  width: 32, height: 32, borderRadius: 7, background: "#2A3240",
                  display: "inline-flex", alignItems: "center", justifyContent: "center",
                  boxShadow: "inset 0 1px 0 rgba(255,255,255,0.06)",
                }}>
                  <Smartphone size={18} color="#EDEEF0" strokeWidth={1.75} aria-hidden />
                </span>
              ),
              title: "Быстро",
              text: "Скопируй URL и нажми кнопку «Вставить» — ссылка вставится автоматически",
            },
          ].map((tip) => (
            <div key={tip.title} className="dl-tip-card">
              <span className="dl-tip-icon">{tip.icon}</span>
              <div>
                <div style={{ fontSize: 12, fontWeight: 700, color: "var(--text-primary)", marginBottom: 3 }}>{tip.title}</div>
                <div style={{ fontSize: 11, color: "var(--text-tertiary)", lineHeight: 1.5 }}>{tip.text}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <style>{`
        .spinner-sm {
          display: inline-block; width: 11px; height: 11px;
          border: 2px solid rgba(255,255,255,0.2); border-top-color: currentColor;
          border-radius: 50%; animation: spin 0.7s linear infinite; flex-shrink: 0;
        }
        .dl-platform-chip {
          display: flex;
          align-items: center;
          gap: 9px;
          padding: 8px 12px 8px 8px;
          border-radius: 10px;
          background: linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0));
          border: 1px solid var(--border-subtle);
          font-size: 11px;
          min-width: 212px;
          transition: transform .18s ease, border-color .18s ease, box-shadow .18s ease;
        }
        .dl-platform-chip:hover {
          transform: translateY(-1px);
          border-color: rgba(94,234,212,0.35);
          box-shadow: 0 8px 20px rgba(0,0,0,0.25);
        }
        .dl-chip-icon {
          display: flex;
          align-items: center;
          justify-content: center;
          width: 32px;
          height: 32px;
          flex-shrink: 0;
          filter: drop-shadow(0 2px 4px rgba(0,0,0,0.45));
        }
        .dl-tip-card {
          display: flex;
          gap: 10px;
          padding: 10px 12px;
          background: linear-gradient(180deg, rgba(255,255,255,0.015), rgba(255,255,255,0));
          border-radius: 8px;
          border: 1px solid var(--border-subtle);
          transition: transform .16s ease, border-color .16s ease, box-shadow .16s ease;
        }
        .dl-tip-card:hover {
          transform: translateY(-1px);
          border-color: rgba(94,234,212,0.3);
          box-shadow: 0 8px 18px rgba(0,0,0,0.25);
        }
        .dl-tip-icon {
          display: flex;
          width: 22px;
          height: 22px;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
          filter: drop-shadow(0 2px 4px rgba(0,0,0,0.4));
        }
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}
