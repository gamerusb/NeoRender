import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { flushSync } from "react-dom";
import {
  Clapperboard,
  ChevronDown,
  CloudUpload,
  Download,
  Film,
  GripVertical,
  Layers,
  Palette,
  PanelsTopLeft,
  Play,
  Rocket,
  Save,
  Sparkles,
  WandSparkles,
  Zap,
} from "lucide-react";
import { apiFetch, apiUrl, downloadTaskMp4, type ApiJson } from "@/api";
import { useTenant } from "@/tenant/TenantContext";

type UqSettings = {
  preset?: string;
  template?: string;
  overlay_blend_mode?: string;
  overlay_opacity?: number;
  subtitle?: string;
  subtitle_srt_path?: string;
  overlay_media_path?: string;
  available_presets?: unknown;
  available_templates?: unknown;
  available_overlay_blends?: unknown;
  available_geo_profiles?: Record<string, { lat: number; lng: number; label?: string }>;
  /** Значение модели в метаданных → подпись (пресеты «отпечатка»). */
  available_device_models?: unknown;
  geo_enabled?: boolean;
  geo_profile?: string;
  geo_jitter?: number;
  device_model?: string;
  niche?: string;
  overlay_mode?: string;
  overlay_position?: string;
  subtitle_style?: string;
  /** Имя шрифта как в системе сервера (libass). Пусто = случайный из пула. */
  subtitle_font?: string;
  /** 0 = авто (размер из шаблона). */
  subtitle_font_size?: number;
  effects?: Record<string, boolean>;
  effect_levels?: Record<string, string>;
  available_effects?: Record<string, string>;
  available_effect_levels?: Record<string, string>;
  uniqualize_intensity?: string;
  available_uniqualize_intensity?: Record<string, { label?: string; desc?: string }>;
  tags?: string[];
  thumbnail_path?: string;
};

type OptionItem = { value: string; label: string };

function normalizeOptions(input: unknown): OptionItem[] {
  if (Array.isArray(input)) {
    return input.map((v) => {
      const s = String(v ?? "");
      return { value: s, label: s };
    });
  }
  if (input && typeof input === "object") {
    const out: OptionItem[] = [];
    for (const [key, val] of Object.entries(input as Record<string, unknown>)) {
      if (val && typeof val === "object") {
        const rec = val as Record<string, unknown>;
        out.push({ value: key, label: String(rec.label ?? key) });
      } else {
        out.push({ value: key, label: String(val ?? key) });
      }
    }
    return out;
  }
  return [];
}

function labelFor(options: OptionItem[], value: string | undefined): string {
  if (!value) return "-";
  const hit = options.find((o) => o.value === value);
  return hit?.label ?? value;
}

function snippetFromAiMeta(d: ApiJson | undefined): string {
  if (!d) return "";
  const o = String(d.overlay_text ?? "").trim();
  const t = String(d.title ?? "").trim();
  return (o || t).slice(0, 500);
}

function taskIdFromPayload(d: ApiJson | undefined): number {
  if (!d) return 0;
  const v = d.id;
  if (typeof v === "number" && Number.isFinite(v) && v > 0) return v;
  if (typeof v === "string") {
    const n = parseInt(v.trim(), 10);
    if (n > 0) return n;
  }
  return 0;
}

function toggleEffect(current: Record<string, boolean> | undefined, key: string): Record<string, boolean> {
  const now = { ...(current || {}) };
  now[key] = !Boolean(now[key]);
  return now;
}

function setEffectLevel(
  current: Record<string, string> | undefined,
  key: string,
  value: string,
): Record<string, string> {
  const next = { ...(current || {}) };
  next[key] = value;
  return next;
}

const OVERLAY_MODE_OPTS: OptionItem[] = [
  { value: "on_top", label: "Поверх основного видео" },
  { value: "under_video", label: "Под роликом (подложка)" },
];

const OVERLAY_POSITION_OPTS: OptionItem[] = [
  { value: "top_left", label: "Верхний левый" },
  { value: "top_right", label: "Верхний правый" },
  { value: "bottom_left", label: "Нижний левый" },
  { value: "bottom_right", label: "Нижний правый" },
  { value: "center", label: "По центру" },
];

/**
 * Топ шрифтов под корейский контент / молодёжь (Shorts, Reels, 카톡-эстетика).
 * value = имя для libass на сервере (как в установленном шрифте); previewFamily — для превью в браузере.
 */
const SUBTITLE_FONT_OPTIONS: { value: string; label: string; previewFamily?: string }[] = [
  { value: "", label: "Авто (случайный из пула движка)" },
  {
    value: "Pretendard",
    label: "Pretendard — самый популярный в KR-приложениях и сайтах",
    previewFamily: '"Pretendard", -apple-system, BlinkMacSystemFont, sans-serif',
  },
  {
    value: "Noto Sans KR",
    label: "Noto Sans KR — нейтральный, для любого корейского текста",
    previewFamily: '"Noto Sans KR", sans-serif',
  },
  {
    value: "Nanum Gothic",
    label: "Nanum Gothic (나눔고딕) — классика веб и баннеров",
    previewFamily: '"Nanum Gothic", "NanumGothic", sans-serif',
  },
  {
    value: "NanumGothic",
    label: "NanumGothic — то же, если в Windows имя без пробела",
    previewFamily: '"Nanum Gothic", "NanumGothic", sans-serif',
  },
  {
    value: "Malgun Gothic",
    label: "Malgun Gothic (맑은 고딕) — стандарт Windows (KR)",
    previewFamily: '"Malgun Gothic", "Malgun Gothic UI", sans-serif',
  },
  {
    value: "Apple SD Gothic Neo",
    label: "Apple SD Gothic Neo — iPhone / macOS",
    previewFamily: '"Apple SD Gothic Neo", "Malgun Gothic", sans-serif',
  },
  {
    value: "Black Han Sans",
    label: "Black Han Sans — жирные заголовки, шортсы, мемы",
    previewFamily: '"Black Han Sans", sans-serif',
  },
  {
    value: "Jua",
    label: "Jua — округлый «милый» стиль (카페, лайфстайл)",
    previewFamily: '"Jua", sans-serif',
  },
  {
    value: "Do Hyeon",
    label: "Do Hyeon — плакатный, заметный CTA",
    previewFamily: '"Do Hyeon", sans-serif',
  },
  {
    value: "Gowun Dodum",
    label: "Gowun Dodum — спокойный гротеск, читаемый",
    previewFamily: '"Gowun Dodum", sans-serif',
  },
  {
    value: "Dongle",
    label: "Dongle — компактный игривый (сторис)",
    previewFamily: '"Dongle", sans-serif',
  },
  {
    value: "Single Day",
    label: "Single Day — лёгкая рукопись, тренды TikTok/Reels",
    previewFamily: '"Single Day", cursive',
  },
  { value: "Montserrat", label: "Montserrat — латиница + микс с KR", previewFamily: '"Montserrat", sans-serif' },
  { value: "Poppins", label: "Poppins — международные нарезки", previewFamily: '"Poppins", sans-serif' },
  { value: "Arial", label: "Arial — запасной универсальный" },
  { value: "Segoe UI", label: "Segoe UI" },
];

function subtitlePreviewFontCss(assFontName: string | undefined): string {
  const v = String(assFontName || "").trim();
  if (!v) return '"Pretendard", "Noto Sans KR", system-ui, sans-serif';
  const hit = SUBTITLE_FONT_OPTIONS.find((o) => o.value === v);
  if (hit?.previewFamily) return hit.previewFamily;
  return `"${v.replace(/"/g, "")}", sans-serif`;
}

/** Пользовательский слой лежит в data/uploads/{tenant}/; иначе — встроенный overlay.png и т.п. */
function pathLooksLikeTenantUpload(p: string): boolean {
  return p.replace(/\\/g, "/").includes("/uploads/");
}

/** Подписи гео как в референсе (City, KR). */
const GEO_CITY_EN_LINE: Record<string, string> = {
  busan: "Busan, KR",
  seoul: "Seoul, KR",
  incheon: "Incheon, KR",
  daegu: "Daegu, KR",
  daejeon: "Daejeon, KR",
  gwangju: "Gwangju, KR",
  suwon: "Suwon, KR",
  jeju: "Jeju, KR",
  ulsan: "Ulsan, KR",
  pohang: "Pohang, KR",
};

function geoKeyToDisplayLine(profile: string): string {
  const raw = (profile || "").trim();
  if (!raw) return "Busan, KR";
  const k = raw.toLowerCase();
  if (GEO_CITY_EN_LINE[k]) return GEO_CITY_EN_LINE[k];
  const num = raw.replace(/\s/g, "");
  const m = num.match(/^([+-]?\d+(?:\.\d+)?)[,;/]([+-]?\d+(?:\.\d+)?)$/);
  if (m) return `${m[1]}, ${m[2]}`;
  return raw;
}

function parseGeoDisplayToProfile(line: string): string {
  const t = line.trim();
  if (!t) return "busan";
  const compact = t.replace(/\s/g, "").toLowerCase();
  for (const [key, en] of Object.entries(GEO_CITY_EN_LINE)) {
    if (en.replace(/\s/g, "").toLowerCase() === compact) return key;
  }
  const num = t.replace(/\s/g, "");
  const m = num.match(/^([+-]?\d+(?:\.\d+)?)[,;/]([+-]?\d+(?:\.\d+)?)$/);
  if (m) {
    const lat = parseFloat(m[1]);
    const lon = parseFloat(m[2]);
    if (lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180) return `${m[1]},${m[2]}`;
  }
  const asKey = t.toLowerCase().replace(/\s+/g, "_").replace(/,/g, "");
  if (GEO_CITY_EN_LINE[asKey]) return asKey;
  return t;
}

function filesWordRu(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return "0 файлов";
  const k = n % 10;
  const kk = n % 100;
  if (kk >= 11 && kk <= 14) return `${n} файлов`;
  if (k === 1) return `${n} файл`;
  if (k >= 2 && k <= 4) return `${n} файла`;
  return `${n} файлов`;
}

const ICON_SZ = 16;
const ICON_STROKE = 1.75;
const LEVEL_CONTROL_EFFECTS = new Set(["crop_reframe", "gamma_jitter", "audio_tone"]);
const DEFAULT_EFFECT_LEVELS: Record<string, string> = { low: "Low", med: "Med", high: "High" };
const EFFECT_LEVEL_HINTS: Record<string, Record<string, string>> = {
  crop_reframe: {
    low: "Минимальный микрокроп и рефрейм, почти без заметной геометрии.",
    med: "Умеренный микрокроп для дополнительной вариативности кадра.",
    high: "Более выраженный микрокроп и рефрейм для сильной перестройки кадра.",
  },
  gamma_jitter: {
    low: "Лёгкие колебания гаммы, почти незаметно визуально.",
    med: "Средняя амплитуда гаммы, заметная, но аккуратная коррекция.",
    high: "Сильнее изменяет гамму между рендерами, максимальная вариативность.",
  },
  audio_tone: {
    low: "Мягкий тональный профиль, минимальное вмешательство в звук.",
    med: "Сбалансированный эквалайзинг и компрессия для стабильного тона.",
    high: "Более агрессивный тональный профиль и компрессия.",
  },
};

const EFFECT_LEVEL_COLORS: Record<string, string> = {
  low: "rgba(34, 197, 94, 0.18)",
  med: "rgba(245, 158, 11, 0.18)",
  high: "rgba(239, 68, 68, 0.2)",
};
const EFFECT_LEVEL_BORDERS: Record<string, string> = {
  low: "rgba(34, 197, 94, 0.55)",
  med: "rgba(245, 158, 11, 0.55)",
  high: "rgba(239, 68, 68, 0.6)",
};

const DEVICE_MODEL_CUSTOM = "__custom__";

/** Если с API не пришёл available_geo_profiles — тот же набор, что в luxury_engine._GEO_PROFILES. */
/** Имя файла после загрузки на сервер (uuid32 + расширение). */
const UPLOAD_VIDEO_BASENAME_RE = /^[a-f0-9]{32}\.(mp4|mov|webm|mkv|avi)$/i;

function storedUploadBasenameFromPath(serverPath: string): string | null {
  const s = serverPath.trim();
  if (!s) return null;
  const seg = s.split(/[/\\]/).pop() ?? "";
  return UPLOAD_VIDEO_BASENAME_RE.test(seg) ? seg : null;
}

export function UniqualizerPage() {
  const { tenantId } = useTenant();
  const qc = useQueryClient();

  const [videoPath, setVideoPath] = useState("");
  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [videoBlobUrl, setVideoBlobUrl] = useState<string | null>(null);
  const [videoDragOver, setVideoDragOver] = useState(false);
  const [targetProfile, setTargetProfile] = useState("");
  const [renderOnly, setRenderOnly] = useState(true);
  const [checkDuplicates, setCheckDuplicates] = useState(true);
  const [variantsCount, setVariantsCount] = useState(10);
  /** По одной строке CTA на каждый variant; пусто = из поля «Текст на видео» / настроек пайплайна. */
  const [variantsSubtitlesText, setVariantsSubtitlesText] = useState("");
  const [rotateTemplates, setRotateTemplates] = useState(false);
  const [randomizeEffects, setRandomizeEffects] = useState(true);
  const [randomizeDeviceGeo, setRandomizeDeviceGeo] = useState(false);
  const [variantsPriority, setVariantsPriority] = useState(0);
  const [subtitleTouched, setSubtitleTouched] = useState(false);
  const [toast, setToast] = useState<{ msg: string; kind: "ok" | "err" } | null>(null);
  const [overlayFile, setOverlayFile] = useState<File | null>(null);
  const [srtFile, setSrtFile] = useState<File | null>(null);
  const [settings, setSettings] = useState<UqSettings>({});

  const [activeStep, setActiveStep] = useState(1);
  /** guide — пошаговая блокировка; free — любой шаг без ограничений (опытные пользователи). */
  const [flowMode, setFlowMode] = useState<"guide" | "free">("guide");
  const [effectsReviewed, setEffectsReviewed] = useState(false);
  /** Шаг «Слои» пройден (Далее) или есть загруженный слой / субтитры / текст. */
  const [layersReviewed, setLayersReviewed] = useState(false);
  const [layerPanelOpen, setLayerPanelOpen] = useState({ overlay: true, text: true, geo: false });
  /** Только для режима «Свои координаты» (не ключ пресета). */
  const [geoCustomDraft, setGeoCustomDraft] = useState("");
  const [aiMeta, setAiMeta] = useState<ApiJson | null>(null);
  /** Задачи, запущенные с этой страницы — ждём success для предложения скачать. */
  const [downloadWatchIds, setDownloadWatchIds] = useState<number[]>([]);
  /** Успешно завершённые, показываем блок с кнопками скачать. */
  const [downloadOfferIds, setDownloadOfferIds] = useState<number[]>([]);
  const [downloadingTaskId, setDownloadingTaskId] = useState<number | null>(null);
  const downloadErrorNotifiedRef = useRef<Set<number>>(new Set());
  /** Уже перенесли в «скачать» — чтобы не терять из‑за повторных вызовов updater / опросов. */
  const downloadPromotedRef = useRef<Set<number>>(new Set());
  const downloadWatchIdsRef = useRef<number[]>([]);
  downloadWatchIdsRef.current = downloadWatchIds;
  const progressVisibleRef = useRef(false);

  const settingsQ = useQuery({
    queryKey: ["uq-settings", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/uniqualizer/settings", { tenantId }),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
  const profilesQ = useQuery({
    queryKey: ["profiles", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/profiles", { tenantId }),
  });
  const progressQ = useQuery({
    queryKey: ["render-progress", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/pipeline/render-progress", { tenantId }),
    refetchInterval: 2000,
  });
  const progressVisibleForPoll = Boolean(progressQ.data?.visible);
  const tasksQ = useQuery({
    queryKey: ["tasks", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/tasks?limit=100", { tenantId }),
    refetchInterval: downloadWatchIds.length > 0 || progressVisibleForPoll ? 2000 : false,
  });

  const runTaskDownload = useCallback(
    async (taskId: number): Promise<void> => {
      setDownloadingTaskId(taskId);
      try {
        await downloadTaskMp4(taskId, tenantId);
      } catch (e) {
        setToast({ msg: e instanceof Error ? e.message : "Не удалось скачать файл", kind: "err" });
      } finally {
        setDownloadingTaskId((x) => (x === taskId ? null : x));
      }
    },
    [tenantId],
  );

  useEffect(() => {
    if (!settingsQ.data) return;
    setSettings((prev) => {
      const d = settingsQ.data as UqSettings;
      const next: UqSettings = subtitleTouched ? { ...d, subtitle: prev.subtitle } : { ...d };
      // Справочники с GET не должны пропадать из стейта при частичных/старых ответах.
      if (
        (!next.available_geo_profiles || Object.keys(next.available_geo_profiles).length === 0) &&
        prev.available_geo_profiles &&
        Object.keys(prev.available_geo_profiles).length > 0
      ) {
        next.available_geo_profiles = prev.available_geo_profiles;
      }
      // Не затирать выбранный шрифт «пустым» ответом (гонка refetch до того, как POST /settings дошёл до API).
      const prevFont = (prev.subtitle_font ?? "").trim();
      const nextFont = (next.subtitle_font ?? "").trim();
      if (prevFont && !nextFont) {
        next.subtitle_font = prevFont;
      }
      return next;
    });
  }, [settingsQ.data, subtitleTouched]);

  /** После закрытия прогресса подтягиваем задачи — иначе success мог прийти в БД между опросами. */
  useEffect(() => {
    const v = Boolean(progressQ.data?.visible);
    if (progressVisibleRef.current && !v) {
      void qc.invalidateQueries({ queryKey: ["tasks", tenantId] });
    }
    progressVisibleRef.current = v;
  }, [progressQ.data?.visible, qc, tenantId]);

  useEffect(() => {
    const raw = tasksQ.data?.tasks;
    if (!Array.isArray(raw)) return;

    const tasks = raw as ApiJson[];
    const watch = downloadWatchIdsRef.current;
    if (!watch.length) return;

    const still: number[] = [];
    const ready: number[] = [];
    const errs: number[] = [];
    for (const id of watch) {
      const t = tasks.find((x) => Number(x.id) === id);
      if (!t) {
        still.push(id);
        continue;
      }
      const st = String(t.status || "");
      const uv = t.unique_video;
      if (st === "success" && (typeof uv === "string" ? uv.trim() : String(uv || "").trim())) {
        ready.push(id);
      } else if (st === "error") {
        errs.push(id);
      } else {
        still.push(id);
      }
    }

    const sameWatch =
      still.length === watch.length && still.every((id, i) => id === watch[i]);
    if (!sameWatch) {
      setDownloadWatchIds(still);
    }

    const freshReady = ready.filter((id) => !downloadPromotedRef.current.has(id));
    if (freshReady.length > 0) {
      for (const id of freshReady) {
        downloadPromotedRef.current.add(id);
      }
      setDownloadOfferIds((o) => [...new Set([...o, ...freshReady])]);
      setToast({
        msg:
          freshReady.length === 1
            ? "Рендер готов — запускаем скачивание."
            : `Готово файлов: ${freshReady.length}. Скачивание по очереди (пауза между файлами)…`,
        kind: "ok",
      });
      void (async () => {
        for (let i = 0; i < freshReady.length; i++) {
          if (i > 0) {
            await new Promise((r) => setTimeout(r, 650));
          }
          await runTaskDownload(freshReady[i]);
        }
      })();
    }

    for (const id of errs) {
      if (downloadErrorNotifiedRef.current.has(id)) continue;
      downloadErrorNotifiedRef.current.add(id);
      setToast({ msg: `Задача #${id} завершилась с ошибкой (файл не сформирован).`, kind: "err" });
    }
  }, [tasksQ.data, tasksQ.dataUpdatedAt, runTaskDownload]);

  useEffect(() => {
    if (!toast) return;
    const id = window.setTimeout(() => setToast(null), 3500);
    return () => window.clearTimeout(id);
  }, [toast]);

  const profiles = useMemo(() => {
    const rows = ((profilesQ.data as ApiJson | undefined)?.profiles as ApiJson[] | undefined) ?? [];
    return rows.map((p) => String(p.adspower_id || "")).filter(Boolean);
  }, [profilesQ.data]);

  const presetOptions = useMemo(() => normalizeOptions(settings.available_presets), [settings.available_presets]);
  const templateOptions = useMemo(() => normalizeOptions(settings.available_templates), [settings.available_templates]);
  const blendOptions = useMemo(() => normalizeOptions(settings.available_overlay_blends), [settings.available_overlay_blends]);

  const geoOptions = useMemo((): OptionItem[] => {
    const raw = settings.available_geo_profiles;
    if (raw && typeof raw === "object" && !Array.isArray(raw)) {
      const keys = Object.keys(raw);
      if (keys.length > 0) {
        return keys.map((k) => {
          const kk = k.toLowerCase();
          const entry = raw[k] as Record<string, unknown>;
          const en = GEO_CITY_EN_LINE[kk];
          const labApi =
            typeof entry.label === "string" && entry.label.trim() ? entry.label.trim() : k.replace(/_/g, " ");
          return { value: kk, label: en || labApi };
        });
      }
    }
    return Object.keys(GEO_CITY_EN_LINE).map((k) => ({ value: k, label: GEO_CITY_EN_LINE[k] }));
  }, [settings.available_geo_profiles]);

  const geoPresetKeySet = useMemo(() => new Set(geoOptions.map((o) => o.value)), [geoOptions]);

  const geoSelectValue = useMemo(() => {
    const raw = (settings.geo_profile || "").trim().toLowerCase();
    if (!raw) return "__custom__";
    if (geoPresetKeySet.has(raw)) return raw;
    return "__custom__";
  }, [settings.geo_profile, geoPresetKeySet]);

  useEffect(() => {
    const p = (settings.geo_profile || "").trim();
    const k = p.toLowerCase();
    if (geoPresetKeySet.has(k)) {
      setGeoCustomDraft("");
      return;
    }
    setGeoCustomDraft(p ? geoKeyToDisplayLine(p) : "");
  }, [settings.geo_profile, geoPresetKeySet]);

  function commitCustomGeoProfile(): void {
    if (geoSelectValue !== "__custom__") return;
    flushSync(() => {
      setSettings((s) => ({
        ...s,
        geo_profile: parseGeoDisplayToProfile(geoCustomDraft),
      }));
    });
  }

  const geoLine = useMemo(() => {
    if (settings.geo_enabled === false) return "выкл.";
    return geoKeyToDisplayLine(settings.geo_profile || "busan");
  }, [settings.geo_enabled, settings.geo_profile]);

  const deviceModelOptions = useMemo(
    () => normalizeOptions(settings.available_device_models),
    [settings.available_device_models],
  );
  const intensityOptions = useMemo(() => {
    const raw = settings.available_uniqualize_intensity;
    if (raw && typeof raw === "object") {
      return Object.entries(raw).map(([k, v]) => ({
        value: k,
        label: String((v as { label?: string })?.label ?? k),
      }));
    }
    return [
      { value: "low", label: "Мягко" },
      { value: "med", label: "Норма" },
      { value: "high", label: "Сильнее" },
    ];
  }, [settings.available_uniqualize_intensity]);
  const deviceModelPresetValues = useMemo(
    () => new Set(deviceModelOptions.map((o) => o.value)),
    [deviceModelOptions],
  );
  const deviceModelSelectValue = useMemo(() => {
    if (deviceModelOptions.length === 0) return DEVICE_MODEL_CUSTOM;
    const m = (settings.device_model || "").trim();
    if (m && deviceModelPresetValues.has(m)) return m;
    if (m) return DEVICE_MODEL_CUSTOM;
    return deviceModelOptions[0]?.value || DEVICE_MODEL_CUSTOM;
  }, [settings.device_model, deviceModelPresetValues, deviceModelOptions]);

  const enabledEffectsCount = useMemo(() => {
    const ex = settings.effects || {};
    return Object.values(ex).filter(Boolean).length;
  }, [settings.effects]);

  /** Оценка уровня защиты (0–100) на основе текущих настроек. */
  const protectionScore = useMemo(() => {
    const intensity = settings.uniqualize_intensity || "med";
    let score = intensity === "high" ? 72 : intensity === "low" ? 42 : 58;
    score += Math.min(enabledEffectsCount * 4, 16);
    if (rotateTemplates) score += 6;
    if (randomizeEffects) score += 8;
    return Math.min(95, Math.max(30, score));
  }, [settings.uniqualize_intensity, enabledEffectsCount, rotateTemplates, randomizeEffects]);

  useEffect(() => {
    if (!videoFile) {
      setVideoBlobUrl(null);
      return;
    }
    const u = URL.createObjectURL(videoFile);
    setVideoBlobUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [videoFile]);

  const serverVideoPreviewUrl = useMemo(() => {
    const base = storedUploadBasenameFromPath(videoPath);
    if (!base) return null;
    const q = new URLSearchParams({ tenant: tenantId });
    return `${apiUrl(`/api/uploads/video/${encodeURIComponent(base)}`)}?${q}`;
  }, [videoPath, tenantId]);

  const videoPreviewSrc = videoBlobUrl ?? serverVideoPreviewUrl;

  const effects = settings.effects || {};
  const availableEffects = settings.available_effects || { mirror: "Mirror", noise: "Noise", speed: "Speed" };
  const availableEffectLevels = settings.available_effect_levels || DEFAULT_EFFECT_LEVELS;

  const hasVideo = Boolean(videoPath.trim());
  const hasStyle = Boolean(settings.preset && settings.template);
  const hasEffects = effectsReviewed || Object.values(effects).some(Boolean);
  const overlayIsUserUpload = pathLooksLikeTenantUpload(String(settings.overlay_media_path || ""));
  const hasLayers =
    layersReviewed ||
    overlayIsUserUpload ||
    Boolean(settings.subtitle_srt_path) ||
    Boolean((settings.subtitle || "").trim());
  const allStepsReady = hasVideo && hasStyle && hasEffects && hasLayers;

  const maxReachableStep =
    flowMode === "free"
      ? 5
      : hasLayers
        ? 5
        : hasEffects
          ? 4
          : hasStyle
            ? 3
            : hasVideo
              ? 2
              : 1;

  const stepNavOpen = (step: number) =>
    flowMode === "free" || allStepsReady || step <= maxReachableStep;

  useEffect(() => {
    if (activeStep > maxReachableStep) setActiveStep(maxReachableStep);
  }, [activeStep, maxReachableStep]);

  async function persistSettingsToServer(): Promise<void> {
    await apiFetch("/api/uniqualizer/settings", { method: "POST", tenantId, body: JSON.stringify(settings) });
    await qc.invalidateQueries({ queryKey: ["uq-settings", tenantId] });
  }

  /** Сохранить часть настроек слоёв без гонки со старым state. */
  function persistLayerPatch(patch: Partial<UqSettings>, okMsg?: string): void {
    setSettings((prev) => {
      const merged = { ...prev, ...patch };
      void (async () => {
        try {
          await apiFetch("/api/uniqualizer/settings", { method: "POST", tenantId, body: JSON.stringify(merged) });
          await qc.invalidateQueries({ queryKey: ["uq-settings", tenantId] });
          if (okMsg) setToast({ msg: okMsg, kind: "ok" });
        } catch (e) {
          setToast({ msg: e instanceof Error ? e.message : "Не удалось сохранить", kind: "err" });
        }
      })();
      return merged;
    });
  }

  const saveSettingsMut = useMutation({
    mutationFn: () => apiFetch("/api/uniqualizer/settings", { method: "POST", tenantId, body: JSON.stringify(settings) }),
    onSuccess: async () => {
      setSubtitleTouched(false);
      setToast({ msg: "Настройки уникализатора сохранены", kind: "ok" });
      await qc.invalidateQueries({ queryKey: ["uq-settings", tenantId] });
    },
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });

  const uploadMut = useMutation({
    mutationFn: async ({ file, purpose }: { file: File; purpose: "video" | "overlay" | "srt" }) => {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("purpose", purpose);
      return apiFetch<ApiJson>("/api/upload", { method: "POST", tenantId, body: fd });
    },
  });

  const aiPreviewMut = useMutation({
    mutationFn: () =>
      apiFetch<ApiJson>("/api/ai/preview", {
        method: "POST",
        tenantId,
        body: JSON.stringify({ niche: (settings.niche || "YouTube Shorts").trim() || "YouTube Shorts" }),
      }),
    onSuccess: (data: ApiJson) => {
      setAiMeta(data);
      setToast({ msg: "AI-метаданные сгенерированы", kind: "ok" });
    },
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });

  const fillSubtitleFromAi = useCallback(async () => {
    try {
      let d: ApiJson = aiMeta || {};
      if (!snippetFromAiMeta(d)) {
        d = await apiFetch<ApiJson>("/api/ai/preview", {
          method: "POST",
          tenantId,
          body: JSON.stringify({ niche: (settings.niche || "YouTube Shorts").trim() || "YouTube Shorts" }),
        });
        setAiMeta(d);
      }
      const s = snippetFromAiMeta(d);
      if (!s) {
        setToast({ msg: "AI не вернул текст — проверьте ключ Groq в настройках.", kind: "err" });
        return;
      }
      setSubtitleTouched(true);
      setSettings((prev) => ({ ...prev, subtitle: s }));
      setToast({ msg: "Текст на видео вставлен из AI (overlay/title)", kind: "ok" });
    } catch (e) {
      setToast({ msg: e instanceof Error ? e.message : "Ошибка AI", kind: "err" });
    }
  }, [aiMeta, settings.niche, tenantId]);

  const runMut = useMutation({
    mutationFn: async () => {
      if (!videoPath.trim()) throw new Error("Укажите исходное видео");
      await persistSettingsToServer();
      await apiFetch("/api/pipeline/start", { method: "POST", tenantId });
      const sub = (settings.subtitle || "").trim();
      const created = await apiFetch<ApiJson>("/api/tasks", {
        method: "POST",
        tenantId,
        body: JSON.stringify({
          original_video: videoPath.trim(),
          target_profile: targetProfile.trim(),
          render_only: renderOnly,
          check_duplicates: checkDuplicates,
          ...(sub ? { subtitle: sub } : {}),
          ...(settings.template ? { template: settings.template } : {}),
        }),
      });
      const taskId = taskIdFromPayload(created);
      if (taskId > 0) {
        await apiFetch("/api/pipeline/enqueue", { method: "POST", tenantId, body: JSON.stringify({ task_id: taskId }) });
      }
      return created;
    },
    onSuccess: async (created) => {
      setToast({ msg: "Рендер поставлен в очередь", kind: "ok" });
      const taskId = taskIdFromPayload(created);
      if (taskId > 0) {
        setDownloadWatchIds((p) => [...new Set([...p, taskId])]);
        await qc.invalidateQueries({ queryKey: ["tasks", tenantId] });
      }
    },
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });

  const variantsMut = useMutation({
    mutationFn: async () => {
      await persistSettingsToServer();
      const rawLines = variantsSubtitlesText.split(/\r?\n/);
      const useLines = variantsSubtitlesText.trim().length > 0;
      let subtitles: string[] | undefined;
      if (useLines) {
        if (rawLines.length !== variantsCount) {
          throw new Error(`В поле CTA для variants нужно ровно ${variantsCount} строк (сейчас ${rawLines.length}).`);
        }
        subtitles = rawLines.map((l) => l.trim());
      }
      const oneSub = (settings.subtitle || "").trim();
      return apiFetch("/api/variants/generate", {
        method: "POST",
        tenantId,
        body: JSON.stringify({
          source_video: videoPath.trim(),
          target_profile: targetProfile.trim(),
          render_only: renderOnly,
          count: variantsCount,
          enqueue: true,
          auto_start_pipeline: true,
          ...(subtitles ? { subtitles } : oneSub ? { subtitle: oneSub } : {}),
          ...(rotateTemplates ? { rotate_templates: true } : settings.template ? { template: settings.template } : {}),
          ...(randomizeEffects ? { randomize_effects: true } : {}),
          ...(randomizeDeviceGeo ? { randomize_device_geo: true } : {}),
          ...(variantsPriority !== 0 ? { priority: variantsPriority } : {}),
        }),
      });
    },
    onSuccess: async (data) => {
      setToast({ msg: "Пакет вариаций создан", kind: "ok" });
      const raw = data.created_ids;
      const ids = Array.isArray(raw) ? raw.map((x) => Number(x)).filter((n) => n > 0) : [];
      if (ids.length) {
        setDownloadWatchIds((p) => [...new Set([...p, ...ids])]);
        await qc.invalidateQueries({ queryKey: ["tasks", tenantId] });
      }
    },
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });

  const previewMut = useMutation({
    mutationFn: () =>
      apiFetch<ApiJson>("/api/render/preview", {
        method: "POST",
        tenantId,
        body: JSON.stringify({
          source_video: videoPath.trim(),
          preview_duration_sec: 10,
          ...(settings.preset ? { preset: settings.preset } : {}),
          ...(settings.template ? { template: settings.template } : {}),
          ...(settings.effects ? { effects: settings.effects } : {}),
        }),
      }),
    onSuccess: (data) => {
      setToast({ msg: `Превью готово: task #${data.task_id ?? data.id ?? "?"}`, kind: "ok" });
    },
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });

  const cancelMut = useMutation({
    mutationFn: (taskId: number) => apiFetch(`/api/tasks/${taskId}/cancel`, { method: "POST", tenantId }),
    onSuccess: () => setToast({ msg: "Отмена отправлена в пайплайн", kind: "ok" }),
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });
  const stopPipelineMut = useMutation({
    mutationFn: () => apiFetch("/api/pipeline/stop", { method: "POST", tenantId }),
    onSuccess: async () => {
      setToast({ msg: "Пайплайн остановлен", kind: "ok" });
      await qc.invalidateQueries({ queryKey: ["render-progress", tenantId] });
    },
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });
  const restartQueueMut = useMutation({
    mutationFn: async () => {
      await apiFetch("/api/pipeline/stop", { method: "POST", tenantId });
      await apiFetch("/api/pipeline/start", { method: "POST", tenantId });
      return apiFetch<ApiJson>("/api/pipeline/enqueue-pending", { method: "POST", tenantId });
    },
    onSuccess: async (data: ApiJson) => {
      const n = Number(data.enqueued || 0);
      setToast({ msg: `Очередь перезапущена${n > 0 ? `, добавлено задач: ${n}` : ""}`, kind: "ok" });
      await qc.invalidateQueries({ queryKey: ["render-progress", tenantId] });
    },
    onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
  });

  const progressVisible = Boolean(progressQ.data?.visible);
  const progressTaskId = Number(progressQ.data?.task_id || 0);
  const progressPercent = Number(progressQ.data?.percent || 0);
  const canRun =
    hasVideo &&
    !runMut.isPending &&
    !variantsMut.isPending &&
    (renderOnly || Boolean(targetProfile.trim()));
  const canGoToRender = hasVideo && hasStyle && hasEffects && hasLayers;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!e.ctrlKey || e.key !== "Enter") return;
      if (!canRun || !canGoToRender || runMut.isPending) return;
      e.preventDefault();
      runMut.mutate();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [canRun, canGoToRender, runMut]);

  function uploadSelectedVideo(file: File): void {
    uploadMut.mutate(
      { file, purpose: "video" },
      {
        onSuccess: (d) => {
          const p = String(d.path || "");
          if (p) setVideoPath(p);
          setToast({ msg: "Видео загружено", kind: "ok" });
        },
        onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
      },
    );
  }

  function uploadSelectedOverlay(file: File): void {
    uploadMut.mutate(
      { file, purpose: "overlay" },
      {
        onSuccess: (d) => {
          setOverlayFile(null);
          setSettings((s) => ({ ...s, overlay_media_path: String(d.overlay_media_path || d.path || "") }));
          setToast({ msg: "Overlay загружен", kind: "ok" });
        },
        onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
      },
    );
  }

  function uploadSelectedSrt(file: File): void {
    uploadMut.mutate(
      { file, purpose: "srt" },
      {
        onSuccess: (d) => {
          setSrtFile(null);
          setSettings((s) => ({ ...s, subtitle_srt_path: String(d.subtitle_srt_path || d.path || "") }));
          setToast({ msg: "SRT загружен", kind: "ok" });
        },
        onError: (e: Error) => setToast({ msg: e.message, kind: "err" }),
      },
    );
  }

  useEffect(() => {
    if (!videoFile) return;
    uploadSelectedVideo(videoFile);
  // intentionally reacts to selected file; mutation state prevents duplicate submit while pending
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoFile]);

  useEffect(() => {
    if (!overlayFile) return;
    uploadSelectedOverlay(overlayFile);
  // intentionally reacts to selected file once
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [overlayFile]);

  useEffect(() => {
    if (!srtFile) return;
    uploadSelectedSrt(srtFile);
  // intentionally reacts to selected file once
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [srtFile]);

  function goStep(next: number): void {
    if (flowMode === "free" || allStepsReady || next <= maxReachableStep) {
      setActiveStep(next);
      return;
    }
    setToast({ msg: `Сначала завершите шаги 1–${maxReachableStep}`, kind: "err" });
  }

  /** Один клик — оптимальные настройки для UBT-арбитражного трафика. */
  function applyUbtPreset(): void {
    setSettings((s) => ({
      ...s,
      uniqualize_intensity: "high",
      template: "ugc",
      preset: "deep",
      niche: "YouTube Shorts",
    }));
    setRotateTemplates(true);
    setRandomizeEffects(true);
    setRandomizeDeviceGeo(true);
    setToast({ msg: "UBT пресет применён: deep · ugc · intensity high · рандом включён", kind: "ok" });
  }

  function shortPath(p: string, maxLen = 52): string {
    const s = (p || "").trim();
    if (!s) return "—";
    if (s.length <= maxLen) return s;
    return `…${s.slice(-(maxLen - 1))}`;
  }

  function formatBytes(n: number): string {
    if (!Number.isFinite(n) || n < 0) return "—";
    if (n < 1024) return `${Math.round(n)} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  }

  function clearVideo(): void {
    setVideoPath("");
    setVideoFile(null);
  }

  async function handleDownloadTask(taskId: number): Promise<void> {
    await runTaskDownload(taskId);
  }

  const completedSteps = [hasVideo, hasStyle, hasEffects, hasLayers, allStepsReady].filter(Boolean).length;
  const wizardProgressPct = Math.round((completedSteps / 5) * 100);

  return (
    <section className="page uniq-page">
      {toast && (
        <div className="toast-container">
          <div className={`toast-v2 ${toast.kind === "err" ? "error" : "success"}`}>
            <span className="toast-v2-icon">{toast.kind === "err" ? "✕" : "✓"}</span>
            <span className="toast-v2-msg">{toast.msg}</span>
            <button type="button" className="toast-v2-close" onClick={() => setToast(null)} aria-label="Закрыть">✕</button>
          </div>
        </div>
      )}
      <div className="panel">
        <div className="panel-title uq-brand-title">
          <span className="uq-brand-name">Уникализатор</span>
          <span className="uq-version-badge">v0.4</span>
        </div>
        <div className="uniq-panel-intro uq-top-intro">
          <span className="inline-note uq-ref-hide-note uq-top-intro-note">
            {flowMode === "guide"
              ? "Мастер: шаги открываются по мере заполнения."
              : "Свободный режим: любой шаг доступен; запуск всё равно требует заполненных полей."}
          </span>
          <div className="dest-toggle uq-flow-toggle">
            <button type="button" className={`dest-option ${flowMode === "guide" ? "active" : ""}`} onClick={() => setFlowMode("guide")}>
              Мастер
            </button>
            <button type="button" className={`dest-option ${flowMode === "free" ? "active" : ""}`} onClick={() => setFlowMode("free")}>
              Свободно
            </button>
          </div>
        </div>

        <div className="uq-wizard-shell">
          <div className="uq-wizard-meta">
            <div className="uq-wizard-meta-title">Мастер настройки</div>
            <div className="uq-wizard-meta-subtitle">
              Завершено шагов: <span className="mono">{completedSteps}/5</span>
            </div>
          </div>
          <div className="uq-wizard-progress">
            <div className="uq-wizard-progress-track">
              <div className="uq-wizard-progress-fill" style={{ width: `${wizardProgressPct}%` }} />
            </div>
            <span className="uq-wizard-progress-value mono">{wizardProgressPct}%</span>
          </div>
        </div>

        {downloadOfferIds.length > 0 ? (
          <div className="info-box uq-download-ready">
            <div className="uq-download-ready-title">Готово к скачиванию</div>
            <p className="uq-download-ready-desc">
              Скачивание уже запускается автоматически. Кнопки ниже — если браузер заблокировал загрузку или нужен повтор.
            </p>
            <div className="uq-download-ready-tasks">
              {downloadOfferIds.map((id) => (
                <div key={id} className="uq-download-ready-row">
                  <span className="uq-download-ready-taskid mono">Задача #{id}</span>
                  <button
                    type="button"
                    className="btn btn-cyan btn-with-icon"
                    disabled={downloadingTaskId !== null}
                    onClick={() => void handleDownloadTask(id)}
                  >
                    <Download size={ICON_SZ} strokeWidth={ICON_STROKE} aria-hidden />
                    {downloadingTaskId === id ? "Скачивание…" : "Скачать MP4"}
                  </button>
                </div>
              ))}
            </div>
            <button type="button" className="btn btn-ghost-outline uq-download-ready-dismiss" onClick={() => setDownloadOfferIds([])}>
              Скрыть панель
            </button>
          </div>
        ) : null}

        <div className="wizard-stepper uq-wizard-stepper">
          <button type="button" className={`wizard-step wizard-step-btn ${hasVideo ? "done" : ""} ${activeStep === 1 ? "active" : ""}`} onClick={() => goStep(1)}><span className="step-num">{hasVideo ? "✓" : "1"}</span><Clapperboard size={ICON_SZ} strokeWidth={ICON_STROKE} aria-hidden />Видео</button>
          <button type="button" className={`wizard-step wizard-step-btn ${hasStyle ? "done" : ""} ${activeStep === 2 ? "active" : ""} ${!stepNavOpen(2) ? "locked" : ""}`} onClick={() => goStep(2)}><span className="step-num">{hasStyle ? "✓" : "2"}</span><Palette size={ICON_SZ} strokeWidth={ICON_STROKE} aria-hidden />Стиль</button>
          <button type="button" className={`wizard-step wizard-step-btn ${hasEffects ? "done" : ""} ${activeStep === 3 ? "active" : ""} ${!stepNavOpen(3) ? "locked" : ""}`} onClick={() => goStep(3)}><span className="step-num">{hasEffects ? "✓" : "3"}</span><Sparkles size={ICON_SZ} strokeWidth={ICON_STROKE} aria-hidden />Эффекты</button>
          <button type="button" className={`wizard-step wizard-step-btn ${hasLayers ? "done" : ""} ${activeStep === 4 ? "active" : ""} ${!stepNavOpen(4) ? "locked" : ""}`} onClick={() => goStep(4)}><span className="step-num">{hasLayers ? "✓" : "4"}</span><PanelsTopLeft size={ICON_SZ} strokeWidth={ICON_STROKE} aria-hidden />Слои</button>
          <button type="button" className={`wizard-step wizard-step-btn ${allStepsReady ? "done" : ""} ${progressVisible || activeStep === 5 ? "active" : ""} ${!stepNavOpen(5) ? "locked" : ""}`} onClick={() => goStep(5)}><span className="step-num">{allStepsReady ? "✓" : "5"}</span><Rocket size={ICON_SZ} strokeWidth={ICON_STROKE} aria-hidden />Запуск</button>
        </div>

        <div className="uniq-layout">
          <div className="uniq-main-col">
            {activeStep === 1 && (
              <div className="card">
                <div className="card-header"><span className="card-title">1. Видео</span></div>
                <div className="card-body uniq-form-tight">
                  <div
                    className={`uq-dropzone-hero dropzone ${videoDragOver ? "drag" : ""}`}
                    role="button"
                    tabIndex={0}
                    onDragEnter={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      setVideoDragOver(true);
                    }}
                    onDragOver={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      setVideoDragOver(true);
                    }}
                    onDragLeave={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      setVideoDragOver(false);
                    }}
                    onDrop={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      setVideoDragOver(false);
                      const f = e.dataTransfer.files?.[0];
                      if (f) setVideoFile(f);
                    }}
                    onClick={() => document.getElementById("uq-video-file")?.click()}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") document.getElementById("uq-video-file")?.click();
                    }}
                    aria-label="Перетащите видео сюда или выберите файл"
                  >
                    <CloudUpload className="uq-dropzone-icon" size={56} strokeWidth={1.35} aria-hidden />
                    <div className="uq-dropzone-title">Перетащи видео сюда</div>
                    <div className="uq-dropzone-sub">или нажми, чтобы выбрать — mp4, mov, webm, mkv</div>
                  </div>
                  <input
                    id="uq-video-file"
                    type="file"
                    accept="video/*,.mp4,.mov,.webm,.mkv,.avi"
                    style={{ display: "none" }}
                    onChange={(e) => setVideoFile(e.target.files?.[0] ?? null)}
                  />
                  {hasVideo ? (
                    <ul className="uq-file-list">
                      <li className="uq-file-row">
                        <GripVertical className="uq-file-grip" size={18} strokeWidth={1.5} aria-hidden />
                        <Film className="film-ic" size={20} strokeWidth={1.75} aria-hidden />
                        <div className="uq-file-meta">
                          <span className="uq-file-name mono">{shortPath(videoPath, 64)}</span>
                          <span className="uq-file-size">
                            {videoFile ? formatBytes(videoFile.size) : "файл на сервере"}
                          </span>
                        </div>
                        <button type="button" className="uq-file-remove" onClick={clearVideo} aria-label="Убрать видео">
                          ×
                        </button>
                      </li>
                    </ul>
                  ) : null}
                  <div className="uq-upload-toolbar">
                    <button type="button" className="btn btn-cyan" onClick={() => document.getElementById("uq-video-file")?.click()}>
                      Выбрать файлы
                    </button>
                    <button type="button" className="btn btn-ghost-outline" disabled={!hasVideo} onClick={clearVideo}>
                      Очистить
                    </button>
                    {uploadMut.isPending ? <span className="inline-note">Загрузка на сервер…</span> : null}
                  </div>
                  <div className="form-group" style={{ marginBottom: 0, marginTop: 18 }}>
                    <label className="form-label">Путь на сервере</label>
                    <input className="form-input mono" value={videoPath} onChange={(e) => setVideoPath(e.target.value)} />
                  </div>
                  <div className="toolbar" style={{ marginTop: 20 }}>
                    <button type="button" className="btn btn-cyan" disabled={!hasVideo} onClick={() => goStep(2)}>
                      Далее к шагу 2
                    </button>
                  </div>
                </div>
              </div>
            )}

            {activeStep === 2 && (
              <div className="card">
                <div className="card-header uq-card-header-row">
                  <span className="card-title">2. Пресеты и типы наложения</span>
                  <button
                    type="button"
                    className="btn btn-sm btn-with-icon uq-soft-amber-btn"
                    onClick={applyUbtPreset}
                    title="Применить оптимальные настройки для UBT-арбитражного трафика: deep · ugc · intensity high · рандом"
                  >
                    <Zap size={13} strokeWidth={2} aria-hidden />
                    UBT пресет
                  </button>
                </div>
                <div className="card-body uniq-form-tight">
                  {/* Preset visual cards */}
                  <div className="form-label" style={{ marginBottom: 8 }}>Пресет обработки</div>
                  <div className="preset-grid">
                    {[
                      { value: "standard", label: "Стандарт", desc: "CRF 26 · fast", color: "linear-gradient(135deg,#4A6FA5,#6B8FC7)" },
                      { value: "soft",     label: "Мягко",    desc: "CRF 22 · film", color: "linear-gradient(135deg,#8B6FA5,#AB8FC7)" },
                      { value: "deep",     label: "Глубокий", desc: "CRF 23 · fast", color: "linear-gradient(135deg,#A5344A,#C75060)" },
                      { value: "ultra",    label: "Ультра",   desc: "CRF 20 · slow", color: "linear-gradient(135deg,#C77830,#E89840)" },
                    ].map((p) => (
                      <div
                        key={p.value}
                        className={`preset-card${(settings.preset || "deep") === p.value ? " selected" : ""}`}
                        onClick={() => setSettings((s) => ({ ...s, preset: p.value }))}
                        role="button"
                        tabIndex={0}
                        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setSettings((s) => ({ ...s, preset: p.value })); }}
                        aria-pressed={(settings.preset || "deep") === p.value}
                      >
                        <div className="preset-swatch" style={{ background: p.color }} />
                        <div className="preset-name">{p.label}</div>
                        <div className="preset-desc">{p.desc}</div>
                      </div>
                    ))}
                  </div>

                  {/* Template visual cards */}
                  <div className="form-label" style={{ marginBottom: 8 }}>Шаблон монтажа</div>
                  <div className="template-grid">
                    {[
                      { value: "default",  label: "Стандарт", color: "var(--text-tertiary)", badge: "норм", badgeColor: "rgba(148,163,184,0.25)", badgeBorder: "rgba(148,163,184,0.4)" },
                      { value: "reaction", label: "Реакция",  color: "var(--accent-amber)",  badge: "split-screen", badgeColor: "rgba(245,158,11,0.15)", badgeBorder: "rgba(245,158,11,0.35)" },
                      { value: "news",     label: "Новости",  color: "var(--accent-cyan)",   badge: "нижн. бар", badgeColor: "rgba(6,182,212,0.15)", badgeBorder: "rgba(6,182,212,0.35)" },
                      { value: "story",    label: "Story",    color: "var(--accent-red)",    badge: "9:16 zoom", badgeColor: "rgba(239,68,68,0.15)", badgeBorder: "rgba(239,68,68,0.35)" },
                      { value: "ugc",      label: "UGC",      color: "var(--accent-green)",  badge: "★ арбитраж", badgeColor: "rgba(34,197,94,0.18)", badgeBorder: "rgba(34,197,94,0.55)" },
                    ].map((t) => (
                      <div
                        key={t.value}
                        className={`template-card${(settings.template || "default") === t.value ? " selected" : ""}`}
                        onClick={() => setSettings((s) => ({ ...s, template: t.value }))}
                        role="button"
                        tabIndex={0}
                        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setSettings((s) => ({ ...s, template: t.value })); }}
                        aria-pressed={(settings.template || "default") === t.value}
                      >
                        <div className="template-thumb"><div className="template-thumb-bar" style={{ background: t.color }} /></div>
                        <div className="template-name">{t.label}</div>
                        <div style={{ fontSize: 10, marginTop: 3, padding: "1px 6px", borderRadius: 999, background: t.badgeColor, border: `1px solid ${t.badgeBorder}`, color: "var(--text-secondary)", whiteSpace: "nowrap", display: "inline-block" }}>{t.badge}</div>
                      </div>
                    ))}
                  </div>

                  {/* Intensity chips */}
                  <div className="form-label" style={{ marginBottom: 8 }}>Разброс уникализации</div>
                  <div className="intensity-grid">
                    {intensityOptions.map((p) => (
                      <div
                        key={p.value}
                        className={`intensity-chip ${p.value}${(settings.uniqualize_intensity || "med") === p.value ? " selected" : ""}`}
                        onClick={() => setSettings((s) => ({ ...s, uniqualize_intensity: p.value }))}
                        role="button"
                        tabIndex={0}
                        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setSettings((s) => ({ ...s, uniqualize_intensity: p.value })); }}
                        aria-pressed={(settings.uniqualize_intensity || "med") === p.value}
                      >
                        {p.label}
                      </div>
                    ))}
                  </div>

                  <div className="form-grid">
                    <label className="form-label" style={{ margin: 0 }}>Ниша для AI</label>
                    <input
                      className="form-input"
                      placeholder="YouTube Shorts"
                      value={settings.niche ?? ""}
                      onChange={(e) => setSettings((s) => ({ ...s, niche: e.target.value }))}
                    />
                    <label className="form-label" style={{ margin: 0 }}>Отпечаток устройства</label>
                    <div style={{ display: "grid", gap: 8 }}>
                      {deviceModelOptions.length > 0 ? (
                        <select
                          className="form-select"
                          value={deviceModelSelectValue}
                          onChange={(e) => {
                            const v = e.target.value;
                            if (v === DEVICE_MODEL_CUSTOM) {
                              setSettings((s) => ({ ...s, device_model: (s.device_model || "").trim() }));
                              return;
                            }
                            setSettings((s) => ({ ...s, device_model: v }));
                          }}
                        >
                          {deviceModelOptions.map((p) => (
                            <option key={p.value} value={p.value}>
                              {p.label}
                            </option>
                          ))}
                          <option value={DEVICE_MODEL_CUSTOM}>Своя модель (вручную)…</option>
                        </select>
                      ) : null}
                      {deviceModelOptions.length === 0 || deviceModelSelectValue === DEVICE_MODEL_CUSTOM ? (
                        <input
                          className="form-input mono"
                          placeholder="Например: Samsung SM-S918N или iPhone 13 mini"
                          value={settings.device_model ?? ""}
                          onChange={(e) => setSettings((s) => ({ ...s, device_model: e.target.value }))}
                        />
                      ) : null}
                    </div>
                  </div>
                  <div className="inline-note" style={{ marginTop: 4 }}>
                    Пустая ниша на сервере станет «YouTube Shorts». Для устройства: пустая строка в ручном режиме → «Samsung
                    SM-S928N». Пресеты задают model + manufacturer в метаданных FFmpeg (Android / QuickTime).
                  </div>
                  <div className="toolbar">
                    <button type="button" className="btn btn-cyan btn-with-icon" disabled={saveSettingsMut.isPending || settingsQ.isLoading} onClick={() => saveSettingsMut.mutate()}><Save size={ICON_SZ} strokeWidth={ICON_STROKE} aria-hidden />Сохранить шаг 2</button>
                    <button type="button" className="btn" disabled={!hasStyle} onClick={() => goStep(3)}>Далее к шагу 3</button>
                  </div>
                </div>
              </div>
            )}

            {activeStep === 3 && (
              <div className="card">
                <div className="card-header uq-card-header-row">
                  <span className="card-title">3. Эффекты</span>
                  <button
                    type="button"
                    className="btn btn-sm uq-soft-amber-btn"
                    onClick={() => {
                      setSettings((s) => ({
                        ...s,
                        effects: { mirror: true, noise: true, crop_reframe: true, gamma_jitter: true, speed: false, audio_tone: true },
                        effect_levels: { crop_reframe: "med", gamma_jitter: "med", audio_tone: "med" },
                      }));
                      setToast({ msg: "Выбраны рекомендуемые эффекты для арбитражного контента", kind: "ok" });
                    }}
                  >
                    Рекомендуемые для арбитража
                  </button>
                </div>
                <div className="card-body uniq-form-tight">
                  <div className="effects-grid">
                    {Object.entries(availableEffects).map(([k, label]) => (
                      <div key={k} style={{ display: "grid", gap: 8 }}>
                        <label className="settings-row" style={{ margin: 0, cursor: "pointer" }}>
                          <input type="checkbox" checked={Boolean(effects[k])} onChange={() => setSettings((s) => ({ ...s, effects: toggleEffect(s.effects, k) }))} />
                          <span style={{ fontSize: 13, color: "var(--text-secondary)" }}>{label}</span>
                        </label>
                        {LEVEL_CONTROL_EFFECTS.has(k) && Boolean(effects[k]) && (
                          <>
                            {(() => {
                              const lvl = settings.effect_levels?.[k] || "med";
                              return (
                                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                  <span
                                    style={{
                                      fontSize: 11,
                                      lineHeight: "16px",
                                      padding: "1px 8px",
                                      borderRadius: 999,
                                      background: EFFECT_LEVEL_COLORS[lvl] || EFFECT_LEVEL_COLORS.med,
                                      border: `1px solid ${EFFECT_LEVEL_BORDERS[lvl] || EFFECT_LEVEL_BORDERS.med}`,
                                      color: "var(--text-primary)",
                                    }}
                                  >
                                    Level: {(availableEffectLevels[lvl] || lvl).toUpperCase()}
                                  </span>
                                </div>
                              );
                            })()}
                            <select
                              className="form-select"
                              value={settings.effect_levels?.[k] || "med"}
                              onChange={(e) =>
                                setSettings((s) => ({
                                  ...s,
                                  effect_levels: setEffectLevel(s.effect_levels, k, e.target.value),
                                }))
                              }
                            >
                              {Object.entries(availableEffectLevels).map(([value, lvlLabel]) => (
                                <option key={value} value={value}>
                                  {lvlLabel}
                                </option>
                              ))}
                            </select>
                            <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                              {EFFECT_LEVEL_HINTS[k]?.[settings.effect_levels?.[k] || "med"] || "Настройка интенсивности эффекта."}
                            </div>
                          </>
                        )}
                      </div>
                    ))}
                  </div>
                  <div className="toolbar">
                    <button type="button" className="btn btn-cyan btn-with-icon" disabled={saveSettingsMut.isPending} onClick={() => saveSettingsMut.mutate()}><Save size={ICON_SZ} strokeWidth={ICON_STROKE} aria-hidden />Сохранить шаг 3</button>
                    <button type="button" className="btn" onClick={() => { setEffectsReviewed(true); goStep(4); }}>Далее к шагу 4</button>
                  </div>
                </div>
              </div>
            )}

            {activeStep === 4 && (
              <div className="card">
                <div className="card-header uq-layer-card-head"><span className="card-title">Слои</span></div>
                <div className="card-body uniq-form-tight uq-layers-page">
                  <div className={`uq-layer-accordion${layerPanelOpen.overlay ? " is-open" : ""}`}>
                    <button
                      type="button"
                      className="uq-layer-accordion-head"
                      onClick={() => setLayerPanelOpen((o) => ({ ...o, overlay: !o.overlay }))}
                    >
                      <span className="uq-layer-accordion-title">Оверлей</span>
                      <span className={`uq-layer-badge${overlayIsUserUpload ? " uq-layer-badge--ok" : " uq-layer-badge--muted"}`}>
                        {overlayIsUserUpload ? "Задан" : "По умолчанию"}
                      </span>
                      <ChevronDown className={`uq-layer-chevron${layerPanelOpen.overlay ? " is-open" : ""}`} size={18} strokeWidth={2} aria-hidden />
                    </button>
                    {layerPanelOpen.overlay ? (
                      <div className="uq-layer-accordion-body">
                        <div className="uq-layer-field-label uq-layer-caps">Файл слоя</div>
                        <input
                          id="uq-overlay-layer"
                          type="file"
                          accept="image/*,video/*,.mp4,.mov,.webm,.mkv,.png,.jpg,.jpeg,.webp"
                          className="uq-layer-file-input"
                          onChange={(e) => setOverlayFile(e.target.files?.[0] ?? null)}
                        />
                        <div className="uq-layer-file-row">
                          <input
                            readOnly
                            className="form-input uq-layer-faux-input mono"
                            title={String(settings.overlay_media_path || "")}
                            value={
                              overlayIsUserUpload
                                ? shortPath(String(settings.overlay_media_path || ""), 52)
                                : "Встроенный слой"
                            }
                          />
                          <div className="uq-layer-file-actions">
                            <button type="button" className="btn btn-sm btn-cyan" onClick={() => document.getElementById("uq-overlay-layer")?.click()}>
                              Выбрать
                            </button>
                            <button
                              type="button"
                              className="btn btn-sm btn-ghost-outline"
                              disabled={!overlayIsUserUpload}
                              onClick={() => {
                                setOverlayFile(null);
                                persistLayerPatch({ overlay_media_path: "" }, "Слой сброшен");
                              }}
                            >
                              Сброс
                            </button>
                          </div>
                        </div>
                        {overlayFile ? (
                          <div className="inline-note" style={{ marginTop: 8 }}>
                            {uploadMut.isPending ? "Загрузка на сервер…" : `Выбран: ${overlayFile.name}`}
                          </div>
                        ) : null}
                        <div className="uq-layer-grid">
                          <label className="uq-layer-mini-label uq-layer-caps">Режим наложения</label>
                          <select
                            className="form-select uq-layer-select"
                            value={settings.overlay_mode || "on_top"}
                            onChange={(e) => setSettings((s) => ({ ...s, overlay_mode: e.target.value }))}
                          >
                            {OVERLAY_MODE_OPTS.map((p) => (
                              <option key={p.value} value={p.value}>
                                {p.label}
                              </option>
                            ))}
                          </select>
                          <label className="uq-layer-mini-label uq-layer-caps">Смешивание</label>
                          <select
                            className="form-select uq-layer-select"
                            value={settings.overlay_blend_mode || "normal"}
                            onChange={(e) => setSettings((s) => ({ ...s, overlay_blend_mode: e.target.value }))}
                          >
                            {blendOptions.map((p) => (
                              <option key={p.value} value={p.value}>
                                {p.label}
                              </option>
                            ))}
                          </select>
                          <label className="uq-layer-mini-label uq-layer-caps">Непрозрачность</label>
                          <div className="uq-layer-opacity-row">
                            <input
                              className="uq-layer-range"
                              type="range"
                              min={0}
                              max={100}
                              value={Math.round(Number(settings.overlay_opacity ?? 1) * 100)}
                              onChange={(e) =>
                                setSettings((s) => ({ ...s, overlay_opacity: Number(e.target.value) / 100 }))
                              }
                            />
                            <span className="uq-layer-opacity-val">{Math.round(Number(settings.overlay_opacity ?? 1) * 100)}%</span>
                          </div>
                          <label className="uq-layer-mini-label uq-layer-caps">Позиция</label>
                          <select
                            className="form-select uq-layer-select"
                            value={settings.overlay_position || "top_left"}
                            onChange={(e) => setSettings((s) => ({ ...s, overlay_position: e.target.value }))}
                          >
                            {OVERLAY_POSITION_OPTS.map((p) => (
                              <option key={p.value} value={p.value}>
                                {p.label}
                              </option>
                            ))}
                          </select>
                        </div>
                      </div>
                    ) : null}
                  </div>

                  <div className={`uq-layer-accordion${layerPanelOpen.text ? " is-open" : ""}`}>
                    <button
                      type="button"
                      className="uq-layer-accordion-head"
                      onClick={() => setLayerPanelOpen((o) => ({ ...o, text: !o.text }))}
                    >
                      <span className="uq-layer-accordion-title">Текст и субтитры</span>
                      <span
                        className={`uq-layer-badge${
                          (settings.subtitle || "").trim() || settings.subtitle_srt_path ? " uq-layer-badge--ok" : " uq-layer-badge--warn"
                        }`}
                      >
                        {(settings.subtitle || "").trim() || settings.subtitle_srt_path ? "Задан" : "Не задан"}
                      </span>
                      <ChevronDown className={`uq-layer-chevron${layerPanelOpen.text ? " is-open" : ""}`} size={18} strokeWidth={2} aria-hidden />
                    </button>
                    {layerPanelOpen.text ? (
                      <div className="uq-layer-accordion-body">
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
                          <div className="uq-layer-field-label uq-layer-caps" style={{ margin: 0 }}>Текст на видео (CTA)</div>
                          <button
                            type="button"
                            className="btn btn-sm btn-uq-ai btn-with-icon"
                            style={{ fontSize: 11, padding: "3px 8px" }}
                            disabled={aiPreviewMut.isPending}
                            onClick={() => void fillSubtitleFromAi()}
                            title="Сгенерировать текст через AI и вставить в поле"
                          >
                            <WandSparkles size={11} strokeWidth={1.75} aria-hidden />
                            {aiPreviewMut.isPending ? "AI…" : "Заполнить из AI"}
                          </button>
                        </div>
                        <textarea
                          className="form-input uq-layer-textarea"
                          rows={4}
                          placeholder="Короткая строка или CTA"
                          value={settings.subtitle || ""}
                          onChange={(e) => {
                            setSubtitleTouched(true);
                            setSettings((s) => ({ ...s, subtitle: e.target.value }));
                          }}
                        />
                        <div className="uq-layer-field-label uq-layer-caps" style={{ marginTop: 16 }}>
                          Стиль субтитров
                        </div>
                        <select
                          className="form-select uq-layer-select"
                          value={settings.subtitle_style === "readable" ? "readable" : "default"}
                          onChange={(e) => setSettings((s) => ({ ...s, subtitle_style: e.target.value }))}
                        >
                          <option value="default">Стандарт (компактнее)</option>
                          <option value="readable">Крупнее и с сильной обводкой</option>
                        </select>
                        <div className="uq-layer-field-label uq-layer-caps" style={{ marginTop: 14 }}>
                          Шрифт (как на сервере с FFmpeg)
                        </div>
                        <select
                          className="form-select uq-layer-select"
                          value={settings.subtitle_font ?? ""}
                          onChange={(e) => setSettings((s) => ({ ...s, subtitle_font: e.target.value }))}
                        >
                          {SUBTITLE_FONT_OPTIONS.map((o) => (
                            <option key={o.value || "__auto__"} value={o.value}>
                              {o.label}
                            </option>
                          ))}
                        </select>
                        <div className="uq-layer-field-label uq-layer-caps" style={{ marginTop: 14 }}>
                          Размер текста (px)
                        </div>
                        <div className="uq-layer-grid" style={{ marginTop: 6, gridTemplateColumns: "1fr auto", alignItems: "center" }}>
                          <input
                            className="form-input"
                            type="number"
                            min={12}
                            max={96}
                            placeholder="Авто по шаблону"
                            value={
                              settings.subtitle_font_size && settings.subtitle_font_size > 0
                                ? settings.subtitle_font_size
                                : ""
                            }
                            onChange={(e) => {
                              const raw = e.target.value.trim();
                              if (!raw) {
                                setSettings((s) => ({ ...s, subtitle_font_size: 0 }));
                                return;
                              }
                              const n = Math.max(12, Math.min(96, parseInt(raw, 10) || 0));
                              setSettings((s) => ({ ...s, subtitle_font_size: n > 0 ? n : 0 }));
                            }}
                          />
                          <button
                            type="button"
                            className="btn btn-sm btn-ghost-outline"
                            style={{ marginLeft: 8 }}
                            onClick={() => setSettings((s) => ({ ...s, subtitle_font_size: 0 }))}
                          >
                            Сброс авто
                          </button>
                        </div>
                        <p className="inline-note" style={{ marginTop: 8, fontSize: 11, lineHeight: 1.45 }}>
                          Pretendard и др. .otf в <span className="mono">core/fonts</span> передаются в libass через fontsdir.
                          Свои файлы — туда же или <span className="mono">NEORENDER_FONTS_DIR</span>. Эмодзи отдельно (Segoe UI
                          Emoji / Noto Color Emoji); свой — <span className="mono">NEORENDER_SUBTITLE_EMOJI_FONT</span>.
                        </p>
                        <div
                          className="uq-subtitle-preview"
                          style={{
                            marginTop: 12,
                            padding: "14px 16px",
                            borderRadius: 10,
                            border: "1px solid var(--border-subtle)",
                            background: "var(--bg-base)",
                            fontFamily: subtitlePreviewFontCss(settings.subtitle_font),
                            fontSize: (() => {
                              const n = Number(settings.subtitle_font_size);
                              if (n > 0) return Math.min(40, Math.max(14, n));
                              return settings.subtitle_style === "readable" ? 22 : 18;
                            })(),
                            fontWeight: 700,
                            color: "var(--text-primary)",
                            lineHeight: 1.25,
                            textAlign: "center",
                            wordBreak: "break-word",
                          }}
                        >
                          {(settings.subtitle || "").trim() || "Пример · Preview · 안녕하세요"}
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 20 }}>
                          <div className="uq-layer-field-label uq-layer-caps" style={{ margin: 0 }}>SRT</div>
                          <a
                            href="/subtitles"
                            style={{ fontSize: 11, color: "var(--accent-cyan)", textDecoration: "none", opacity: 0.85 }}
                            title="Перейти к AI-генератору субтитров"
                          >
                            ↗ Сгенерировать .srt
                          </a>
                        </div>
                        <input
                          id="uq-srt-layer"
                          type="file"
                          accept=".srt"
                          className="uq-layer-file-input"
                          onChange={(e) => setSrtFile(e.target.files?.[0] ?? null)}
                        />
                        <div className="uq-layer-file-row uq-layer-srt-row">
                          <div className="uq-layer-file-actions uq-layer-srt-actions">
                            <button type="button" className="btn btn-sm btn-cyan" onClick={() => document.getElementById("uq-srt-layer")?.click()}>
                              Выбрать .srt
                            </button>
                            <button
                              type="button"
                              className="btn btn-sm btn-ghost-outline"
                              disabled={!settings.subtitle_srt_path}
                              onClick={() => {
                                setSrtFile(null);
                                persistLayerPatch({ subtitle_srt_path: "" }, "SRT сброшен");
                              }}
                            >
                              Сбросить
                            </button>
                          </div>
                        </div>
                        {settings.subtitle_srt_path ? (
                          <div className="inline-note mono" style={{ marginTop: 6, fontSize: 11 }}>
                            {shortPath(String(settings.subtitle_srt_path), 56)}
                          </div>
                        ) : null}
                        {srtFile ? (
                          <div className="inline-note" style={{ marginTop: 8 }}>
                            {uploadMut.isPending ? "Загрузка SRT…" : `Выбран: ${srtFile.name}`}
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                  </div>

                  <div className={`uq-layer-accordion${layerPanelOpen.geo ? " is-open" : ""}`}>
                    <button
                      type="button"
                      className="uq-layer-accordion-head"
                      onClick={() => setLayerPanelOpen((o) => ({ ...o, geo: !o.geo }))}
                    >
                      <span className="uq-layer-accordion-title">Гео-инъекция</span>
                      <span
                        className={`uq-layer-badge${settings.geo_enabled === false ? " uq-layer-badge--muted" : " uq-layer-badge--ok"} uq-geo-badge-caps`}
                      >
                        {settings.geo_enabled === false ? "Выкл." : geoKeyToDisplayLine(settings.geo_profile || "busan")}
                      </span>
                      <ChevronDown className={`uq-layer-chevron${layerPanelOpen.geo ? " is-open" : ""}`} size={18} strokeWidth={2} aria-hidden />
                    </button>
                    {layerPanelOpen.geo ? (
                      <div className="uq-layer-accordion-body">
                        <label className="settings-row" style={{ cursor: "pointer", marginBottom: 12 }}>
                          <input
                            type="checkbox"
                            checked={settings.geo_enabled !== false}
                            onChange={(e) => setSettings((s) => ({ ...s, geo_enabled: e.target.checked }))}
                          />
                          <span style={{ fontSize: 13, color: "var(--text-secondary)", marginLeft: 8 }}>Гео в метаданные</span>
                        </label>
                        <div className="uq-layer-field-label uq-layer-caps">Геолокация</div>
                        <select
                          className="form-select uq-layer-select uq-geo-preset-select"
                          disabled={settings.geo_enabled === false}
                          value={geoSelectValue}
                          onChange={(e) => {
                            const v = e.target.value;
                            if (v === "__custom__") {
                              setSettings((s) => ({ ...s, geo_profile: "" }));
                              setGeoCustomDraft("");
                              return;
                            }
                            setSettings((s) => ({ ...s, geo_profile: v }));
                          }}
                        >
                          {geoOptions.map((p) => (
                            <option key={p.value} value={p.value}>
                              {p.label}
                            </option>
                          ))}
                          <option value="__custom__">Свои координаты…</option>
                        </select>
                        {geoSelectValue === "__custom__" ? (
                          <input
                            className="form-input uq-layer-select uq-geo-coords-input"
                            disabled={settings.geo_enabled === false}
                            placeholder="35.1796, 129.0756"
                            value={geoCustomDraft}
                            onChange={(e) => setGeoCustomDraft(e.target.value)}
                            onBlur={() =>
                              setSettings((s) => ({
                                ...s,
                                geo_profile: parseGeoDisplayToProfile(geoCustomDraft),
                              }))
                            }
                          />
                        ) : null}
                        <div className="uq-layer-field-label uq-layer-caps" style={{ marginTop: 14 }}>
                          Jitter
                        </div>
                        <input
                          className="form-input"
                          type="number"
                          min={0.01}
                          max={0.5}
                          step={0.01}
                          value={settings.geo_jitter ?? 0.05}
                          disabled={settings.geo_enabled === false}
                          onChange={(e) => setSettings((s) => ({ ...s, geo_jitter: Number(e.target.value) }))}
                        />
                      </div>
                    ) : null}
                  </div>

                  <div className="toolbar" style={{ marginTop: 20 }}>
                    <button
                      type="button"
                      className="btn btn-cyan btn-with-icon"
                      disabled={saveSettingsMut.isPending || settingsQ.isLoading}
                      onClick={() => {
                        commitCustomGeoProfile();
                        saveSettingsMut.mutate();
                      }}
                    >
                      <Save size={ICON_SZ} strokeWidth={ICON_STROKE} aria-hidden />
                      Сохранить шаг 4
                    </button>
                    <button
                      type="button"
                      className="btn"
                      onClick={() => {
                        commitCustomGeoProfile();
                        setLayersReviewed(true);
                        goStep(5);
                      }}
                    >
                      Далее к запуску
                    </button>
                  </div>
                </div>
              </div>
            )}

            {activeStep === 5 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {/* Назначение: скачать или антидетект */}
                <div className="card">
                  <div className="card-header"><span className="card-title">Назначение</span></div>
                  <div className="card-body" style={{ paddingBottom: 16 }}>
                    <div className="dest-toggle">
                      <button type="button" className={`dest-option ${renderOnly ? "active" : ""}`} onClick={() => setRenderOnly(true)}>
                        Скачать
                        <div className="dest-option-sub">Только рендер, файл на сервере</div>
                      </button>
                      <button type="button" className={`dest-option ${!renderOnly ? "active" : ""}`} onClick={() => setRenderOnly(false)}>
                        Антидетект
                        <div className="dest-option-sub">Рендер + залив через AdsPower</div>
                      </button>
                    </div>
                    {!renderOnly && (
                      <div className="form-group" style={{ marginTop: 12, marginBottom: 0 }}>
                        <label className="form-label">Профиль AdsPower</label>
                        <select className="form-select" value={targetProfile} onChange={(e) => setTargetProfile(e.target.value)}>
                          <option value="">— Выберите профиль —</option>
                          {profiles.map((id) => <option key={id} value={id}>{id}</option>)}
                        </select>
                      </div>
                    )}
                  </div>
                </div>

                {/* ── YouTube-настройки (только при заливе через антидетект) ── */}
                {!renderOnly && (
                  <div className="card">
                    <div className="card-header"><span className="card-title">YouTube: хэштеги и обложка</span></div>
                    <div className="card-body" style={{ paddingBottom: 16 }}>
                      <div className="form-group" style={{ marginBottom: 12 }}>
                        <label className="form-label">
                          Хэштеги
                          <span style={{ fontWeight: 400, color: "var(--text-muted)", marginLeft: 6 }}>через пробел или запятую</span>
                        </label>
                        <input
                          className="form-input"
                          placeholder="#shorts #viral #корея"
                          value={((settings.tags || []) as string[]).map((t) => `#${t}`).join(" ")}
                          onChange={(e) => {
                            const raw = e.target.value;
                            const parsed = raw.split(/[\s,]+/).map((t) => t.trim().replace(/^#+/, "")).filter(Boolean);
                            setSettings((s) => ({ ...s, tags: parsed }));
                          }}
                          onBlur={() => {
                            saveSettingsMut.mutate();
                          }}
                        />
                        <div className="inline-note" style={{ marginTop: 4 }}>
                          Добавляются в конец описания при заливе. Максимум 30.
                        </div>
                      </div>
                      <div className="form-group" style={{ marginBottom: 0 }}>
                        <label className="form-label">
                          Кастомный thumbnail
                          {settings.thumbnail_path && (
                            <span style={{ fontWeight: 400, color: "var(--accent-cyan)", marginLeft: 8 }}>
                              {String(settings.thumbnail_path).split(/[/\\]/).pop()}
                            </span>
                          )}
                        </label>
                        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                          <label className="action-btn" style={{ cursor: "pointer", marginBottom: 0 }}>
                            Загрузить обложку
                            <input
                              type="file"
                              accept="image/png,image/jpeg,image/webp"
                              style={{ display: "none" }}
                              onChange={async (e) => {
                                const f = e.target.files?.[0];
                                if (!f) return;
                                const fd = new FormData();
                                fd.append("file", f);
                                fd.append("purpose", "overlay");
                                try {
                                  const r = await apiFetch<ApiJson>("/api/upload", { method: "POST", tenantId, body: fd });
                                  const p = String(r.path || r.overlay_media_path || "");
                                  setSettings((s) => ({ ...s, thumbnail_path: p }));
                                  saveSettingsMut.mutate();
                                } catch (err) {
                                  console.error("thumbnail upload:", err);
                                }
                              }}
                            />
                          </label>
                          {settings.thumbnail_path && (
                            <button
                              type="button"
                              className="action-btn"
                              onClick={() => {
                                setSettings((s) => ({ ...s, thumbnail_path: "" }));
                                saveSettingsMut.mutate();
                              }}
                            >
                              Сбросить
                            </button>
                          )}
                        </div>
                        <div className="inline-note" style={{ marginTop: 4 }}>
                          PNG / JPG / WebP, 1280×720. Загружается в папку uploads/, применяется при заливе.
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* ── Одиночный рендер ── */}
                <div className="card">
                  <div className="card-header">
                    <span className="card-title">Одиночный рендер</span>
                    <span className="badge badge-neutral">1 видео</span>
                  </div>
                  <div className="card-body" style={{ paddingBottom: 16 }}>
                    <p style={{ fontSize: 12.5, color: "var(--text-secondary)", marginBottom: 14 }}>
                      Создаёт одну уникализированную версию ролика с текущими настройками.
                    </p>
                    <button
                      type="button"
                      className="btn-render btn-with-icon"
                      style={{ width: "100%" }}
                      disabled={!canRun || !canGoToRender || runMut.isPending}
                      onClick={() => runMut.mutate()}
                    >
                      <Play size={20} strokeWidth={2} aria-hidden />
                      {runMut.isPending ? "Ставим в очередь…" : "Запустить рендер"}
                    </button>
                    <div className="render-shortcut" style={{ marginTop: 8 }}>
                      <kbd className="uq-kbd">Ctrl</kbd>
                      <span className="uq-kbd-plus"> + </span>
                      <kbd className="uq-kbd">Enter</kbd>
                    </div>
                  </div>
                </div>

                {/* ── Пакетный рендер ── */}
                <div className="card" style={{ border: "1px solid rgba(54,214,232,0.25)", background: "rgba(54,214,232,0.03)" }}>
                  <div className="card-header" style={{ borderBottom: "1px solid rgba(54,214,232,0.15)" }}>
                    <span className="card-title" style={{ color: "var(--accent-cyan)" }}>Пакетный рендер</span>
                    <span className="badge badge-info">{variantsCount} видео из 1 исходника</span>
                  </div>
                  <div className="card-body" style={{ paddingBottom: 16 }}>
                    <p style={{ fontSize: 12.5, color: "var(--text-secondary)", marginBottom: 16 }}>
                      Из одного ролика создаётся <strong style={{ color: "var(--text-primary)" }}>{variantsCount} уникальных версий</strong> — каждая с разными эффектами, цветом, углами и метаданными.
                    </p>

                    {/* Счётчик количества */}
                    <div className="form-label" style={{ marginBottom: 8 }}>Количество роликов</div>
                    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
                      <button
                        type="button"
                        className="btn"
                        style={{ width: 36, height: 36, padding: 0, fontSize: 18, flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center" }}
                        onClick={() => setVariantsCount((n) => Math.max(1, n - 1))}
                      >−</button>
                      <input
                        className="form-input"
                        type="number"
                        min={1}
                        max={50}
                        value={variantsCount}
                        style={{ textAlign: "center", fontSize: 20, fontWeight: 700, height: 44 }}
                        onChange={(e) => setVariantsCount(Math.max(1, Math.min(50, Number(e.target.value || 1))))}
                      />
                      <button
                        type="button"
                        className="btn"
                        style={{ width: 36, height: 36, padding: 0, fontSize: 18, flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center" }}
                        onClick={() => setVariantsCount((n) => Math.min(50, n + 1))}
                      >+</button>
                    </div>

                    {/* Быстрые пресеты */}
                    <div style={{ display: "flex", gap: 6, marginBottom: 16, flexWrap: "wrap" }}>
                      {[5, 10, 20, 30, 50].map((n) => (
                        <button
                          key={n}
                          type="button"
                          className={`filter-chip${variantsCount === n ? " active" : ""}`}
                          onClick={() => setVariantsCount(n)}
                        >{n}</button>
                      ))}
                    </div>

                    {/* Опции рандомизации */}
                    <div style={{ display: "flex", flexDirection: "column", gap: 10, padding: "12px 14px", background: "var(--bg-elevated)", borderRadius: "var(--radius-md)", marginBottom: 16 }}>
                      <label className="settings-row" style={{ cursor: "pointer", margin: 0 }}>
                        <input type="checkbox" checked={randomizeEffects} onChange={(e) => setRandomizeEffects(e.target.checked)} />
                        <span style={{ fontSize: 13, color: "var(--text-secondary)", marginLeft: 8 }}>
                          Рандомные эффекты для каждого ролика
                          <span style={{ display: "block", fontSize: 11, color: "var(--text-tertiary)", marginTop: 1 }}>
                            mirror, noise, gamma, crop, скорость — разные у каждого
                          </span>
                        </span>
                      </label>
                      <label className="settings-row" style={{ cursor: "pointer", margin: 0 }}>
                        <input type="checkbox" checked={rotateTemplates} onChange={(e) => setRotateTemplates(e.target.checked)} />
                        <span style={{ fontSize: 13, color: "var(--text-secondary)", marginLeft: 8 }}>
                          Чередовать шаблоны монтажа
                          <span style={{ display: "block", fontSize: 11, color: "var(--text-tertiary)", marginTop: 1 }}>
                            default → reaction → news → story → ugc → …
                          </span>
                        </span>
                      </label>
                      <label className="settings-row" style={{ cursor: "pointer", margin: 0 }}>
                        <input type="checkbox" checked={randomizeDeviceGeo} onChange={(e) => setRandomizeDeviceGeo(e.target.checked)} />
                        <span style={{ fontSize: 13, color: "var(--text-secondary)", marginLeft: 8 }}>
                          Рандомные device / geo для каждого ролика
                          <span style={{ display: "block", fontSize: 11, color: "var(--text-tertiary)", marginTop: 1 }}>
                            каждая задача получит случайный отпечаток устройства и геолокацию
                          </span>
                        </span>
                      </label>
                    </div>

                    {/* Приоритет пакета */}
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
                      <span style={{ fontSize: 12, color: "var(--text-secondary)", whiteSpace: "nowrap" }}>Приоритет пакета:</span>
                      {[
                        { v: -1, label: "▼ Низкий" },
                        { v: 0, label: "— Обычный" },
                        { v: 1, label: "▲ Высокий" },
                      ].map(({ v, label }) => (
                        <button
                          key={v}
                          type="button"
                          className={`filter-chip${variantsPriority === v ? " active" : ""}`}
                          style={{ fontSize: 11 }}
                          onClick={() => setVariantsPriority(v)}
                        >{label}</button>
                      ))}
                    </div>

                    {/* Кнопка пакетного запуска */}
                    <button
                      type="button"
                      className="btn-render btn-with-icon"
                      style={{ width: "100%", background: "var(--accent-cyan)", fontSize: 15 }}
                      disabled={!canRun || !canGoToRender || variantsMut.isPending}
                      onClick={() => variantsMut.mutate()}
                    >
                      <Layers size={20} strokeWidth={2} aria-hidden />
                      {variantsMut.isPending
                        ? "Создаём задачи…"
                        : `Создать ${variantsCount} уникальных роликов`}
                    </button>

                    {/* Dry-run превью (первые 10 сек) */}
                    <button
                      type="button"
                      className="btn btn-with-icon"
                      style={{ width: "100%", marginTop: 8, fontSize: 13 }}
                      disabled={!videoPath.trim() || previewMut.isPending}
                      onClick={() => previewMut.mutate()}
                      title="Рендер только первых 10 секунд — быстрая проверка настроек без полного рендера"
                    >
                      <Play size={14} strokeWidth={2} aria-hidden />
                      {previewMut.isPending ? "Рендер превью…" : "Dry-run (10 сек превью)"}
                    </button>

                    {/* CTA на каждый ролик (раскрываемое) */}
                    <details style={{ marginTop: 12 }}>
                      <summary style={{ fontSize: 12, color: "var(--text-tertiary)", cursor: "pointer", userSelect: "none" }}>
                        Свой текст на каждый ролик (необязательно)
                      </summary>
                      <div style={{ marginTop: 8 }}>
                        <textarea
                          className="form-input"
                          rows={4}
                          style={{ resize: "vertical", fontFamily: "inherit", marginTop: 4 }}
                          placeholder={`Ровно ${variantsCount} строк — одна строка = один ролик`}
                          value={variantsSubtitlesText}
                          onChange={(e) => setVariantsSubtitlesText(e.target.value)}
                        />
                        <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginTop: 4 }}>
                          {variantsSubtitlesText.split(/\r?\n/).filter(Boolean).length} / {variantsCount} строк
                        </div>
                      </div>
                    </details>
                  </div>
                </div>

                {/* AI метаданные */}
                <div className="card">
                  <div className="card-header"><span className="card-title">AI-метаданные</span></div>
                  <div className="card-body" style={{ paddingBottom: 16 }}>
                    <div className="toolbar" style={{ marginBottom: aiMeta ? 12 : 0 }}>
                      <button type="button" className="btn btn-uq-ai btn-with-icon" disabled={aiPreviewMut.isPending} onClick={() => aiPreviewMut.mutate()}>
                        <WandSparkles size={ICON_SZ} strokeWidth={ICON_STROKE} aria-hidden />
                        {aiPreviewMut.isPending ? "Генерация…" : "Сгенерировать AI-текст"}
                      </button>
                      {aiMeta && (
                        <button type="button" className="btn" onClick={() => void fillSubtitleFromAi()}>
                          Подставить в «Текст на видео»
                        </button>
                      )}
                    </div>
                    {aiMeta && (
                      <div className="info-box uq-ai-meta-box">
                        <div><span className="mono uq-ai-meta-key">title:</span> {String(aiMeta.title ?? "-")}</div>
                        <div><span className="mono uq-ai-meta-key">description:</span> {String(aiMeta.description ?? "-")}</div>
                        {aiMeta.overlay_text != null && String(aiMeta.overlay_text).trim() ? (
                          <div><span className="mono uq-ai-meta-key">overlay_text:</span> {String(aiMeta.overlay_text)}</div>
                        ) : null}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>

          <div className="uniq-sidebar-panel">
            <div className={`uniq-preview-frame${videoPreviewSrc ? " uniq-preview-frame--video" : ""}`}>
              {videoPreviewSrc ? (
                <video
                  key={videoPreviewSrc}
                  className="uq-preview-video"
                  src={videoPreviewSrc}
                  controls
                  playsInline
                  preload="metadata"
                />
              ) : (
                <>
                  <div className="uq-preview-play" aria-hidden>
                    <Play size={22} strokeWidth={2} className="opacity-80" />
                  </div>
                  <div className="uq-preview-hint">Выберите или загрузите видео</div>
                </>
              )}
            </div>
            <div className="config-summary uq-sidebar-config">
              <div className="config-title">Конфигурация</div>
              <div className="config-row"><span className="config-row-key">Пресет</span><span className="config-row-value">{labelFor(presetOptions, settings.preset)}</span></div>
              <div className="config-row"><span className="config-row-key">Шаблон</span><span className="config-row-value">{labelFor(templateOptions, settings.template)}</span></div>
              <div className="config-row">
                <span className="config-row-key">Эффекты</span>
                <span className={`config-row-value${enabledEffectsCount > 0 ? " config-row-value--accent-purple" : ""}`}>
                  {enabledEffectsCount > 0 ? `${enabledEffectsCount} · рандом` : "—"}
                </span>
              </div>
              <div className="config-row">
                <span className="config-row-key">Оверлей</span>
                <span className={`config-row-value${overlayIsUserUpload ? " config-row-value--accent-cyan" : ""}`}>
                  {overlayIsUserUpload ? "Задан" : "По умолчанию"}
                </span>
              </div>
              <div className="config-row"><span className="config-row-key">Гео</span><span className="config-row-value">{geoLine}</span></div>
              <div className="config-row">
                <span className="config-row-key">Видео</span>
                <span className="config-row-value">{hasVideo ? filesWordRu(variantsCount) : "Нет"}</span>
              </div>
              {/* Protection bar */}
              <div style={{ marginTop: 12, borderTop: "1px solid var(--border-subtle)", paddingTop: 12 }}>
                <div className="hash-label">Защита от детекции</div>
                <div className="hash-meter">
                  <div className="hash-bar">
                    <div
                      className={`hash-bar-fill ${protectionScore >= 70 ? "good" : protectionScore >= 50 ? "warn" : "low"}`}
                      style={{ width: `${protectionScore}%` }}
                    />
                  </div>
                  <span className="hash-value" style={{ color: protectionScore >= 70 ? "var(--accent-green)" : protectionScore >= 50 ? "var(--accent-amber)" : "var(--accent-red)" }}>
                    {protectionScore}%
                  </span>
                </div>
                <div style={{ fontSize: 10, color: "var(--text-tertiary)", marginTop: 2 }}>
                  {protectionScore >= 70 ? "Высокий уровень уникализации" : protectionScore >= 50 ? "Средний уровень — увеличь intensity" : "Низкий — включи эффекты или intensity high"}
                </div>
              </div>
            </div>
            <div className="uq-sidebar-launch">
              <div className="dest-toggle uq-sidebar-dest">
                <button type="button" className={`dest-option ${renderOnly ? "active" : ""}`} onClick={() => setRenderOnly(true)}>
                  Скачать
                  <div className="dest-option-sub">Только рендер</div>
                </button>
                <button
                  type="button"
                  className={`dest-option ${!renderOnly ? "active" : ""}`}
                  disabled={profiles.length === 0}
                  onClick={() => setRenderOnly(false)}
                >
                  Антидетект
                  <div className="dest-option-sub">Рендер + залив</div>
                </button>
              </div>
              {!renderOnly && (
                <select className="form-select uq-sidebar-profile" value={targetProfile} onChange={(e) => setTargetProfile(e.target.value)}>
                  <option value="">— Профиль AdsPower —</option>
                  {profiles.map((id) => (
                    <option key={id} value={id}>
                      {id}
                    </option>
                  ))}
                </select>
              )}
              <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", fontSize: 12, color: "var(--text-secondary)", padding: "4px 0" }}>
                <input
                  type="checkbox"
                  checked={checkDuplicates}
                  onChange={(e) => setCheckDuplicates(e.target.checked)}
                  style={{ accentColor: "var(--accent-cyan)", width: 14, height: 14, cursor: "pointer" }}
                />
                Проверить дубли
              </label>
              <button type="button" className="btn-render btn-with-icon uq-sidebar-render" disabled={!canRun || !canGoToRender} onClick={() => runMut.mutate()}>
                <Play size={20} strokeWidth={2} aria-hidden />
                Запустить рендер
              </button>
            </div>
            <div className="uq-sidebar-foot">
              <span>
                {hasVideo ? variantsCount : 0} видео · {enabledEffectsCount} эффектов · hash-проверка
              </span>
              <span className="uq-sidebar-kbd">
                <kbd className="uq-kbd">Ctrl</kbd>
                <span className="uq-kbd-plus">+</span>
                <kbd className="uq-kbd">Enter</kbd>
              </span>
            </div>
          </div>
        </div>
      </div>

      {progressVisible && (
        <div className="progress-overlay show">
          <div className="progress-modal">
            <div className="progress-title">{String(progressQ.data?.title || "Обработка")}</div>
            <div className="progress-subtitle">{String(progressQ.data?.detail || "")}</div>
            <div className="progress-bar-bg"><div className="progress-bar-fill" style={{ width: `${Math.max(0, Math.min(100, progressPercent))}%` }} /></div>
            <div className="progress-stats">
              <div><div className="progress-stat-label">Прогресс</div><div className="progress-stat-value">{progressPercent.toFixed(1)}%</div></div>
              <div><div className="progress-stat-label">Скорость</div><div className="progress-stat-value">{Number(progressQ.data?.fps || 0).toFixed(0)} fps</div></div>
              <div><div className="progress-stat-label">Осталось</div><div className="progress-stat-value">{(() => { const eta = Number(progressQ.data?.eta_sec || 0); if (!eta || eta < 1) return "-"; const m = Math.floor(eta / 60); const s = Math.floor(eta % 60); return `${m}м ${s}с`; })()}</div></div>
              <div><div className="progress-stat-label">Очередь</div><div className="progress-stat-value">{Number(progressQ.data?.queue_done || 0)}/{Number(progressQ.data?.queue_total || 0)}</div></div>
            </div>
            {progressQ.data?.hash && (
              <div style={{ marginTop: 10, padding: "6px 10px", background: "rgba(94,234,212,0.07)", border: "1px solid rgba(94,234,212,0.2)", borderRadius: 6, fontSize: 11, display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ color: "var(--text-tertiary)" }}>Hash:</span>
                <span className="mono" style={{ color: "var(--accent-cyan)", letterSpacing: "0.04em" }}>{String(progressQ.data.hash)}</span>
              </div>
            )}
            <div className="progress-actions">
              <button
                type="button"
                className="btn"
                disabled={cancelMut.isPending || stopPipelineMut.isPending || restartQueueMut.isPending}
                onClick={() => {
                  if (progressTaskId > 0) {
                    cancelMut.mutate(progressTaskId);
                  } else {
                    stopPipelineMut.mutate();
                  }
                }}
              >
                {(cancelMut.isPending || stopPipelineMut.isPending || restartQueueMut.isPending)
                  ? "Отмена..."
                  : (progressTaskId > 0 ? "Отменить текущую" : "Остановить очередь")}
              </button>
              <button
                type="button"
                className="btn btn-cyan"
                disabled={cancelMut.isPending || stopPipelineMut.isPending || restartQueueMut.isPending}
                onClick={() => restartQueueMut.mutate()}
              >
                {restartQueueMut.isPending ? "Перезапуск..." : "Перезапустить очередь"}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
