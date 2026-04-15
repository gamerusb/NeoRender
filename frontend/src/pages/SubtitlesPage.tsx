import { useState, useRef, useEffect } from "react";
import { apiUrl } from "@/api";
import { useTenant } from "@/tenant/TenantContext";
import {
  AlertTriangle,
  Bot,
  Check,
  Clapperboard,
  Clipboard,
  Download,
  FileText,
  MessageSquare,
  Mic2,
  Video,
  X,
} from "lucide-react";
import { uiIconProps } from "@/components/icons/uiIconProps";

const U14 = uiIconProps(14);
const U15 = uiIconProps(15);

const LANGS = [
  { code: "", label: "Авто (определить)" },
  { code: "ko", label: "Корейский" },
  { code: "en", label: "Английский" },
  { code: "ru", label: "Русский" },
  { code: "ja", label: "Японский" },
  { code: "zh", label: "Китайский" },
  { code: "de", label: "Немецкий" },
  { code: "fr", label: "Французский" },
  { code: "es", label: "Испанский" },
  { code: "th", label: "Тайский" },
  { code: "ar", label: "Арабский" },
];

type JobStatus = "idle" | "pending" | "running" | "done" | "error";

interface Job {
  status: JobStatus;
  step?: string;
  message?: string;
  srt_path?: string;
  srt_filename?: string;
  burned_path?: string;
  burned_filename?: string;
  segment_count?: number;
  source_lang?: string;
  target_lang?: string;
}

const STEPS = [
  { key: "download", label: "Скачивание видео" },
  { key: "transcribe", label: "Транскрипция (Whisper)" },
  { key: "translate", label: "Перевод (LLaMA)" },
  { key: "srt", label: "Генерация .srt" },
  { key: "burn", label: "Вжигание субтитров" },
];

function stepIndex(step?: string): number {
  if (!step) return -1;
  const s = step.toLowerCase();
  if (s.includes("скачив")) return 0;
  if (s.includes("транскрип") || s.includes("whisper")) return 1;
  if (s.includes("перевод") || s.includes("llama")) return 2;
  if (s.includes("srt") || s.includes("генерац")) return 3;
  if (s.includes("вжига") || s.includes("burn")) return 4;
  if (s.includes("готово")) return 5;
  return -1;
}

export function SubtitlesPage() {
  const { tenantId } = useTenant();
  const [url, setUrl] = useState("");
  const [sourceLang, setSourceLang] = useState("");
  const [targetLang, setTargetLang] = useState("ko");
  const [burn, setBurn] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<Job>({ status: "idle" });
  const [toast, setToast] = useState<{ msg: string; kind: "ok" | "err" } | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  function showToast(msg: string, kind: "ok" | "err") {
    setToast({ msg, kind });
    setTimeout(() => setToast(null), 6000);
  }

  // Poll job status
  useEffect(() => {
    if (!jobId || job.status === "done" || job.status === "error" || job.status === "idle") {
      if (pollRef.current) clearInterval(pollRef.current);
      return;
    }
    pollRef.current = setInterval(async () => {
      try {
        const resp = await fetch(apiUrl(`/api/subtitles/${jobId}`), {
          headers: { "X-Tenant-ID": tenantId },
        });
        const data = await resp.json() as { status: string; job?: Job };
        if (data.job) {
          setJob(data.job as Job);
          if (data.job.status === "done" || data.job.status === "error") {
            if (pollRef.current) clearInterval(pollRef.current);
          }
        }
      } catch { /* noop */ }
    }, 1500);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [jobId, job.status, tenantId]);

  async function pasteFromClipboard() {
    try {
      const text = await navigator.clipboard.readText();
      if (text.trim()) { setUrl(text.trim()); inputRef.current?.focus(); }
    } catch { showToast("Нет доступа к буферу обмена", "err"); }
  }

  async function handleSubmit() {
    if (!url.trim()) return;
    setJob({ status: "pending", step: "Отправка..." });
    setJobId(null);
    try {
      const resp = await fetch(apiUrl("/api/subtitles/generate"), {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Tenant-ID": tenantId },
        body: JSON.stringify({
          url: url.trim(),
          source_lang: sourceLang || null,
          target_lang: targetLang || null,
          burn,
        }),
      });
      const data = await resp.json() as { status: string; job_id?: string; message?: string };
      if (!resp.ok || data.status === "error") throw new Error(data.message || `HTTP ${resp.status}`);
      setJobId(data.job_id!);
      setJob({ status: "running", step: "Скачивание видео" });
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Ошибка";
      setJob({ status: "error", message: msg });
      showToast(msg, "err");
    }
  }

  function downloadFile(path: "srt" | "ass" | "video") {
    if (!jobId) return;
    const endpoint = apiUrl(`/api/subtitles/${jobId}/download/${path}`);
    const a = document.createElement("a");
    Object.assign(a.style, { display: "none" });
    document.body.appendChild(a);

    // Need auth header, so download via fetch+blob and manually set filename.
    fetch(endpoint, { headers: { "X-Tenant-ID": tenantId } })
      .then(async (r) => {
        if (!r.ok) {
          throw new Error(`HTTP ${r.status}`);
        }
        const cd = r.headers.get("content-disposition") || "";
        const blob = await r.blob();
        let filename = path === "srt"
          ? (job.srt_filename || `subtitles_${jobId}.srt`)
          : (job.burned_filename || `subtitled_${jobId}.mp4`);
        const m = cd.match(/filename\*?=(?:UTF-8''|"?)([^";\n]+)/i);
        if (m?.[1]) {
          const raw = m[1].replaceAll('"', "").trim();
          try {
            filename = decodeURIComponent(raw);
          } catch {
            filename = raw;
          }
        }

        const url2 = URL.createObjectURL(blob);
        a.href = url2;
        a.download = filename;
        a.click();
        setTimeout(() => URL.revokeObjectURL(url2), 2000);
      })
      .catch(() => showToast("Ошибка скачивания файла", "err"))
      .finally(() => a.remove());
  }

  const isRunning = job.status === "pending" || job.status === "running";
  const isDone = job.status === "done";
  const isError = job.status === "error";
  const curStep = stepIndex(job.step);
  const showBurnStep = burn;

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
          AI Субтитры
        </div>
        <div style={{ fontSize: 13, color: "var(--text-tertiary)", marginTop: 3 }}>
          Groq Whisper транскрипция + автоперевод → скачать .srt или видео с субтитрами
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 340px", gap: 16, alignItems: "start" }}>

        {/* ── Left: form ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div className="card">
            <div className="card-header">
              <span className="card-title">Источник видео</span>
            </div>
            <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ display: "flex", gap: 8 }}>
                <div style={{ position: "relative", flex: 1 }}>
                  <input
                    ref={inputRef}
                    className="form-input"
                    placeholder="YouTube Shorts, TikTok, Kick — ссылка на видео…"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter" && url.trim() && !isRunning) void handleSubmit(); }}
                    style={{ fontSize: 13, paddingRight: url ? 36 : undefined }}
                    disabled={isRunning}
                  />
                  {url && (
                    <button type="button" onClick={() => setUrl("")}
                      style={{ position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)", background: "none", border: "none", cursor: "pointer", color: "var(--text-tertiary)", display: "flex", alignItems: "center" }}
                      aria-label="Очистить">
                      <X {...U14} />
                    </button>
                  )}
                </div>
                <button type="button" className="btn-v3 btn-v3-ghost"
                  onClick={pasteFromClipboard} disabled={isRunning}
                  style={{ flexShrink: 0, gap: 6, padding: "0 13px" }}>
                  <Clipboard {...U14} aria-hidden />
                  Вставить
                </button>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                <div>
                  <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginBottom: 5 }}>Язык оригинала</div>
                  <select className="form-input" value={sourceLang}
                    onChange={(e) => setSourceLang(e.target.value)} disabled={isRunning}
                    style={{ fontSize: 12, width: "100%" }}>
                    {LANGS.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
                  </select>
                </div>
                <div>
                  <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginBottom: 5 }}>Перевести на</div>
                  <select className="form-input" value={targetLang}
                    onChange={(e) => setTargetLang(e.target.value)} disabled={isRunning}
                    style={{ fontSize: 12, width: "100%" }}>
                    {LANGS.filter((l) => l.code).map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
                  </select>
                </div>
              </div>

              <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", userSelect: "none" }}>
                <input type="checkbox" checked={burn} onChange={(e) => setBurn(e.target.checked)}
                  disabled={isRunning}
                  style={{ accentColor: "var(--accent-cyan)", width: 14, height: 14 }} />
                <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>
                  Вжечь субтитры в видео
                  <span style={{ fontSize: 10, color: "var(--text-tertiary)", marginLeft: 6 }}>+2-5 мин</span>
                </span>
              </label>

              <button type="button"
                className={`btn-v3 ${url.trim() && !isRunning ? "btn-v3-primary" : ""}`}
                disabled={!url.trim() || isRunning}
                onClick={() => void handleSubmit()}
                style={{ fontWeight: 700, fontSize: 13, gap: 8 }}>
                {isRunning ? (
                  <><span className="spinner-sm" />{job.step || "Обработка…"}</>
                ) : (
                  <>
                    <MessageSquare {...U15} aria-hidden />
                    Сгенерировать субтитры
                  </>
                )}
              </button>
            </div>
          </div>

          {/* ── Result ── */}
          {isDone && (
            <div className="card">
              <div className="card-header">
                <span className="card-title" style={{ color: "var(--accent-green)" }}>
                  <Check {...U14} strokeWidth={2.5} color="var(--accent-green)" style={{ marginRight: 6 }} aria-hidden />
                  Субтитры готовы
                </span>
                <span style={{ fontSize: 11, color: "var(--text-tertiary)" }}>
                  {job.segment_count} реплик · {LANGS.find((l) => l.code === job.target_lang)?.label ?? job.target_lang}
                </span>
              </div>
              <div className="card-body" style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                <button type="button" className="btn-v3 btn-v3-primary"
                  onClick={() => downloadFile("srt")}
                  style={{ gap: 8, fontWeight: 700 }}>
                  <Download {...U15} aria-hidden />
                  Скачать .srt
                </button>

                <button type="button" className="btn-v3 btn-v3-ghost"
                  onClick={() => downloadFile("ass")}
                  style={{ gap: 8 }}
                  title="ASS — субтитры с fade-анимацией (для Premiere, DaVinci, Aegisub)">
                  <Download {...U15} aria-hidden />
                  Скачать .ass
                </button>

                {job.burned_path && (
                  <button type="button" className="btn-v3 btn-v3-ghost"
                    onClick={() => downloadFile("video")}
                    style={{ gap: 8 }}>
                    <Video {...U15} aria-hidden />
                    Скачать видео с субтитрами
                  </button>
                )}

                <button type="button" className="btn-v3 btn-v3-ghost"
                  onClick={() => { setJob({ status: "idle" }); setJobId(null); setUrl(""); }}
                  style={{ marginLeft: "auto", fontSize: 11 }}>
                  Новый
                </button>
              </div>
            </div>
          )}

          {isError && (
            <div className="card" style={{ borderColor: "var(--accent-red)" }}>
              <div className="card-body" style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <AlertTriangle size={18} color="var(--accent-red)" />
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "var(--accent-red)" }}>Ошибка генерации</div>
                  <div style={{ fontSize: 12, color: "var(--text-tertiary)", marginTop: 3 }}>{job.message}</div>
                </div>
                <button type="button" className="btn-v3 btn-v3-sm btn-v3-ghost"
                  onClick={() => { setJob({ status: "idle" }); setJobId(null); }}
                  style={{ marginLeft: "auto" }}>Повторить</button>
              </div>
            </div>
          )}
        </div>

        {/* ── Right: progress + info ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>

          {/* Progress steps */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">Прогресс</span>
              {isRunning && <span className="spinner-sm" style={{ color: "var(--accent-cyan)" }} />}
            </div>
            <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 0 }}>
              {STEPS.filter((s) => s.key !== "burn" || showBurnStep).map((s, idx) => {
                const realIdx = STEPS.filter((x) => x.key !== "burn" || showBurnStep).indexOf(s);
                const done = isDone || curStep > realIdx;
                const active = isRunning && curStep === realIdx;
                const _pending = !done && !active; void _pending;
                return (
                  <div key={s.key} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 0",
                    borderBottom: idx < STEPS.filter((x) => x.key !== "burn" || showBurnStep).length - 1 ? "1px solid var(--border-subtle)" : "none" }}>
                    <div style={{
                      width: 22, height: 22, borderRadius: "50%", flexShrink: 0,
                      display: "flex", alignItems: "center", justifyContent: "center",
                      background: done ? "var(--accent-green)" : active ? "var(--accent-cyan)" : "var(--bg-elevated)",
                      border: `1.5px solid ${done ? "var(--accent-green)" : active ? "var(--accent-cyan)" : "var(--border-default)"}`,
                      fontSize: 10, fontWeight: 700,
                    }}>
                      {done
                        ? <Check size={11} strokeWidth={3} color="#fff" aria-hidden />
                        : active
                        ? <span className="spinner-sm" style={{ width: 10, height: 10, borderTopColor: "var(--bg-deep)" }} />
                        : <span style={{ color: "var(--text-tertiary)", fontSize: 9 }}>{realIdx + 1}</span>}
                    </div>
                    <span style={{
                      fontSize: 12,
                      color: done ? "var(--text-primary)" : active ? "var(--accent-cyan)" : "var(--text-tertiary)",
                      fontWeight: active ? 600 : 400,
                    }}>{s.label}</span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Info card */}
          <div className="card">
            <div className="card-header">
              <span className="card-title" style={{ fontSize: 11 }}>Как это работает</span>
            </div>
            <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {[
                { icon: <Mic2 size={15} />, title: "Groq Whisper", text: "Распознаёт речь с точными таймингами" },
                { icon: <Bot size={15} />, title: "LLaMA 3.1", text: "Переводит субтитры сохраняя стиль" },
                { icon: <FileText size={15} />, title: ".srt файл", text: "Универсальный формат для любого плеера" },
                { icon: <Clapperboard size={15} />, title: "Вжигание", text: "Копия видео с субтитрами через ffmpeg" },
              ].map((tip) => (
                <div key={tip.title} style={{ display: "flex", gap: 8 }}>
                  <span style={{ display: "flex", alignItems: "center", justifyContent: "center", width: 16, color: "var(--text-secondary)", flexShrink: 0 }}>{tip.icon}</span>
                  <div>
                    <div style={{ fontSize: 11, fontWeight: 700, color: "var(--text-primary)" }}>{tip.title}</div>
                    <div style={{ fontSize: 10, color: "var(--text-tertiary)", lineHeight: 1.5 }}>{tip.text}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <style>{`
        .spinner-sm {
          display: inline-block; width: 11px; height: 11px;
          border: 2px solid rgba(255,255,255,0.2); border-top-color: currentColor;
          border-radius: 50%; animation: spin 0.7s linear infinite; flex-shrink: 0;
        }
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}
