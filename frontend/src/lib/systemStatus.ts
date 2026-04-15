import type { ApiJson } from "@/api";

export type StatusLine = { label: string; value: string; kind: string };

function shortFfmpegVersion(raw: unknown): string {
  const text = String(raw || "").trim();
  if (!text) return "OK";
  const m = text.match(/version\s+([^\s]+)/i);
  const token = (m?.[1] || text).trim();
  // "8.1-full_build-..." -> "8.1", but keep non-standard tokens as-is.
  if (/^\d+(\.\d+)+([-.].*)?$/.test(token)) {
    return token.split("-")[0];
  }
  return token.length > 16 ? `${token.slice(0, 16)}…` : token;
}

/** Строки для блока «Состояние системы» (дашборд, настройки). */
export function buildSystemStatusLines(
  system: ApiJson | undefined,
  ping: ApiJson | undefined,
): StatusLine[] {
  if (!system) return [];
  const sys = system;
  const groqConfigured = Boolean(sys.groq_configured);
  let groqLine = groqConfigured ? "Ключ задан" : "Ключ не задан";
  let groqKind = groqConfigured ? "good" : "warn";
  if (ping?.status === "ok" && ping.groq && typeof ping.groq === "object") {
    const g = ping.groq as ApiJson;
    const live = Boolean(g.live);
    const extra = String(g.message || "").trim();
    const redundant = extra && groqLine.includes(extra);
    groqLine += ` · ${live ? "✓" : "✗"}`;
    if (extra && !redundant) groqLine += ` ${extra}`;
    else if (!extra) groqLine += live ? " OK" : "";
    groqKind = live ? "good" : "warn";
  }

  const adsBase = String(sys.adspower_api_base || "—");
  let adsLine = adsBase;
  let adsKind = "good";
  if (ping?.status === "ok" && ping.adspower && typeof ping.adspower === "object") {
    const a = ping.adspower as ApiJson;
    const live = Boolean(a.live);
    adsLine = `${adsBase} · ${live ? "✓ " : "✗ "}${String(a.message || "")}`;
    if (!live) adsKind = "warn";
    if (live && a.profiles_count != null) {
      adsLine += ` (${a.profiles_count} проф.)`;
    }
  }

  let ffmpegLine = "Не найден";
  let ffmpegKind = "warn";
  if (sys.ffmpeg_runs === true) {
    ffmpegLine = shortFfmpegVersion(sys.ffmpeg_version);
    ffmpegKind = "good";
  } else if (sys.ffmpeg_found === true) {
    ffmpegLine = `Не запускается (${shortFfmpegVersion(sys.ffmpeg_version)})`;
    ffmpegKind = "warn";
  } else {
    ffmpegLine = "Не в PATH";
  }

  return [
    { label: "Overlay PNG", value: sys.overlay_exists ? "Готов" : "Не найден", kind: sys.overlay_exists ? "good" : "warn" },
    { label: "FFmpeg", value: ffmpegLine, kind: ffmpegKind },
    { label: "Groq", value: groqLine, kind: groqKind },
    { label: "AdsPower API", value: adsLine, kind: adsKind },
    {
      label: "AdsPower Auth",
      value: sys.adspower_use_auth ? "Bearer включен" : "Выключен",
      kind: sys.adspower_use_auth ? "good" : "warn",
    },
    {
      label: "AdsPower API Key",
      value: sys.adspower_api_key_configured ? "Задан" : "Не задан",
      kind: sys.adspower_api_key_configured ? "good" : "warn",
    },
  ];
}
