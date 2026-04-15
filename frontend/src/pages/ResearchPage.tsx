import { useState, useMemo, useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, Check, Download, Eye, Heart, MessageCircle, Save, Search, SlidersHorizontal, Users } from "lucide-react";
import { apiFetch, apiUrl, type ApiJson } from "@/api";
import { uiIconProps } from "@/components/icons/uiIconProps";
import { useTenant } from "@/tenant/TenantContext";

const R12 = uiIconProps(12);
const R14 = uiIconProps(14);

// ── Types ────────────────────────────────────────────────────────────────────
type VideoResult = {
  id: string;
  title: string;
  url: string;
  thumbnail: string;
  duration: number;
  view_count: number;
  like_count?: number;
  comment_count?: number;
  upload_date: string;
  channel: string;
  channel_url?: string;
  source: string;
  region?: string;
  arb_score?: number;
  watchlist_hit?: boolean;
  watchlist_match?: string;
};

type QueuedFile = { filename: string; path: string; size_mb: number; modified: number };

type BreakdownItem = { pts: number; value?: number; rate?: number; likes?: number; comments?: number; seconds?: number; platform?: string };

type AdviceResult = {
  score: number;
  risk: "low" | "medium" | "high";
  preset: string;
  reasons: string[];
  action_plan: string[];
  breakdown?: Record<string, BreakdownItem>;
  engagement_rate?: number;
  viral_coeff?: number;
  ai_title?: string;
  ai_description?: string;
  ai_comment?: string;
  overlay_text?: string;
  used_fallback?: boolean;
};

type SavedPreset = { id: string; name: string; niche: string; source: string; period: number; region: string };
type ArbScanResults = Record<string, VideoResult[]>;
type ArbMonitorSettings = {
  alerts_enabled: boolean;
  score_threshold: number;
  alert_max_items: number;
  watchlist_channels: string[];
};

/** Порядок вкладок в «Арбитраж скан» (совпадает с бэкендом). */
const ARB_GAMES = [
  { key: "tower_rust", label: "Tower Rust", color: "#F59E0B" },
  { key: "mine_drop", label: "Mine Drop", color: "#EF4444" },
  { key: "aviator", label: "Avia Master", color: "#3B82F6" },
  { key: "ice_fishing", label: "Ice Fishing", color: "#06B6D4" },
] as const;

// ── Constants ────────────────────────────────────────────────────────────────
const SOURCES = [
  { value: "youtube", label: "YouTube Shorts", available: true },
  { value: "tiktok", label: "TikTok", available: false },
  { value: "instagram", label: "Reels", available: false },
];

const PERIODS = [
  { value: 1, label: "24ч" },
  { value: 2, label: "48ч" },
  { value: 7, label: "7д" },
  { value: 30, label: "30д" },
];

const REGIONS = [
  { value: "KR", label: "KR" },
  { value: "TH", label: "TH" },
  { value: "MY", label: "MY" },
  { value: "JP", label: "JP" },
  { value: "ID", label: "ID" },
  { value: "US", label: "US" },
  { value: "VN", label: "🇻🇳 VN" },
  { value: "RU", label: "🇷🇺 RU" },
];

const SORT_OPTIONS = [
  { value: "views", label: "По просмотрам" },
  { value: "engagement", label: "По вовлечённости" },
  { value: "duration", label: "По длительности" },
  { value: "date", label: "По дате" },
];

const DURATION_FILTERS = [
  { value: "all", label: "Все" },
  { value: "short", label: "<30с" },
  { value: "medium", label: "30–60с" },
  { value: "long", label: ">60с" },
];

const VIEWS_FILTERS = [
  { value: "all", label: "Все" },
  { value: "10k", label: "10K+" },
  { value: "100k", label: "100K+" },
  { value: "1m", label: "1M+" },
];

type PresetTag = { label: string; value: string };
type PresetGroup = {
  label: string;
  color: string;
  source: "youtube";
  region: "KR" | "TH" | "MY" | "JP" | "ID" | "US";
  period: number;
  note: string;
  presets: PresetTag[];
};

const PRESET_GROUPS: PresetGroup[] = [
  {
    label: "Казино",
    color: "#F23F5D",
    source: "youtube",
    region: "KR",
    period: 2,
    note: "Высокий CPM, быстрый отклик",
    presets: [
      { label: "한국 카지노", value: "한국 카지노 대박" },
      { label: "Korean Casino Win", value: "korean casino big win shorts" },
      { label: "Korean Slots", value: "korean slots jackpot" },
      { label: "카지노 대박", value: "카지노 슬롯 대박 jackpot" },
      { label: "Seoul Casino", value: "seoul casino highlight" },
    ],
  },
  {
    label: "Развлечения",
    color: "#FBBF24",
    source: "youtube",
    region: "KR",
    period: 7,
    note: "Вирусный охват и реакция",
    presets: [
      { label: "한국 반응", value: "한국 반응 모음 shorts" },
      { label: "Korean Reaction", value: "korean reaction funny compilation" },
      { label: "Korean Prank", value: "korean prank viral shorts" },
      { label: "K-Drama Scenes", value: "kdrama viral scene shorts" },
      { label: "Korean Street", value: "korean street food challenge" },
    ],
  },
  {
    label: "Финансы",
    color: "#4ADE80",
    source: "youtube",
    region: "US",
    period: 7,
    note: "Платежеспособная аудитория",
    presets: [
      { label: "한국 부자", value: "한국 부자 라이프 shorts" },
      { label: "Korean Crypto", value: "korean crypto profit shorts" },
      { label: "Seoul Rich Life", value: "seoul luxury lifestyle" },
      { label: "Korean Trading", value: "korean trading win story" },
      { label: "K-Money Hack", value: "korean money saving tips shorts" },
    ],
  },
  {
    label: "Вирусное",
    color: "#A78BFA",
    source: "youtube",
    region: "KR",
    period: 1,
    note: "Максимум трендового трафика",
    presets: [
      { label: "K-Viral Fails", value: "korean viral fail compilation" },
      { label: "K-Challenge", value: "korea trending challenge shorts" },
      { label: "Korean OMG", value: "korea omg moments shorts" },
      { label: "BTS Reaction", value: "bts reaction kpop shorts" },
      { label: "K-Food Trend", value: "korean food trend viral" },
    ],
  },
  {
    label: "Игры",
    color: "#38BDF8",
    source: "youtube",
    region: "JP",
    period: 2,
    note: "Стабильная вовлеченность",
    presets: [
      { label: "Korean Gaming", value: "korean gaming highlights shorts" },
      { label: "K-Esports", value: "korea esports highlights" },
      { label: "Korean Gamer", value: "korean pro gamer moments" },
      { label: "리그오브레전드", value: "리그오브레전드 하이라이트 shorts" },
    ],
  },
  {
    label: "Арбитраж",
    color: "#F59E0B",
    source: "youtube",
    region: "KR",
    period: 2,
    note: "Tower · Mine · Aviator · Ice Fishing",
    presets: [
      { label: "Tower big win", value: "tower game big win shorts" },
      { label: "Tower x100", value: "tower game x100 win" },
      { label: "타워 대박", value: "타워 게임 대박 shorts" },
      { label: "Mines cashout", value: "mines game big win shorts" },
      { label: "Mine Drop win", value: "mine drop win cashout" },
      { label: "마인 대박", value: "마인 게임 대박 shorts" },
      { label: "Aviator win", value: "aviator game big win shorts" },
      { label: "Aviator x100", value: "aviator x100 cashout" },
      { label: "아비에이터 대박", value: "아비에이터 대박 shorts" },
      { label: "Ice Fishing win", value: "ice fishing game big win shorts" },
      { label: "Ice Fishing jackpot", value: "ice fishing slot jackpot" },
      { label: "아이스 피싱", value: "아이스 피싱 대박 shorts" },
    ],
  },
];

const RISK_COLOR: Record<string, string> = {
  low: "var(--accent-green)",
  medium: "var(--accent-amber)",
  high: "var(--accent-red)",
};

const RISK_LABEL: Record<string, string> = {
  low: "Низкий риск",
  medium: "Средний риск",
  high: "Высокий риск",
};

const THUMBNAIL_GRADIENTS = [
  "linear-gradient(160deg,#1a2a18 0%,#0d3d2a 100%)",
  "linear-gradient(160deg,#1a1f2e 0%,#2a2040 100%)",
  "linear-gradient(160deg,#2a1a1a 0%,#3d1a0d 100%)",
  "linear-gradient(160deg,#1a2830 0%,#0d2a3d 100%)",
  "linear-gradient(160deg,#28201a 0%,#3d2a0d 100%)",
  "linear-gradient(160deg,#201a28 0%,#0d1a3d 100%)",
  "linear-gradient(160deg,#1a1a2a 0%,#2a0d3d 100%)",
  "linear-gradient(160deg,#2a1a28 0%,#3d0d2a 100%)",
];

// ── Helpers ───────────────────────────────────────────────────────────────────
function formatDuration(sec: number) {
  if (!sec) return "";
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function formatNum(n: number) {
  if (!n) return "—";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function timeAgo(dateStr: string) {
  if (!dateStr) return "";
  try {
    let d: Date;
    const compact = dateStr.replace(/-/g, "").replace("T", "").slice(0, 8);
    if (/^\d{8}$/.test(compact)) {
      const y = parseInt(compact.slice(0, 4), 10);
      const mo = parseInt(compact.slice(4, 6), 10) - 1;
      const day = parseInt(compact.slice(6, 8), 10);
      d = new Date(Date.UTC(y, mo, day, 12, 0, 0));
    } else {
      d = new Date(dateStr);
    }
    if (Number.isNaN(d.getTime())) return "";
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 0) return "";
    if (diff < 3600) return `${Math.floor(diff / 60)}м назад`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}ч назад`;
    return `${Math.floor(diff / 86400)}д назад`;
  } catch { return ""; }
}

function sourceLabel(s: string) {
  if (s === "youtube") return "YT Shorts";
  if (s === "tiktok") return "TikTok";
  if (s === "instagram") return "Reels";
  return s;
}

function sourceBadgeStyle(s: string): React.CSSProperties {
  const base: React.CSSProperties = {
    position: "absolute", top: 8, right: 8, padding: "2px 7px",
    borderRadius: 4, fontSize: 10, fontWeight: 700, letterSpacing: "0.3px",
    fontFamily: "var(--font-mono)",
  };
  if (s === "youtube") return { ...base, background: "#FF0000", color: "#fff" };
  if (s === "tiktok") return { ...base, background: "#010101", color: "#fff", border: "1px solid #888" };
  return { ...base, background: "#E1306C", color: "#fff" };
}

function hotBadge(v: number, idx: number): { label: string; bg: string } | null {
  if (v >= 1_000_000 || idx === 0) return { label: "HOT", bg: "#F23F5D" };
  if (v >= 200_000 && idx <= 3) return { label: "HOT", bg: "#F23F5D" };
  if (idx <= 2 && v >= 20_000) return { label: "NEW", bg: "#FBBF24" };
  return null;
}

function computeEngagement(v: VideoResult) {
  const vc = v.view_count || 0;
  const lc = v.like_count || 0;
  const cc = v.comment_count || 0;
  if (!vc || (!lc && !cc)) return 0;
  return (lc + cc * 3) / vc * 100;
}

function normalizeWatchlistEntry(raw: string): string {
  const v = raw.trim();
  if (!v) return "";
  let s = v.replace(/^https?:\/\//i, "").replace(/^www\./i, "");
  s = s.replace(/\/+$/, "");
  const lower = s.toLowerCase();

  if (lower.startsWith("youtube.com/channel/")) {
    const id = s.split("youtube.com/channel/")[1]?.split(/[/?#]/)[0] || "";
    return id.trim();
  }
  if (lower.startsWith("youtube.com/@")) {
    const handle = s.split("youtube.com/@")[1]?.split(/[/?#]/)[0] || "";
    return handle ? `@${handle.trim()}` : "";
  }
  if (lower.startsWith("@")) return s;
  return s;
}

function validateWatchlistEntry(raw: string): { ok: boolean; normalized: string; reason?: string } {
  const normalized = normalizeWatchlistEntry(raw);
  if (!normalized) return { ok: false, normalized: "", reason: "Пустое значение" };
  if (normalized.startsWith("@")) {
    const handle = normalized.slice(1);
    if (!/^[A-Za-z0-9._-]{3,40}$/.test(handle)) {
      return { ok: false, normalized, reason: "Некорректный @handle" };
    }
    return { ok: true, normalized };
  }
  if (/^UC[0-9A-Za-z_-]{10,}$/.test(normalized)) {
    return { ok: true, normalized };
  }
  if (/^[A-Za-z0-9._-]{3,120}$/.test(normalized) && !normalized.includes("/")) {
    return { ok: true, normalized };
  }
  return { ok: false, normalized, reason: "Введите channel_id, @handle или URL YouTube-канала" };
}

function loadSavedPresets(): SavedPreset[] {
  try { return JSON.parse(localStorage.getItem("research_presets") || "[]"); } catch { return []; }
}

function saveSavedPresets(presets: SavedPreset[]) {
  localStorage.setItem("research_presets", JSON.stringify(presets));
}

// ── Score Ring ───────────────────────────────────────────────────────────────
function ScoreRing({ score, risk }: { score: number; risk: string }) {
  const r = 22; const circ = 2 * Math.PI * r;
  const fill = (score / 100) * circ;
  const color = RISK_COLOR[risk] ?? "var(--accent-cyan)";
  return (
    <svg width="58" height="58" viewBox="0 0 58 58" style={{ flexShrink: 0 }}>
      <circle cx="29" cy="29" r={r} fill="none" stroke="var(--bg-elevated)" strokeWidth="5" />
      <circle cx="29" cy="29" r={r} fill="none" stroke={color} strokeWidth="5"
        strokeDasharray={`${fill} ${circ - fill}`} strokeLinecap="round"
        transform="rotate(-90 29 29)" style={{ transition: "stroke-dasharray 0.5s ease" }} />
      <text x="29" y="29" textAnchor="middle" dominantBaseline="central"
        style={{ fontSize: 14, fontWeight: 800, fill: color, fontFamily: "var(--font-mono)" }}>
        {score}
      </text>
    </svg>
  );
}

function MiniBar({ pts, maxPts, color }: { pts: number; maxPts: number; color: string }) {
  const pct = Math.max(0, Math.min(100, ((pts + maxPts) / (maxPts * 2)) * 100));
  return (
    <div style={{ flex: 1, height: 5, background: "var(--bg-elevated)", borderRadius: 3, overflow: "hidden" }}>
      <div style={{ width: `${pct}%`, height: "100%", background: color, borderRadius: 3, transition: "width 0.4s ease" }} />
    </div>
  );
}

function ResearchSkeletonGrid() {
  return (
    <div className="research-skeleton-grid" aria-hidden>
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="research-skeleton-card">
          <div className="research-skeleton-thumb shimmer" />
          <div className="research-skeleton-lines">
            <div className="research-skeleton-line shimmer" />
            <div className="research-skeleton-line short shimmer" />
            <div className="research-skeleton-chips">
              <span className="research-skeleton-chip shimmer" />
              <span className="research-skeleton-chip shimmer" />
              <span className="research-skeleton-chip shimmer" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Segmented control helper ─────────────────────────────────────────────────
function SegControl<T extends string | number>({
  options, value, onChange, small,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  small?: boolean;
}) {
  return (
    <div style={{ display: "flex", gap: 3, background: "var(--bg-elevated)", borderRadius: 6, padding: 3 }}>
      {options.map((o) => (
        <button key={String(o.value)} type="button" onClick={() => onChange(o.value)}
          style={{
            padding: small ? "3px 8px" : "5px 10px", borderRadius: 4, border: "none",
            fontSize: small ? 11 : 12, fontWeight: 600,
            background: value === o.value ? "var(--bg-surface)" : "transparent",
            color: value === o.value ? "var(--text-primary)" : "var(--text-tertiary)",
            cursor: "pointer", transition: "all 0.15s", whiteSpace: "nowrap",
            boxShadow: value === o.value ? "0 1px 3px rgba(0,0,0,0.3)" : "none",
          }}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────
export function ResearchPage() {
  const { tenantId } = useTenant();
  const qc = useQueryClient();

  // Search params
  const [niche, setNiche] = useState("");
  const [source, setSource] = useState("youtube");
  const [period, setPeriod] = useState(7);
  const [region, setRegion] = useState("KR");

  // Results + processing
  const [results, setResults] = useState<VideoResult[]>([]);
  const [toast, setToast] = useState<{ msg: string; kind: "ok" | "err" } | null>(null);
  const [downloadStartedAt, setDownloadStartedAt] = useState<Record<string, number>>({});
  const [downloadedIds, setDownloadedIds] = useState<Set<string>>(new Set());
  const [downloadErrors, setDownloadErrors] = useState<Record<string, string>>({});
  const [adviceById, setAdviceById] = useState<Record<string, AdviceResult>>({});
  const [adviceOpenId, setAdviceOpenId] = useState<string | null>(null);

  // Sort & filter
  const [sortBy, setSortBy] = useState<string>("views");
  const [durationFilter, setDurationFilter] = useState("all");
  const [viewsFilter, setViewsFilter] = useState("all");
  const [showFilters, setShowFilters] = useState(false);

  // Batch select
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [batchLoading, setBatchLoading] = useState(false);

  // Presets
  const [activeGroup, setActiveGroup] = useState<string | null>(null);
  const [savedPresets, setSavedPresets] = useState<SavedPreset[]>(loadSavedPresets);
  const [showSavePreset, setShowSavePreset] = useState(false);
  const [newPresetName, setNewPresetName] = useState("");

  // Arbitrage scan (регион не задаётся — бэкенд ищет по всему миру, только Shorts)
  const [arbScanResults, setArbScanResults] = useState<ArbScanResults | null>(null);
  const [arbScanPeriod, setArbScanPeriod] = useState(7);
  const [arbExpandedGame, setArbExpandedGame] = useState<string | null>(null);
  const [arbShowMonitorSettings, setArbShowMonitorSettings] = useState(false);
  const [watchlistDraft, setWatchlistDraft] = useState("");
  const [watchlistTouched, setWatchlistTouched] = useState(false);
  const [arbMonitorSettings, setArbMonitorSettings] = useState<ArbMonitorSettings>({
    alerts_enabled: true,
    score_threshold: 72,
    alert_max_items: 5,
    watchlist_channels: [],
  });

  /** Активная вкладка игры: выбранная пользователем или первая с роликами. */
  const arbPanelGameKey = useMemo(() => {
    if (!arbScanResults) return null;
    const keys = ARB_GAMES.map((g) => g.key);
    if (arbExpandedGame && keys.includes(arbExpandedGame)) return arbExpandedGame;
    return keys.find((k) => (arbScanResults[k]?.length ?? 0) > 0) ?? keys[0];
  }, [arbScanResults, arbExpandedGame]);

  // ── Mutations / queries ─────────────────────────────────────────────────
  const searchMut = useMutation({
    mutationFn: (override?: Partial<{ niche: string; source: string; period: number; region: string }>) =>
      apiFetch<ApiJson>("/api/research/search", {
        method: "POST", tenantId,
        body: JSON.stringify({
          niche: (override?.niche ?? niche).trim(),
          source: override?.source ?? source,
          period_days: override?.period ?? period,
          limit: 12,
          region: override?.region ?? region,
        }),
      }),
    onSuccess: (data) => {
      setResults((data.results as VideoResult[]) ?? []);
      setSelected(new Set());
      if (!(data.results as unknown[])?.length) showToast("Ничего не найдено по этому запросу", "err");
    },
    onError: (e: Error) => showToast(e.message, "err"),
  });

  const queueQ = useQuery({
    queryKey: ["research-queue", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/research/queue", { tenantId }),
    staleTime: 10_000,
    refetchInterval: 15_000,
  });

  const downloadMut = useMutation({
    mutationFn: async (video: VideoResult) => {
      const resp = await fetch(apiUrl("/api/research/download/browser"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Tenant-ID": tenantId,
        },
        body: JSON.stringify({ url: video.url }),
      });
      if (!resp.ok) {
        try {
          const j = await resp.json();
          throw new Error(String(j?.message || `HTTP ${resp.status}`));
        } catch {
          throw new Error(`HTTP ${resp.status}`);
        }
      }
      const blob = await resp.blob();
      const cd = resp.headers.get("content-disposition") || "";
      const m = cd.match(/filename=\"?([^\";]+)\"?/i);
      const filename = (m?.[1] || `${video.id}.mp4`).trim();
      const objectUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = objectUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(objectUrl), 1500);
      return { filename };
    },
    onMutate: (video) => {
      setDownloadStartedAt((prev) => ({ ...prev, [video.id]: Date.now() }));
      setDownloadedIds((prev) => {
        const next = new Set(prev);
        next.delete(video.id);
        return next;
      });
      setDownloadErrors((prev) => {
        const next = { ...prev };
        delete next[video.id];
        return next;
      });
    },
    onSuccess: (_data, video) => {
      setDownloadedIds((prev) => new Set([...prev, video.id]));
      void qc.invalidateQueries({ queryKey: ["research-queue", tenantId] });
      showToast(`Видео ${video.id} скачано в браузер`, "ok");
    },
    onError: (e: Error, video) => {
      setDownloadErrors((prev) => ({ ...prev, [video.id]: e.message || "Ошибка скачивания" }));
      showToast(e.message, "err");
    },
  });

  const arbScanMut = useMutation({
    mutationFn: (_?: undefined) =>
      apiFetch<ApiJson>("/api/research/arbitrage-scan", {
        method: "POST", tenantId,
        body: JSON.stringify({ period_days: arbScanPeriod, limit_per_query: 5 }),
      }),
    onSuccess: (data) => {
      const res = data.results as ArbScanResults | undefined;
      const next = res ?? {};
      setArbScanResults(next);
      const keys = ARB_GAMES.map((g) => g.key);
      const pick = keys.find((k) => (next[k]?.length ?? 0) > 0) ?? keys[0] ?? null;
      setArbExpandedGame(pick);
      const monitor = data.monitor as { alerts_sent?: number } | undefined;
      const alerts = Number(monitor?.alerts_sent || 0);
      showToast(alerts > 0 ? `Скан завершён · отправлено алертов: ${alerts}` : "Скан завершён", "ok");
    },
    onError: (e: Error) => showToast(e.message, "err"),
  });

  const arbMonitorQ = useQuery({
    queryKey: ["arb-monitor-settings", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/settings/arbitrage-monitor", { tenantId }),
    staleTime: 30_000,
  });

  const saveArbMonitorMut = useMutation({
    mutationFn: (payload: ArbMonitorSettings) =>
      apiFetch<ApiJson>("/api/settings/arbitrage-monitor", {
        method: "POST",
        tenantId,
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      showToast("Настройки мониторинга сохранены", "ok");
      void arbMonitorQ.refetch();
    },
    onError: (e: Error) => showToast(e.message, "err"),
  });

  useEffect(() => {
    const s = arbMonitorQ.data as Partial<ArbMonitorSettings> | undefined;
    if (!s) return;
    setArbMonitorSettings({
      alerts_enabled: Boolean(s.alerts_enabled ?? true),
      score_threshold: Math.max(1, Math.min(Number(s.score_threshold ?? 72), 100)),
      alert_max_items: Math.max(1, Math.min(Number(s.alert_max_items ?? 5), 10)),
      watchlist_channels: Array.isArray(s.watchlist_channels) ? s.watchlist_channels.map((x) => String(x).trim()).filter(Boolean) : [],
    });
  }, [arbMonitorQ.data]);

  const adviceMut = useMutation({
    mutationFn: (video: VideoResult) =>
      apiFetch<ApiJson>("/api/research/advice", {
        method: "POST", tenantId,
        body: JSON.stringify({
          title: video.title, channel: video.channel, url: video.url,
          source: video.source, view_count: video.view_count,
          like_count: video.like_count ?? 0,
          comment_count: video.comment_count ?? 0,
          duration: video.duration, niche: niche.trim(),
        }),
      }),
    onSuccess: (data, video) => {
      const advice = data.advice as AdviceResult | undefined;
      if (advice) {
        setAdviceById((prev) => ({ ...prev, [video.id]: advice }));
        setAdviceOpenId(video.id);
        showToast("AI анализ готов", "ok");
      }
    },
    onError: (e: Error) => showToast(e.message, "err"),
  });

  // ── Helpers ───────────────────────────────────────────────────────────────
  function showToast(msg: string, kind: "ok" | "err") {
    setToast({ msg, kind });
    setTimeout(() => setToast(null), 4000);
  }

  function applyPreset(value: string, opts?: Partial<SavedPreset>, autoSearch = true) {
    const nextSource = opts?.source ?? source;
    const nextPeriod = opts?.period ?? period;
    const nextRegion = opts?.region ?? region;
    setNiche(value);
    setSource(nextSource);
    setPeriod(nextPeriod);
    setRegion(nextRegion);
    if (autoSearch) {
      void searchMut.mutate({ niche: value, source: nextSource, period: nextPeriod, region: nextRegion });
    }
  }

  function savePreset() {
    if (!newPresetName.trim() || !niche.trim()) return;
    const p: SavedPreset = {
      id: Date.now().toString(),
      name: newPresetName.trim(),
      niche: niche.trim(),
      source, period, region,
    };
    const next = [p, ...savedPresets].slice(0, 20);
    setSavedPresets(next);
    saveSavedPresets(next);
    setNewPresetName("");
    setShowSavePreset(false);
    showToast(`Пресет «${p.name}» сохранён`, "ok");
  }

  function deletePreset(id: string) {
    const next = savedPresets.filter((p) => p.id !== id);
    setSavedPresets(next);
    saveSavedPresets(next);
  }

  async function batchDownload() {
    if (!selected.size) return;
    setBatchLoading(true);
    const selectedVideos = results.filter((v) => selected.has(v.id));
    for (const video of selectedVideos) {
      try { await downloadMut.mutateAsync(video); } catch { /* continue */ }
    }
    setBatchLoading(false);
    showToast(`Запущена загрузка ${selectedVideos.length} видео`, "ok");
    setSelected(new Set());
  }

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  function addWatchlistChannel() {
    const check = validateWatchlistEntry(watchlistDraft);
    if (!check.ok) return;
    const value = check.normalized;
    setArbMonitorSettings((prev) => {
      const norm = value.toLowerCase();
      const exists = prev.watchlist_channels.some((x) => x.toLowerCase() === norm);
      if (exists) return prev;
      return { ...prev, watchlist_channels: [...prev.watchlist_channels, value] };
    });
    setWatchlistDraft("");
    setWatchlistTouched(false);
  }

  function removeWatchlistChannel(value: string) {
    setArbMonitorSettings((prev) => ({
      ...prev,
      watchlist_channels: prev.watchlist_channels.filter((x) => x !== value),
    }));
  }

  function selectAll() {
    if (selected.size === filteredSorted.length) setSelected(new Set());
    else setSelected(new Set(filteredSorted.map((v) => v.id)));
  }

  // ── Filter + sort ─────────────────────────────────────────────────────────
  const filteredSorted = useMemo(() => {
    let list = [...results];
    if (durationFilter === "short") list = list.filter((v) => v.duration > 0 && v.duration < 30);
    else if (durationFilter === "medium") list = list.filter((v) => v.duration >= 30 && v.duration <= 60);
    else if (durationFilter === "long") list = list.filter((v) => v.duration > 60);
    if (viewsFilter === "10k") list = list.filter((v) => v.view_count >= 10_000);
    else if (viewsFilter === "100k") list = list.filter((v) => v.view_count >= 100_000);
    else if (viewsFilter === "1m") list = list.filter((v) => v.view_count >= 1_000_000);
    list.sort((a, b) => {
      if (sortBy === "views") return b.view_count - a.view_count;
      if (sortBy === "engagement") return computeEngagement(b) - computeEngagement(a);
      if (sortBy === "duration") return (b.duration || 0) - (a.duration || 0);
      if (sortBy === "date") return new Date(b.upload_date).getTime() - new Date(a.upload_date).getTime();
      return 0;
    });
    return list;
  }, [results, sortBy, durationFilter, viewsFilter]);
  const currentGroupLabel = activeGroup ?? PRESET_GROUPS[0]?.label ?? null;
  const currentGroup = PRESET_GROUPS.find((g) => g.label === currentGroupLabel) ?? PRESET_GROUPS[0];
  const watchlistValidation = useMemo(() => validateWatchlistEntry(watchlistDraft), [watchlistDraft]);
  const watchlistPreview = watchlistValidation.normalized && watchlistValidation.normalized !== watchlistDraft.trim()
    ? watchlistValidation.normalized
    : "";

  // ── Counters ──────────────────────────────────────────────────────────────
  const queuedFiles = (queueQ.data?.videos as QueuedFile[] | undefined) ?? [];
  const queuedFilenames = useMemo(
    () => new Set(queuedFiles.map((f) => String(f.filename || "").toLowerCase())),
    [queuedFiles],
  );
  const queueCount = queuedFiles.length;
  const today = new Date().toDateString();
  const downloadedToday = queuedFiles.filter((f) => new Date(f.modified * 1000).toDateString() === today).length;

  function isVideoDownloaded(video: VideoResult) {
    const id = String(video.id || "").toLowerCase();
    if (!id) return false;
    for (const name of queuedFilenames) {
      if (name.includes(id)) return true;
    }
    return false;
  }

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="page research-page">
      {toast && (
        <div className="toast-container">
          <div className={`toast-v2 ${toast.kind === "err" ? "error" : "success"}`}>
            <span className="toast-v2-icon">{toast.kind === "err" ? "✕" : "✓"}</span>
            <span className="toast-v2-msg">{toast.msg}</span>
            <button type="button" className="toast-v2-close" onClick={() => setToast(null)}>✕</button>
          </div>
        </div>
      )}

      {/* ── Stats bar ── */}
      <div className="stats-grid-4">
        <div className="stat-card">
          <div className="stat-label">Найдено видео</div>
          <div className="stat-value cyan">{results.length || "—"}</div>
          {results.length > 0 && filteredSorted.length !== results.length && (
            <div style={{ marginTop: 4, fontSize: 11, color: "var(--text-tertiary)" }}>показано {filteredSorted.length}</div>
          )}
        </div>
        <div className="stat-card">
          <div className="stat-label">В очереди</div>
          <div className="stat-value">{queueCount}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Скачано сегодня</div>
          <div className="stat-value green">{downloadedToday}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Регион / Период</div>
          <div style={{ marginTop: 4, fontSize: 13, fontWeight: 700, color: "var(--text-primary)" }}>
            {region} · {period}д
          </div>
        </div>
      </div>

      {/* ── Search bar ── */}
      <div className="card">
        <div className="card-body" style={{ padding: "12px 16px", display: "flex", flexDirection: "column", gap: 10 }}>
          {/* Row 1: input + search button */}
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input className="form-input"
              placeholder="Ниша / тема — например: korean casino shorts"
              value={niche} onChange={(e) => setNiche(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && niche.trim()) searchMut.mutate(undefined); }}
              style={{ flex: 1 }} />
            {/* Save preset */}
            {niche.trim() && !showSavePreset && (
              <button type="button" className="btn-v3 btn-v3-sm btn-v3-ghost"
                onClick={() => setShowSavePreset(true)}
                title="Сохранить как пресет"
                style={{ flexShrink: 0, padding: "7px 10px" }}>
                <Save {...R14} aria-hidden />
              </button>
            )}
            <button type="button" className="btn-v3 btn-v3-primary"
              disabled={!niche.trim() || searchMut.isPending}
              onClick={() => searchMut.mutate(undefined)}
              style={{ flexShrink: 0, minWidth: 130, fontWeight: 700 }}>
              {searchMut.isPending
                ? <span style={{ display: "flex", alignItems: "center", gap: 7 }}><span className="spinner-sm" />Поиск…</span>
                : "Найти видео"}
            </button>
          </div>

          {/* Save preset inline form */}
          {showSavePreset && (
            <div style={{ display: "flex", gap: 7, alignItems: "center" }}>
              <input className="form-input" placeholder="Название пресета…" value={newPresetName}
                onChange={(e) => setNewPresetName(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") savePreset(); if (e.key === "Escape") setShowSavePreset(false); }}
                style={{ flex: 1 }} autoFocus />
              <button type="button" className="btn-v3 btn-v3-sm btn-v3-primary" onClick={savePreset}
                disabled={!newPresetName.trim()}>Сохранить</button>
              <button type="button" className="btn-v3 btn-v3-sm btn-v3-ghost" onClick={() => setShowSavePreset(false)}>Отмена</button>
            </div>
          )}

          {/* Row 2: source + period + region */}
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            {/* Source — with unavailable indicator */}
            <div style={{ display: "flex", gap: 3, background: "var(--bg-elevated)", borderRadius: 6, padding: 3, position: "relative" }}>
              {SOURCES.map((s) => (
                <div key={s.value} style={{ position: "relative" }} title={!s.available ? "Скоро — прямой парсинг в разработке. Сейчас поиск через YouTube." : ""}>
                  <button type="button" onClick={() => s.available && setSource(s.value)}
                    style={{
                      padding: "5px 12px", borderRadius: 4, border: "none", fontSize: 12, fontWeight: 600,
                      background: source === s.value ? "var(--bg-surface)" : "transparent",
                      color: source === s.value ? "var(--text-primary)" : s.available ? "var(--text-tertiary)" : "var(--text-disabled)",
                      cursor: s.available ? "pointer" : "not-allowed",
                      boxShadow: source === s.value ? "0 1px 3px rgba(0,0,0,0.3)" : "none",
                      transition: "all 0.15s",
                      opacity: s.available ? 1 : 0.5,
                    }}>
                    {s.label}
                    {!s.available && (
                      <span style={{
                        marginLeft: 5, fontSize: 9, padding: "1px 4px", borderRadius: 3,
                        background: "var(--bg-hover)", color: "var(--text-tertiary)",
                        verticalAlign: "middle", fontWeight: 700,
                      }}>soon</span>
                    )}
                  </button>
                </div>
              ))}
            </div>

            <SegControl options={PERIODS} value={period} onChange={setPeriod} />

            {/* Region */}
            <SegControl options={REGIONS} value={region} onChange={setRegion} small />

            {/* Filters toggle */}
            <button type="button" className="btn-v3 btn-v3-sm btn-v3-ghost"
              onClick={() => setShowFilters((v) => !v)}
              style={{ marginLeft: "auto", gap: 5, color: showFilters ? "var(--accent-cyan)" : "var(--text-secondary)" }}>
              <SlidersHorizontal {...uiIconProps(13)} aria-hidden />
              Фильтры
            </button>
          </div>

          {/* Row 3: filters (collapsible) */}
          {showFilters && (
            <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", paddingTop: 6, borderTop: "1px solid var(--border-subtle)" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: 11, color: "var(--text-tertiary)", whiteSpace: "nowrap" }}>Сортировка:</span>
                <SegControl options={SORT_OPTIONS} value={sortBy} onChange={setSortBy} small />
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: 11, color: "var(--text-tertiary)", whiteSpace: "nowrap" }}>Длина:</span>
                <SegControl options={DURATION_FILTERS} value={durationFilter} onChange={setDurationFilter} small />
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: 11, color: "var(--text-tertiary)", whiteSpace: "nowrap" }}>Просмотры:</span>
                <SegControl options={VIEWS_FILTERS} value={viewsFilter} onChange={setViewsFilter} small />
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Preset niche tags ── */}
      <div className="card">
        <div className="card-header" style={{ paddingBottom: 8 }}>
          <span className="card-title" style={{ fontSize: 12 }}>Пресеты ниш</span>
          <span style={{ fontSize: 11, color: "var(--text-tertiary)" }}>Нажмите для вставки в поиск</span>
        </div>
        <div className="card-body" style={{ padding: "0 16px 14px", display: "flex", flexDirection: "column", gap: 10 }}>
          {/* Saved presets group */}
          {savedPresets.length > 0 && (
            <div>
              <div style={{ fontSize: 12, fontWeight: 600, color: "var(--accent-cyan)", marginBottom: 6 }}>⭐ Мои пресеты</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {savedPresets.map((p) => (
                  <div key={p.id} style={{ display: "flex", alignItems: "center", gap: 0 }}>
                    <button type="button"
                      onClick={() => applyPreset(p.niche, p)}
                      style={{
                        padding: "4px 10px", borderRadius: "20px 0 0 20px",
                        border: `1px solid ${niche === p.niche ? "var(--accent-cyan)" : "var(--border-default)"}`,
                        borderRight: "none",
                        background: niche === p.niche ? "rgba(94,234,212,0.1)" : "var(--bg-elevated)",
                        color: niche === p.niche ? "var(--accent-cyan)" : "var(--text-secondary)",
                        fontSize: 11, fontWeight: niche === p.niche ? 600 : 400,
                        cursor: "pointer", transition: "all 0.15s", whiteSpace: "nowrap",
                      }}>
                      {p.name}
                      <span style={{ marginLeft: 5, fontSize: 9, color: "var(--text-tertiary)" }}>{p.region}·{p.period}д</span>
                    </button>
                    <button type="button"
                      onClick={() => deletePreset(p.id)}
                      style={{
                        padding: "4px 7px", borderRadius: "0 20px 20px 0",
                        border: `1px solid ${niche === p.niche ? "var(--accent-cyan)" : "var(--border-default)"}`,
                        borderLeft: "1px solid var(--border-subtle)",
                        background: niche === p.niche ? "rgba(94,234,212,0.1)" : "var(--bg-elevated)",
                        color: "var(--text-tertiary)", fontSize: 10,
                        cursor: "pointer", lineHeight: 1,
                      }}>✕</button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Library presets */}
          <div className="preset-layout">
            <div className="preset-groups">
              {PRESET_GROUPS.map((group) => {
                const selected = currentGroup?.label === group.label;
                return (
                  <button
                    key={group.label}
                    type="button"
                    onClick={() => setActiveGroup(group.label)}
                    className={`preset-group-btn ${selected ? "active" : ""}`}
                    style={{ borderColor: selected ? `${group.color}66` : undefined }}
                  >
                    <span style={{ color: group.color }}>{group.label}</span>
                    <span style={{ fontSize: 10, color: "var(--text-tertiary)" }}>{group.presets.length}</span>
                  </button>
                );
              })}
            </div>

            <div className="preset-tags-panel">
              <div className="preset-tags-header">
                <div>
                  <div style={{ fontSize: 12, fontWeight: 700, color: currentGroup?.color || "var(--text-secondary)" }}>
                    {currentGroup?.label ?? "Пресеты"}
                  </div>
                  <div style={{ fontSize: 10, color: "var(--text-tertiary)", marginTop: 2 }}>
                    {currentGroup?.note}
                  </div>
                </div>
                <button
                  type="button"
                  className="btn-v3 btn-v3-sm btn-v3-ghost"
                  onClick={() => {
                    if (!currentGroup) return;
                    setSource(currentGroup.source);
                    setRegion(currentGroup.region);
                    setPeriod(currentGroup.period);
                    showToast(`Профиль ${currentGroup.region} · ${currentGroup.period}д применён`, "ok");
                  }}
                  style={{ fontSize: 10, padding: "0 10px", height: 26 }}
                >
                  Применить UBT-профиль
                </button>
              </div>

              <div className="preset-meta-row">
                <span className="preset-meta-chip">Источник: {currentGroup?.source ?? "youtube"}</span>
                <span className="preset-meta-chip">ГЕО: {currentGroup?.region ?? "KR"}</span>
                <span className="preset-meta-chip">Окно: {currentGroup?.period ?? 2}д</span>
                <span className="preset-meta-chip">{currentGroup?.presets.length ?? 0} тегов</span>
              </div>

              <div className="preset-tags-grid">
                {(currentGroup?.presets ?? []).map((p) => {
                  const selected = niche === p.value;
                  return (
                    <div key={p.value} className={`preset-tag-card ${selected ? "active" : ""}`} style={{ borderColor: selected ? (currentGroup?.color || "var(--accent-cyan)") : undefined }}>
                      <button
                        type="button"
                        onClick={() => applyPreset(p.value, {
                          source: currentGroup?.source,
                          region: currentGroup?.region,
                          period: currentGroup?.period,
                        }, false)}
                        className="preset-tag-main"
                        style={{ color: selected ? (currentGroup?.color || "var(--accent-cyan)") : undefined }}
                        title="Вставить в поиск"
                      >
                        {p.label}
                      </button>
                      <button
                        type="button"
                        onClick={() => applyPreset(p.value, {
                          source: currentGroup?.source,
                          region: currentGroup?.region,
                          period: currentGroup?.period,
                        }, true)}
                        className="preset-tag-run"
                        title="Вставить и сразу найти"
                      >
                        Поиск
                      </button>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ── Arbitrage scan ── */}
      <div className="card arb-scan-card">
        <div className="card-header arb-scan-card-header">
          <div className="arb-scan-header-top">
            <span className="card-title arb-scan-title">
              <span className="arb-scan-title-icon" aria-hidden>⚡</span>
              Арбитраж скан
              <span className="arb-scan-beta">BETA</span>
            </span>
            <span className="arb-scan-legend">
              Tower · Mine · Aviator · Ice Fishing
            </span>
          </div>
          <p className="arb-scan-desc">
            Поиск по YouTube Shorts (до 60 с) по всему миру, без привязки к ГЕО — запросы под типичные заливы арбитража
            (big win, x100, crash, strategy, #shorts). Выберите окно публикации и нажмите скан.
          </p>
        </div>
        <div className="card-body arb-scan-body">
          <div className="arb-scan-filters">
            <div className="arb-filter-block">
              <span className="arb-filter-label">Период публикации</span>
              <SegControl options={PERIODS} value={arbScanPeriod} onChange={setArbScanPeriod} />
            </div>
            <div className="arb-scan-actions">
              <button
                type="button"
                className="btn-v3 btn-v3-ghost arb-scan-settings-btn"
                onClick={() => setArbShowMonitorSettings((v) => !v)}
                title="Настройки мониторинга"
              >
                <BellRing {...R14} aria-hidden />
                Мониторинг
              </button>
              <button
                type="button"
                className={`btn-v3 arb-scan-btn ${arbScanMut.isPending ? "" : "btn-v3-primary"}`}
                disabled={arbScanMut.isPending}
                onClick={() => arbScanMut.mutate(undefined)}
              >
                {arbScanMut.isPending
                  ? <><span className="spinner-sm" />Сканирую…</>
                  : <>
                      <Search {...R14} strokeWidth={2.1} aria-hidden />
                      Сканировать игры
                    </>
                }
              </button>
            </div>
          </div>

          {arbShowMonitorSettings && (
            <div className="arb-monitor-card">
              <div className="arb-monitor-head">
                <div>
                  <div className="arb-monitor-title">Мониторинг коллег</div>
                  <div className="arb-monitor-sub">Watchlist каналов + Telegram-алерты по сильным роликам</div>
                </div>
                <button
                  type="button"
                  className="btn-v3 btn-v3-sm btn-v3-primary"
                  onClick={() => saveArbMonitorMut.mutate(arbMonitorSettings)}
                  disabled={saveArbMonitorMut.isPending}
                >
                  <Save {...R12} aria-hidden />
                  Сохранить
                </button>
              </div>

              <div className="arb-monitor-grid">
                <label className="arb-monitor-toggle">
                  <span>Telegram-алерты</span>
                  <button
                    type="button"
                    className={`toggle-switch ${arbMonitorSettings.alerts_enabled ? "on" : ""}`}
                    onClick={() => setArbMonitorSettings((p) => ({ ...p, alerts_enabled: !p.alerts_enabled }))}
                    aria-label="Переключить Telegram-алерты"
                  />
                </label>

                <label className="arb-monitor-field">
                  <span>Порог Score</span>
                  <input
                    className="form-input mono"
                    type="number"
                    min={1}
                    max={100}
                    value={arbMonitorSettings.score_threshold}
                    onChange={(e) => setArbMonitorSettings((p) => ({ ...p, score_threshold: Math.max(1, Math.min(Number(e.target.value || 1), 100)) }))}
                  />
                </label>

                <label className="arb-monitor-field">
                  <span>Лимит алертов</span>
                  <input
                    className="form-input mono"
                    type="number"
                    min={1}
                    max={10}
                    value={arbMonitorSettings.alert_max_items}
                    onChange={(e) => setArbMonitorSettings((p) => ({ ...p, alert_max_items: Math.max(1, Math.min(Number(e.target.value || 1), 10)) }))}
                  />
                </label>
              </div>

              <div className="arb-watchlist-block">
                <div className="arb-watchlist-title">
                  <Users {...R14} aria-hidden />
                  Watchlist каналов
                </div>
                <div className="arb-watchlist-row">
                  <input
                    className="form-input mono"
                    placeholder="channel_id или https://youtube.com/channel/..."
                    value={watchlistDraft}
                    onChange={(e) => {
                      setWatchlistDraft(e.target.value);
                      if (!watchlistTouched) setWatchlistTouched(true);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        addWatchlistChannel();
                      }
                    }}
                  />
                  <button
                    type="button"
                    className="btn-v3 btn-v3-sm btn-v3-ghost"
                    onClick={addWatchlistChannel}
                    disabled={Boolean(watchlistDraft.trim()) && !watchlistValidation.ok}
                  >
                    Добавить
                  </button>
                </div>
                <div className="arb-watchlist-hint-row">
                  {watchlistPreview ? (
                    <span className="arb-watchlist-hint-ok">Нормализация: <code>{watchlistPreview}</code></span>
                  ) : (
                    <span className="arb-watchlist-hint-neutral">
                      Поддерживаются: <code>UC...</code>, <code>@handle</code>, <code>youtube.com/channel/...</code>, <code>youtube.com/@...</code>
                    </span>
                  )}
                  {watchlistTouched && watchlistDraft.trim() && !watchlistValidation.ok && (
                    <span className="arb-watchlist-hint-err">{watchlistValidation.reason}</span>
                  )}
                </div>
                <div className="arb-watchlist-chips">
                  {arbMonitorSettings.watchlist_channels.length === 0 ? (
                    <span className="arb-watchlist-empty">Пока пусто — добавьте каналы коллег для точного мониторинга.</span>
                  ) : (
                    arbMonitorSettings.watchlist_channels.map((channel) => (
                      <button
                        key={channel}
                        type="button"
                        className="arb-watchlist-chip"
                        onClick={() => removeWatchlistChannel(channel)}
                        title="Удалить из watchlist"
                      >
                        {channel}
                        <span aria-hidden>✕</span>
                      </button>
                    ))
                  )}
                </div>
              </div>
            </div>
          )}

          {!arbScanResults ? (
            <div className="arb-scan-placeholder">
              <div className="arb-scan-placeholder-icon" aria-hidden>◇</div>
              <div className="arb-scan-placeholder-title">Ещё не сканировали</div>
              <p className="arb-scan-placeholder-text">
                Нажмите «Сканировать игры» — вкладки по четырём играм и списки Shorts за выбранный период (поиск глобальный).
              </p>
            </div>
          ) : (
            <>
              <div className="arb-game-tabs" role="tablist" aria-label="Игры арбитража">
                {ARB_GAMES.map(({ key, label, color }) => {
                  const videos = arbScanResults[key] ?? [];
                  const active = arbPanelGameKey === key;
                  const top = videos[0]?.view_count ?? 0;
                  return (
                    <button
                      key={key}
                      type="button"
                      role="tab"
                      aria-selected={active}
                      className={`arb-game-tab ${active ? "arb-game-tab-active" : ""}`}
                      style={{
                        ["--arb-tab" as string]: color,
                        borderColor: active ? `${color}66` : undefined,
                        background: active ? `${color}14` : undefined,
                      }}
                      onClick={() => setArbExpandedGame(key)}
                    >
                      <span className="arb-game-tab-dot" style={{ background: color }} />
                      <span className="arb-game-tab-name">{label}</span>
                      <span className="arb-game-tab-meta">
                        {videos.length}
                        {top > 0 ? <> · {formatNum(top)}</> : null}
                      </span>
                    </button>
                  );
                })}
              </div>

              {arbPanelGameKey && (() => {
                const meta = ARB_GAMES.find((g) => g.key === arbPanelGameKey);
                const color = meta?.color ?? "var(--accent-cyan)";
                const videos = arbScanResults[arbPanelGameKey] ?? [];
                return (
                  <div
                    className="arb-game-panel"
                    role="tabpanel"
                    style={{ borderColor: `${color}40` }}
                  >
                    {videos.length === 0 ? (
                      <div className="arb-panel-empty">
                        Нет Shorts по этой игре за период — попробуйте окно 30д или обновите yt-dlp; если Shorts не найдены, сервер может показать топ по просмотрам без фильтра длительности (см. лог).
                      </div>
                    ) : (
                      <div className="arb-video-list">
                        <div className="arb-video-list-head">
                          <span>Видео</span>
                          <span>Метрики</span>
                          <span>Действия</span>
                        </div>
                        {videos.map((video) => {
                          const er = computeEngagement(video);
                          const dlBusy = downloadMut.isPending && downloadMut.variables?.id === video.id;
                          return (
                            <article key={video.id} className="arb-video-row">
                              <a
                                href={video.url}
                                target="_blank"
                                rel="noreferrer"
                                className="arb-video-thumb-wrap"
                                title="Открыть в YouTube"
                              >
                                {video.thumbnail ? (
                                  <img src={video.thumbnail} alt="" className="arb-video-thumb" />
                                ) : (
                                  <div className="arb-video-thumb arb-video-thumb-fallback" />
                                )}
                                {video.duration > 0 && (
                                  <span className="arb-video-dur">{formatDuration(video.duration)}</span>
                                )}
                              </a>
                              <div className="arb-video-main">
                                <a href={video.url} target="_blank" rel="noreferrer" className="arb-video-title">
                                  {video.title || "—"}
                                </a>
                                <div className="arb-meta-chips">
                                  <span className="arb-meta-chip arb-meta-chip-strong">{formatNum(video.view_count)} просм.</span>
                                  {(video.arb_score ?? 0) > 0 && (
                                    <span className={`arb-meta-chip arb-er-chip ${(video.arb_score ?? 0) >= 75 ? "arb-er-high" : (video.arb_score ?? 0) >= 55 ? "arb-er-mid" : ""}`}>
                                      Score {video.arb_score}
                                    </span>
                                  )}
                                  {video.watchlist_hit && (
                                    <span className="arb-meta-chip arb-er-chip arb-er-high">Watchlist</span>
                                  )}
                                  {(video.like_count ?? 0) > 0 && (
                                    <span className="arb-meta-chip">{formatNum(video.like_count ?? 0)} лайков</span>
                                  )}
                                  {(video.comment_count ?? 0) > 0 && (
                                    <span className="arb-meta-chip">{formatNum(video.comment_count ?? 0)} коммент.</span>
                                  )}
                                  {er > 0 && (
                                    <span className={`arb-meta-chip arb-er-chip ${er >= 5 ? "arb-er-high" : er >= 2 ? "arb-er-mid" : ""}`}>
                                      ER {er.toFixed(1)}%
                                    </span>
                                  )}
                                </div>
                                <div className="arb-channel-line">
                                  {video.channel_url ? (
                                    <a href={video.channel_url} target="_blank" rel="noreferrer" className="arb-channel-link">
                                      {video.channel || "Канал"}
                                    </a>
                                  ) : (
                                    <span className="arb-channel-muted">{video.channel || "—"}</span>
                                  )}
                                  {video.upload_date ? <span className="arb-channel-muted"> · {timeAgo(video.upload_date)}</span> : null}
                                </div>
                              </div>
                              <div className="arb-video-actions">
                                <button
                                  type="button"
                                  className="arb-icon-btn"
                                  title="Вставить заголовок в поле поиска"
                                  aria-label="В поиск"
                                  onClick={() => applyPreset(video.title, { source: "youtube", region, period: arbScanPeriod }, false)}
                                >
                                  <Search {...uiIconProps(16)} aria-hidden />
                                  <span className="arb-icon-btn-label">В поиск</span>
                                </button>
                                <button
                                  type="button"
                                  className="arb-icon-btn arb-icon-btn-accent"
                                  title="Скачать в браузер"
                                  aria-label="Скачать"
                                  onClick={() => downloadMut.mutate(video)}
                                  disabled={dlBusy}
                                >
                                  {dlBusy ? <span className="spinner-sm" /> : (
                                    <Download {...uiIconProps(16)} aria-hidden />
                                  )}
                                  <span className="arb-icon-btn-label">Скачать</span>
                                </button>
                              </div>
                            </article>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })()}
            </>
          )}
        </div>
      </div>

      {/* ── Results header with batch controls ── */}
      {filteredSorted.length > 0 && (
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <label style={{ display: "flex", alignItems: "center", gap: 7, cursor: "pointer", fontSize: 12, color: "var(--text-secondary)" }}>
            <input type="checkbox"
              checked={selected.size === filteredSorted.length && filteredSorted.length > 0}
              onChange={selectAll}
              style={{ accentColor: "var(--accent-cyan)", width: 14, height: 14, cursor: "pointer" }} />
            {selected.size > 0 ? `Выбрано ${selected.size}` : "Выбрать все"}
          </label>
          {selected.size > 0 && (
            <button type="button" className="btn-v3 btn-v3-sm btn-v3-primary"
              onClick={batchDownload} disabled={batchLoading}
              style={{ fontSize: 11, gap: 6 }}>
              {batchLoading ? <><span className="spinner-sm" />Загрузка…</> : `↓ Скачать выбранные (${selected.size})`}
            </button>
          )}
          <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--text-tertiary)" }}>
            {filteredSorted.length} из {results.length} видео
          </span>
        </div>
      )}

      {/* ── Results grid ── */}
      {results.length === 0 ? (
        <div className="card" style={{ padding: "48px 24px", textAlign: "center", color: "var(--text-tertiary)", fontSize: 14 }}>
          {searchMut.isPending
            ? <ResearchSkeletonGrid />
            : <><div style={{ fontSize: 32, marginBottom: 12, opacity: 0.3 }}>◈</div>Выберите пресет или введите нишу</>}
        </div>
      ) : filteredSorted.length === 0 ? (
        <div className="card" style={{ padding: "32px 24px", textAlign: "center", color: "var(--text-tertiary)", fontSize: 13 }}>
          Нет видео по выбранным фильтрам — попробуйте изменить условия
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 16 }}>
          {filteredSorted.map((video, idx) => {
            const hot = hotBadge(video.view_count, idx);
            const gradient = THUMBNAIL_GRADIENTS[idx % THUMBNAIL_GRADIENTS.length];
            const startedAt = downloadStartedAt[video.id] || 0;
            const isDownloaded = downloadedIds.has(video.id) || isVideoDownloaded(video);
            const hasDownloadError = Boolean(downloadErrors[video.id]);
            const isQueued = startedAt > 0 && !isDownloaded && Date.now() - startedAt < 3500;
            const isDownloading = startedAt > 0 && !isDownloaded && !isQueued && !hasDownloadError;
            const advice = adviceById[video.id];
            const adviceOpen = adviceOpenId === video.id;
            const isGettingAdvice = adviceMut.isPending && adviceMut.variables?.id === video.id;
            const isSelected = selected.has(video.id);
            const er = computeEngagement(video);

            return (
              <div key={video.id}
                style={{
                  background: "var(--bg-surface)",
                  border: `1px solid ${isSelected ? "var(--accent-cyan)" : advice ? "rgba(94,234,212,0.2)" : "var(--border-subtle)"}`,
                  borderRadius: 12, overflow: "hidden", transition: "all 0.18s",
                  display: "flex", flexDirection: "column",
                  boxShadow: isSelected ? "0 0 0 2px rgba(94,234,212,0.15)" : "none",
                }}
                onMouseEnter={(e) => {
                  (e.currentTarget as HTMLDivElement).style.transform = "translateY(-2px)";
                  (e.currentTarget as HTMLDivElement).style.boxShadow = isSelected
                    ? "0 0 0 2px rgba(94,234,212,0.2), 0 8px 24px rgba(0,0,0,0.35)"
                    : "0 8px 24px rgba(0,0,0,0.35)";
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLDivElement).style.transform = "";
                  (e.currentTarget as HTMLDivElement).style.boxShadow = isSelected ? "0 0 0 2px rgba(94,234,212,0.15)" : "none";
                }}
              >
                {/* Thumbnail */}
                <div
                  style={{ position: "relative", aspectRatio: "9/16", maxHeight: 420, overflow: "hidden", background: gradient, flexShrink: 0, cursor: "pointer" }}
                  onClick={() => window.open(video.url, "_blank", "noopener,noreferrer")}
                  title="Открыть источник"
                >
                  {video.thumbnail && (
                    <img src={video.thumbnail} alt=""
                      style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
                      onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }} />
                  )}
                  {/* Select checkbox */}
                  <div style={{ position: "absolute", top: 9, left: 9, zIndex: 2 }}
                    onClick={(e) => { e.stopPropagation(); toggleSelect(video.id); }}>
                    <div style={{
                      width: 20, height: 20, borderRadius: 5,
                      background: isSelected ? "var(--accent-cyan)" : "rgba(0,0,0,0.55)",
                      border: `2px solid ${isSelected ? "var(--accent-cyan)" : "rgba(255,255,255,0.5)"}`,
                      display: "flex", alignItems: "center", justifyContent: "center",
                      cursor: "pointer", transition: "all 0.15s", backdropFilter: "blur(4px)",
                    }}>
                      {isSelected && <Check size={11} strokeWidth={3.25} color="#0a0a0b" aria-hidden />}
                    </div>
                  </div>
                  {hot && (
                    <div style={{
                      position: "absolute", top: 9, left: 38,
                      background: hot.bg, color: "#fff",
                      fontSize: 9, fontWeight: 800, letterSpacing: "0.6px",
                      padding: "2px 7px", borderRadius: 4, fontFamily: "var(--font-mono)",
                    }}>{hot.label}</div>
                  )}
                  <div style={sourceBadgeStyle(video.source)}>{sourceLabel(video.source)}</div>
                  {video.duration > 0 && (
                    <div style={{
                      position: "absolute", bottom: 8, right: 8,
                      background: "rgba(0,0,0,0.78)", color: "#fff",
                      fontSize: 11, fontWeight: 600, padding: "2px 6px",
                      borderRadius: 4, fontFamily: "var(--font-mono)",
                    }}>{formatDuration(video.duration)}</div>
                  )}
                </div>

                {/* Info */}
                <div style={{ padding: "10px 12px 12px", display: "flex", flexDirection: "column", gap: 5, flex: 1 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: "var(--text-tertiary)" }}>
                    {video.channel_url ? (
                      <a
                        href={video.channel_url}
                        target="_blank"
                        rel="noreferrer"
                        title="Открыть канал"
                        style={{ fontWeight: 500, color: "var(--accent-cyan)", maxWidth: 110, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", textDecoration: "none" }}
                      >
                        {video.channel || "Channel"}
                      </a>
                    ) : (
                      <span style={{ fontWeight: 500, color: "var(--text-secondary)", maxWidth: 110, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {video.channel || "Channel"}
                      </span>
                    )}
                    {video.upload_date && <span>· {timeAgo(video.upload_date)}</span>}
                    {video.region && <span style={{ marginLeft: "auto", opacity: 0.7 }}>{video.region}</span>}
                  </div>
                  <a
                    href={video.url}
                    target="_blank"
                    rel="noreferrer"
                    style={{ fontSize: 10, color: "var(--accent-cyan)", textDecoration: "none", width: "fit-content" }}
                  >
                    Источник ↗
                  </a>
                  <a href={video.url} target="_blank" rel="noreferrer"
                    style={{
                      fontSize: 13, fontWeight: 500, color: "var(--text-primary)",
                      textDecoration: "none", lineHeight: 1.4,
                      display: "-webkit-box", WebkitLineClamp: 2,
                      WebkitBoxOrient: "vertical", overflow: "hidden",
                    }}>
                    {video.title || "Без названия"}
                  </a>

                  {/* Metrics */}
                  <div style={{ display: "flex", gap: 10, fontSize: 12, color: "var(--text-tertiary)", marginTop: 2, flexWrap: "wrap" }}>
                    <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
                      <Eye {...R12} aria-hidden />
                      <span style={{ color: "var(--text-primary)", fontWeight: 600 }}>{formatNum(video.view_count)}</span>
                    </span>
                    {(video.like_count ?? 0) > 0 && (
                      <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
                        <Heart {...R12} aria-hidden />
                        {formatNum(video.like_count ?? 0)}
                      </span>
                    )}
                    {(video.comment_count ?? 0) > 0 && (
                      <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
                        <MessageCircle {...R12} aria-hidden />
                        {formatNum(video.comment_count ?? 0)}
                      </span>
                    )}
                    {er > 0 && (
                      <span style={{ color: er >= 5 ? "var(--accent-green)" : er >= 2 ? "var(--accent-amber)" : "var(--text-tertiary)", fontWeight: 600 }}>
                        ER {er.toFixed(1)}%
                      </span>
                    )}
                  </div>

                  {/* Buttons */}
                  <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
                    <button
                      type="button"
                      className={`btn-v3 btn-v3-sm ${
                        hasDownloadError
                          ? "btn-v3-danger"
                          : isDownloaded
                            ? "btn-v3-success"
                            : isQueued || isDownloading
                              ? "btn-v3-primary"
                              : "btn-v3-ghost"
                      }`}
                      disabled={isQueued || isDownloading}
                      onClick={() => downloadMut.mutate(video)}
                      style={{ flex: 1, fontSize: 11, justifyContent: "center" }}>
                      {hasDownloadError
                        ? "⚠ Повторить"
                        : isDownloaded
                          ? "✓ Скачано"
                          : isQueued
                            ? "⏳ В очереди"
                            : isDownloading
                              ? "⬇ Загрузка..."
                              : "↓ Скачать видео"}
                    </button>
                    <button type="button" className="btn-v3 btn-v3-sm btn-v3-primary"
                      disabled={isGettingAdvice}
                      onClick={() => {
                        if (advice && adviceOpen) setAdviceOpenId(null);
                        else if (advice) setAdviceOpenId(video.id);
                        else adviceMut.mutate(video);
                      }}
                      style={{ flex: 1, fontSize: 11, justifyContent: "center" }}>
                      {isGettingAdvice
                        ? <><span className="spinner-sm" />AI…</>
                        : advice ? (adviceOpen ? "Скрыть" : `Score ${advice.score}`) : "AI анализ"}
                    </button>
                  </div>

                  {hasDownloadError && (
                    <div style={{ marginTop: 6, fontSize: 10, color: "var(--accent-red)" }}>
                      Ошибка скачивания: {downloadErrors[video.id]}
                    </div>
                  )}

                  {/* AI advice panel */}
                  {advice && adviceOpen && <AdvicePanel advice={advice} />}
                </div>
              </div>
            );
          })}
        </div>
      )}

      <style>{`
        .spinner-sm {
          display: inline-block; width: 11px; height: 11px;
          border: 2px solid rgba(255,255,255,0.25); border-top-color: #fff;
          border-radius: 50%; animation: spin 0.7s linear infinite; flex-shrink: 0;
        }
        .preset-layout {
          display: grid;
          grid-template-columns: minmax(170px, 220px) 1fr;
          gap: 10px;
          align-items: start;
        }
        .preset-groups {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        .preset-group-btn {
          display: flex;
          align-items: center;
          justify-content: space-between;
          width: 100%;
          padding: 6px 9px;
          border-radius: 8px;
          border: 1px solid var(--border-subtle);
          background: var(--bg-elevated);
          cursor: pointer;
          transition: all .15s ease;
          font-size: 12px;
          font-weight: 600;
        }
        .preset-group-btn:hover,
        .preset-group-btn.active {
          background: rgba(255,255,255,0.03);
          transform: translateY(-1px);
        }
        .preset-tags-panel {
          border: 1px solid var(--border-subtle);
          border-radius: 10px;
          background: var(--bg-elevated);
          padding: 11px;
          min-height: 132px;
        }
        .preset-tags-header {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 10px;
          margin-bottom: 10px;
        }
        .preset-meta-row {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
          margin-bottom: 10px;
        }
        .preset-meta-chip {
          font-size: 10px;
          color: var(--text-tertiary);
          border: 1px solid var(--border-subtle);
          background: rgba(255,255,255,0.02);
          border-radius: 999px;
          padding: 2px 8px;
          white-space: nowrap;
        }
        .preset-tags-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
          gap: 8px;
        }
        .preset-tag-card {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 4px;
          border: 1px solid var(--border-subtle);
          border-radius: 10px;
          background: rgba(255,255,255,0.01);
          transition: all .15s ease;
        }
        .preset-tag-card:hover {
          border-color: rgba(94,234,212,0.35);
          transform: translateY(-1px);
        }
        .preset-tag-card.active {
          background: rgba(94,234,212,0.08);
          box-shadow: 0 0 0 1px rgba(94,234,212,0.2) inset;
        }
        .preset-tag-main {
          flex: 1;
          min-width: 0;
          background: transparent;
          border: none;
          color: var(--text-secondary);
          cursor: pointer;
          text-align: left;
          font-size: 11px;
          font-weight: 600;
          padding: 4px 6px;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .preset-tag-run {
          border: 1px solid var(--border-subtle);
          border-radius: 8px;
          background: var(--bg-elevated);
          color: var(--text-tertiary);
          cursor: pointer;
          font-size: 10px;
          font-weight: 600;
          padding: 4px 8px;
          line-height: 1;
        }
        .preset-tag-run:hover {
          color: var(--text-primary);
          border-color: rgba(94,234,212,0.4);
        }
        @media (max-width: 1024px) {
          .preset-layout { grid-template-columns: 1fr; }
          .preset-groups { flex-direction: row; flex-wrap: wrap; }
          .preset-group-btn { width: auto; min-width: 140px; }
          .preset-tags-grid { grid-template-columns: 1fr; }
        }
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}

// ── Advice Panel ──────────────────────────────────────────────────────────────
function AdvicePanel({ advice }: { advice: AdviceResult }) {
  const riskColor = RISK_COLOR[advice.risk] ?? "var(--accent-cyan)";
  const bd = advice.breakdown ?? {};

  const breakdownRows = [
    { key: "views",      label: "Просмотры",    maxPts: 30, color: "var(--accent-blue)" },
    { key: "engagement", label: "Engagement",   maxPts: 20, color: "var(--accent-cyan)" },
    { key: "duration",   label: "Длительность", maxPts: 15, color: "var(--accent-purple)" },
    { key: "keywords",   label: "Тематика",     maxPts: 10, color: "var(--accent-amber)" },
    { key: "source",     label: "Платформа",    maxPts: 5,  color: "var(--accent-green)" },
  ];

  return (
    <div style={{
      marginTop: 8, padding: "11px 12px",
      background: "rgba(94,234,212,0.05)",
      border: "1px solid rgba(94,234,212,0.18)",
      borderRadius: 10, fontSize: 12,
      display: "flex", flexDirection: "column", gap: 10,
    }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <ScoreRing score={advice.score} risk={advice.risk} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 4 }}>
            <span style={{
              padding: "2px 9px", borderRadius: 4, fontSize: 11, fontWeight: 700,
              background: `${riskColor}20`, color: riskColor, border: `1px solid ${riskColor}40`,
            }}>{advice.preset}</span>
            <span style={{ padding: "2px 9px", borderRadius: 4, fontSize: 11, fontWeight: 600,
              background: "var(--bg-elevated)", color: "var(--text-secondary)" }}>
              {RISK_LABEL[advice.risk]}
            </span>
          </div>
          {(advice.engagement_rate ?? 0) > 0 && (
            <div style={{ fontSize: 11, color: "var(--text-tertiary)" }}>
              ER: <span style={{ color: "var(--accent-cyan)", fontWeight: 600 }}>{advice.engagement_rate!.toFixed(1)}%</span>
              {(advice.viral_coeff ?? 0) > 0 && (
                <> · Viral: <span style={{ color: "var(--accent-amber)", fontWeight: 600 }}>{advice.viral_coeff!.toFixed(0)}</span></>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Score breakdown */}
      <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text-tertiary)", letterSpacing: "0.5px", textTransform: "uppercase", marginBottom: 2 }}>
          Разбивка оценки
        </div>
        {breakdownRows.map((row) => {
          const item = bd[row.key];
          if (!item) return null;
          return (
            <div key={row.key} style={{ display: "flex", alignItems: "center", gap: 7 }}>
              <span style={{ width: 80, fontSize: 10, color: "var(--text-tertiary)", flexShrink: 0 }}>{row.label}</span>
              <MiniBar pts={item.pts} maxPts={row.maxPts} color={row.color} />
              <span style={{ width: 28, textAlign: "right", fontSize: 10, fontWeight: 700,
                fontFamily: "var(--font-mono)", color: item.pts >= 0 ? row.color : "var(--accent-red)" }}>
                {item.pts >= 0 ? "+" : ""}{item.pts}
              </span>
            </div>
          );
        })}
      </div>

      {/* Reasons */}
      {advice.reasons.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text-tertiary)", letterSpacing: "0.5px", textTransform: "uppercase", marginBottom: 1 }}>
            Выводы
          </div>
          {advice.reasons.map((r, i) => (
            <div key={i} style={{ display: "flex", gap: 6, fontSize: 11, color: "var(--text-secondary)", lineHeight: 1.4 }}>
              <span style={{ color: riskColor, flexShrink: 0 }}>›</span><span>{r}</span>
            </div>
          ))}
        </div>
      )}

      {/* AI title */}
      {advice.ai_title && (
        <div style={{ padding: "7px 9px", background: "var(--bg-elevated)", borderRadius: 7 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text-tertiary)", letterSpacing: "0.5px", textTransform: "uppercase", marginBottom: 4 }}>
            AI заголовок
          </div>
          <div style={{ fontSize: 12, color: "var(--text-primary)", lineHeight: 1.45 }}>{advice.ai_title}</div>
        </div>
      )}

      {/* Overlay text */}
      {advice.overlay_text && (
        <div style={{ padding: "5px 9px", background: "rgba(167,139,250,0.07)", border: "1px solid rgba(167,139,250,0.2)", borderRadius: 7 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: "var(--accent-purple)", letterSpacing: "0.5px", textTransform: "uppercase", marginBottom: 3 }}>
            Overlay текст
          </div>
          <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>{advice.overlay_text}</div>
        </div>
      )}

      {/* Action plan */}
      <div>
        <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text-tertiary)", letterSpacing: "0.5px", textTransform: "uppercase", marginBottom: 5 }}>
          План действий
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {advice.action_plan.map((a, i) => (
            <div key={i} style={{ display: "flex", gap: 7, fontSize: 11, color: "var(--text-secondary)", lineHeight: 1.4 }}>
              <span style={{ width: 17, height: 17, borderRadius: "50%",
                background: `${riskColor}20`, color: riskColor,
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 9, fontWeight: 800, flexShrink: 0 }}>{i + 1}</span>
              <span>{a}</span>
            </div>
          ))}
        </div>
      </div>

      {advice.ai_description && (
        <div style={{ fontSize: 11, color: "var(--text-tertiary)", lineHeight: 1.5, paddingTop: 4, borderTop: "1px solid var(--border-subtle)" }}>
          <span style={{ color: "var(--text-secondary)", fontWeight: 600 }}>AI описание: </span>
          {advice.ai_description}
        </div>
      )}

      {advice.used_fallback && (
        <div style={{ fontSize: 10, color: "var(--text-tertiary)", fontStyle: "italic" }}>
          * AI без ключа — шаблонная генерация
        </div>
      )}
    </div>
  );
}
