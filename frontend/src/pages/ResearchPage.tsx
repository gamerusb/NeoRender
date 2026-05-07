import React, { useState, useMemo, useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BellRing,
  Check,
  ChevronDown,
  Clock,
  Coins,
  Copy,
  Dice5,
  Download,
  ExternalLink,
  Eye,
  FileDown,
  Gamepad2,
  Globe,
  Heart,
  Layers,
  MessageCircle,
  Save,
  Search,
  Sparkles,
  TrendingUp,
  Users,
  Zap,
} from "lucide-react";
import { apiFetch, apiUrl, type ApiJson } from "@/api";
import { uiIconProps } from "@/components/icons/uiIconProps";
import { useTenant } from "@/tenant/TenantContext";

const R12 = uiIconProps(13);
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
  ubt_niche?: string;
  ubt_marker?: boolean;
  ubt_masking_hits?: string[];
  ubt_shorteners?: string[];
  risk_tier?: "low" | "medium" | "high";
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

/**
 * Stealth UBT категории (2026).
 * Арбитражники не называют игры в заголовке — YouTube банит.
 * Ищем по поведенческим паттернам: реакция/секрет/приложение/мультипликатор.
 */
const ARB_GAMES = [
  { key: "money_reaction",   label: "Шок-реакция",     color: "#10B981" },
  { key: "secret_method",    label: "Секретный метод",  color: "#8B5CF6" },
  { key: "new_app",          label: "Новое приложение", color: "#3B82F6" },
  { key: "multiplier",       label: "Мультипликатор",   color: "#EF4444" },
  { key: "lifestyle",        label: "Пассивный доход",  color: "#F59E0B" },
  { key: "urgency",          label: "Срочность",        color: "#F97316" },
  { key: "withdrawal_proof", label: "Вывод / Скрин",    color: "#06B6D4" },
  { key: "phone_screen",     label: "Экран телефона",   color: "#EC4899" },
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
  { value: "KR", label: "🇰🇷 KR" },
  { value: "TH", label: "🇹🇭 TH" },
  { value: "MY", label: "🇲🇾 MY" },
  { value: "JP", label: "🇯🇵 JP" },
  { value: "ID", label: "🇮🇩 ID" },
  { value: "US", label: "🇺🇸 US" },
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

const SIMPLE_PRESETS = [
  { label: "Gambling",    hint: "Casino wins · KR",  query: "casino win reaction shorts",                region: "KR", period: 2, icon: Dice5,      accent: "#EF4444" },
  { label: "Nutra",       hint: "Weight loss · US",  query: "weight loss before after shorts",           region: "US", period: 7, icon: Zap,         accent: "#10B981" },
  { label: "Dating",      hint: "Hook clips · US",   query: "dating app reaction hook shorts",           region: "US", period: 7, icon: Heart,       accent: "#F472B6" },
  { label: "Crypto",      hint: "Profit · US",       query: "crypto profit reaction shorts",             region: "US", period: 7, icon: TrendingUp,  accent: "#F59E0B" },
  { label: "InOut Games", hint: "Chicken Road · KR", query: "Chicken Road #chickenroad #inout #shorts",  region: "KR", period: 2, icon: Gamepad2,    accent: "#5EEAD4" },
  { label: "Korea SEA",   hint: "Viral · KR",        query: "korean viral shorts big win",               region: "KR", period: 1, icon: Globe,       accent: "#8B5CF6" },
] as const;

/** Быстрые запросы в духе generate_search_seeds() (бэкенд) — для холодного UBT Shorts */
const UBT_PARSER_CHIPS: { label: string; query: string }[] = [
  { label: "#баг", query: "#баг shorts" },
  { label: "#темка", query: "#темка #shorts" },
  { label: "#заработок", query: "#заработок shorts" },
  { label: "#проверка", query: "#проверка #shorts" },
  { label: "#честно", query: "#честно shorts" },
  { label: "#реакция", query: "#реакция #shorts" },
  { label: "темка", query: "темка шортс" },
  { label: "проверка баг", query: "проверка баг shorts" },
];

type PresetTag = { label: string; value: string };
type PresetGroup = {
  label: string;
  color: string;
  source: "youtube";
  region: "KR" | "TH" | "MY" | "JP" | "ID" | "US" | "RU" | "VN";
  period: number;
  note: string;
  presets: PresetTag[];
};

/**
 * STEALTH PRESET GROUPS — 2026
 *
 * Источник: форумы по УБТ-арбитражу (cpaduck, trafficcardinal, affmoment,
 * afftimes). Явные слова "казино / casino / big win" = мгновенный бан.
 *
 * Как реально маскируют в 2026:
 *  • Промокод в кадре — никаких ссылок, код вшит визуально в видео
 *  • Стримерская нарезка — split-screen: реакция стримера + игра, без названия
 *  • Нейтральный аккаунт — мотивация/факты, гемблинг-контент вкраплён среди них
 *  • Форматы с интригой — "Попробовал — не поверил", "Начал с 1000₽"
 *  • Тактики/прогнозы — "Эта тактика работает 3 из 5", "Почему боятся"
 */
const PRESET_GROUPS: PresetGroup[] = [
  // ── РУССКОЯЗЫЧНЫЙ РЫНОК ──────────────────────────────────────────────────
  {
    label: "RU · Стримеры",
    color: "#F23F5D",
    source: "youtube",
    region: "RU",
    period: 2,
    note: "Топ-формат 2026: split-screen реакция стримера без слова казино",
    presets: [
      { label: "Реакция стримера выигрыш", value: "реакция стримера большой выигрыш шортс" },
      { label: "Стример не ожидал", value: "стример не ожидал такого шортс" },
      { label: "Нарезка стримера деньги", value: "нарезка стримера деньги шортс" },
      { label: "Стример в шоке", value: "стример в шоке от суммы шортс" },
      { label: "Стример не поверил", value: "стример не поверил сколько заработал шортс" },
      { label: "Реакция на результат", value: "реакция на результат стрима деньги шортс" },
    ],
  },
  {
    label: "RU · Промокод",
    color: "#F59E0B",
    source: "youtube",
    region: "RU",
    period: 2,
    note: "Промокод вшит в кадр — никаких ссылок, бан обходится полностью",
    presets: [
      { label: "Промокод в видео бонус", value: "промокод бонус в видео шортс" },
      { label: "Бонус в кадре", value: "бонус в кадре получи шортс" },
      { label: "Промо в видео заработок", value: "промо код заработок видео шортс" },
      { label: "Введи промокод", value: "введи промокод и получи шортс" },
      { label: "Секретный код бонус", value: "секретный код бонус шортс" },
    ],
  },
  {
    label: "RU · Тактика",
    color: "#8B5CF6",
    source: "youtube",
    region: "RU",
    period: 7,
    note: "Интрига без вертикали: тактики, схемы, лайфхаки — форум-паттерны",
    presets: [
      { label: "Тактика работает 3 из 5", value: "эта тактика работает 3 из 5 раз шортс" },
      { label: "Вот почему этого боятся", value: "вот почему этого боятся шортс" },
      { label: "Схема которую скрывают", value: "схема которую скрывают шортс" },
      { label: "Лайфхак который работает", value: "лайфхак который реально работает шортс" },
      { label: "Метод который скрывают", value: "метод который от тебя скрывают шортс" },
      { label: "Почему не показывают", value: "почему не показывают по телевизору шортс" },
    ],
  },
  {
    label: "RU · История",
    color: "#10B981",
    source: "youtube",
    region: "RU",
    period: 7,
    note: "Микроистории: «начал с 1000₽», нейтральный аккаунт-лайфстайл",
    presets: [
      { label: "Начал с 1000 рублей", value: "начал с 1000 рублей история шортс" },
      { label: "Изменил жизнь за месяц", value: "изменил жизнь за месяц деньги шортс" },
      { label: "Мой доход сегодня", value: "мой доход сегодня покажу шортс" },
      { label: "Вывел деньги скрин", value: "вывел деньги скрин шортс" },
      { label: "Не верил пока не увидел", value: "не верил пока сам не увидел шортс" },
      { label: "Успей пока не удалили", value: "успей пока не закрыли шортс" },
    ],
  },
  // ── КОРЕЯ ────────────────────────────────────────────────────────────────
  {
    label: "KR · Вывод",
    color: "#06B6D4",
    source: "youtube",
    region: "KR",
    period: 2,
    note: "Доказательство вывода + тест приложения без называния игры",
    presets: [
      { label: "실제 출금 인증", value: "실제 출금 인증 쇼츠" },
      { label: "앱 수익 인증", value: "앱 수익 인증 shorts" },
      { label: "비밀 앱 수익", value: "비밀 어플 수익 인증 쇼츠" },
      { label: "새로운 앱 테스트", value: "새로운 앱 테스트 수익 쇼츠" },
      { label: "스트리머 반응 수익", value: "스트리머 반응 수익 쇼츠" },
      { label: "챌린지 수익 인증", value: "챌린지 수익 인증 쇼츠" },
    ],
  },
  {
    label: "KR · Реакция",
    color: "#FBBF24",
    source: "youtube",
    region: "KR",
    period: 1,
    note: "Шок-реакция на деньги — вирусный KR-формат без слова казино",
    presets: [
      { label: "당첨 반응 실시간", value: "당첨 반응 실시간 쇼츠" },
      { label: "충격 수익 순간", value: "충격 순간 수익 쇼츠" },
      { label: "실화냐 수익", value: "실화냐 수익 인증 쇼츠" },
      { label: "처음 해봤는데 대박", value: "처음 해봤는데 대박 shorts" },
      { label: "진짜 되네 방법", value: "진짜 되네 돈버는 방법 쇼츠" },
    ],
  },
  // ── ЮГО-ВОСТОЧНАЯ АЗИЯ ───────────────────────────────────────────────────
  {
    label: "TH · Маскировка",
    color: "#A78BFA",
    source: "youtube",
    region: "TH",
    period: 2,
    note: "Таиланд: приложение + вывод + лайфхак без слова азартная игра",
    presets: [
      { label: "แอพหาเงิน ได้จริง", value: "แอพหาเงิน ได้จริง shorts" },
      { label: "ถอนเงินได้จริง", value: "ถอนเงินได้จริง ทดสอบ shorts" },
      { label: "วิธีทำเงิน ลับ", value: "วิธีทำเงินออนไลน์ ลับ shorts" },
      { label: "สตรีมเมอร์ ได้เงิน", value: "สตรีมเมอร์ ได้เงิน ตกใจ shorts" },
      { label: "สูตรลับ ได้จริง", value: "สูตรลับ หาเงิน ได้จริง shorts" },
    ],
  },
  {
    label: "ID · Cuan",
    color: "#3B82F6",
    source: "youtube",
    region: "ID",
    period: 2,
    note: "Индонезия: cuan (доход), букти (доказательство), без casino",
    presets: [
      { label: "Aplikasi cuan terbukti", value: "aplikasi penghasil uang terbukti shorts" },
      { label: "Withdraw langsung bukti", value: "withdraw langsung terbukti shorts" },
      { label: "Rahasia cuan app", value: "rahasia cuan aplikasi terbaru shorts" },
      { label: "Bukti transfer nyata", value: "bukti transfer nyata aplikasi shorts" },
      { label: "Streamer reaksi menang", value: "streamer reaksi menang banyak shorts" },
    ],
  },
  // ── ЗАПАД ─────────────────────────────────────────────────────────────────
  {
    label: "JP · 副業",
    color: "#EC4899",
    source: "youtube",
    region: "JP",
    period: 7,
    note: "Япония: 副業 (побочный доход) + 検証 (верификация) без ギャンブル",
    presets: [
      { label: "副業アプリ 稼げる検証", value: "副業アプリ 稼げる 検証 shorts" },
      { label: "本当に稼げる 実績", value: "本当に稼げる アプリ 実績 shorts" },
      { label: "副業 バレない方法", value: "副業 バレない 稼ぐ方法 shorts" },
      { label: "アプリ 収益 検証", value: "新しいアプリ 収益 検証 shorts" },
    ],
  },
  {
    label: "US · Proof",
    color: "#F97316",
    source: "youtube",
    region: "US",
    period: 7,
    note: "США: app proof + streamer reaction — без gambling слов",
    presets: [
      { label: "App actually pays", value: "this app actually pays you shorts" },
      { label: "Promo code in video", value: "promo code bonus in video shorts" },
      { label: "Streamer reaction win", value: "streamer reaction big win shorts" },
      { label: "Passive income proof", value: "passive income app proof shorts" },
      { label: "Tactic that works", value: "this tactic works every time shorts" },
      { label: "Paid me to play", value: "paid me to play game withdraw proof shorts" },
    ],
  },
  {
    label: "INOUT · Games",
    color: "#5EEAD4",
    source: "youtube",
    region: "US",
    period: 7,
    note: "Официальные названия игр InOut для мониторинга Shorts/UGC: названия + прямые хэштеги без обходных формулировок",
    presets: [
      { label: "Chicken Road", value: "Chicken Road #chickenroad #inout #inoutgames #shorts" },
      { label: "Chicken Road 2", value: "Chicken Road 2 #chickenroad2 #chickenroad #inout #shorts" },
      { label: "Mine Slot", value: "Mine Slot #mineslot #inoutgames #slot #shorts" },
      { label: "Aviafly 2", value: "Aviafly 2 #aviafly2 #aviafly #inoutgames #shorts" },
      { label: "Hamster Run", value: "Hamster Run #hamsterrun #inoutgames #crashgame #shorts" },
      { label: "Aztec Plinko", value: "Aztec Plinko #aztecplinko #plinko #inoutgames #shorts" },
      { label: "Penalty Unlimited", value: "Penalty Unlimited #penaltyunlimited #inoutgames #shorts" },
      { label: "Forest Arrow", value: "Forest Arrow #forestarrow #inoutgames #shorts" },
      { label: "Twist", value: "Twist #twist #inoutgames #shorts" },
      { label: "Chicken Coin", value: "Chicken Coin #chickencoin #inoutgames #shorts" },
      { label: "Chicken Banana", value: "Chicken Banana #chickenbanana #inoutgames #shorts" },
      { label: "Chicken Shoot", value: "Chicken Shoot #chickenshoot #inoutgames #shorts" },
      { label: "Chicken Royal", value: "Chicken Royal #chickenroyal #inoutgames #shorts" },
      { label: "Rabbit Road", value: "Rabbit Road #rabbitroad #inoutgames #shorts" },
      { label: "Squid Gambler", value: "Squid Gambler #squidgambler #inoutgames #shorts" },
      { label: "Joker Poker", value: "Joker Poker #jokerpoker #inoutgames #shorts" },
    ],
  },
  {
    label: "YT · UBT Signals",
    color: "#A78BFA",
    source: "youtube",
    region: "US",
    period: 7,
    note: "Поисковые сигналы из публичных разборов Shorts: эмоции, вывод, промо, тактика, app proof. Для поиска чужого UGC, не для генерации креативов.",
    presets: [
      { label: "Streamer reaction", value: "streamer reaction win #shorts" },
      { label: "Big win reaction", value: "big win reaction #shorts" },
      { label: "App proof", value: "app actually pays proof #shorts" },
      { label: "Withdraw proof", value: "withdraw proof app #shorts" },
      { label: "Promo in video", value: "promo code in video bonus #shorts" },
      { label: "New tactic", value: "new tactic works #shorts" },
      { label: "Game community", value: "game community new method #shorts" },
      { label: "Forecast app", value: "forecast app proof #shorts" },
      { label: "Started with 100", value: "started with 100 result #shorts" },
      { label: "Paid to play", value: "paid me to play withdraw proof #shorts" },
    ],
  },
  {
    label: "INOUT · UBT Signals",
    color: "#F472B6",
    source: "youtube",
    region: "US",
    period: 7,
    note: "Комбинации INOUT game-name + поисковые сигналы, чтобы находить Shorts, где игру могут подавать через реакцию, proof или промо.",
    presets: [
      { label: "Chicken Road reaction", value: "Chicken Road reaction #chickenroad #shorts" },
      { label: "Chicken Road proof", value: "Chicken Road withdraw proof #chickenroad #shorts" },
      { label: "Chicken Road promo", value: "Chicken Road promo code #chickenroad #shorts" },
      { label: "Chicken Road 2 win", value: "Chicken Road 2 big win #chickenroad2 #shorts" },
      { label: "Mine Slot reaction", value: "Mine Slot reaction #mineslot #shorts" },
      { label: "Aviafly cashout", value: "Aviafly cashout #aviafly #shorts" },
      { label: "Hamster Run win", value: "Hamster Run win #hamsterrun #shorts" },
      { label: "Aztec Plinko drop", value: "Aztec Plinko drop #aztecplinko #shorts" },
      { label: "Penalty Unlimited goal", value: "Penalty Unlimited goal #penaltyunlimited #shorts" },
      { label: "Rabbit Road proof", value: "Rabbit Road proof #rabbitroad #shorts" },
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
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{ flex: 1, height: 5, background: "var(--bg-elevated)", borderRadius: 3, overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color, borderRadius: 3, transition: "width 0.4s ease" }} />
      </div>
      <span className="mono" style={{ minWidth: 38, fontSize: 10, color: "var(--text-tertiary)", textAlign: "right" }}>
        {pct.toFixed(0)}%
      </span>
    </div>
  );
}

function ResearchSkeletonGrid() {
  return (
    <div className="research-skeleton-list" aria-hidden>
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="research-skeleton-row">
          <div className="research-skeleton-check shimmer" />
          <div className="research-skeleton-thumb-sm shimmer" />
          <div className="research-skeleton-body">
            <div className="research-skeleton-line shimmer" style={{ width: `${55 + (i * 7) % 30}%` }} />
            <div className="research-skeleton-line shimmer" style={{ width: "35%", height: 8 }} />
            <div className="research-skeleton-chips">
              <span className="research-skeleton-chip shimmer" />
              <span className="research-skeleton-chip shimmer" />
              <span className="research-skeleton-chip shimmer" style={{ width: 40 }} />
            </div>
          </div>
          <div className="research-skeleton-actions">
            <span className="research-skeleton-chip shimmer" style={{ width: 28, height: 28 }} />
            <span className="research-skeleton-chip shimmer" style={{ width: 28, height: 28 }} />
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
  // showFilters removed — filters are always visible now

  // Batch select
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [batchLoading, setBatchLoading] = useState(false);

  // Presets
  const [activeGroup, setActiveGroup] = useState<string | null>(null);
  const [savedPresets, setSavedPresets] = useState<SavedPreset[]>(loadSavedPresets);
  const [showSavePreset, setShowSavePreset] = useState(false);
  const [newPresetName, setNewPresetName] = useState("");

  // Tabs
  const [activeTab, setActiveTab] = useState<"search" | "arb" | "queue">("search");

  /** Парсер: комбинированные UBT-сид + только свежие по дате загрузки (см. NEORENDER_SEARCH_RECENT_HOURS на бэке) */
  const [parserUbtSeeds, setParserUbtSeeds] = useState(true);
  const [parserFresh48h, setParserFresh48h] = useState(false);

  // Search history
  const [searchHistory, setSearchHistory] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem("research_history") || "[]"); } catch { return []; }
  });

  function pushHistory(q: string) {
    if (!q.trim()) return;
    setSearchHistory((prev) => {
      const next = [q, ...prev.filter((x) => x !== q)].slice(0, 10);
      localStorage.setItem("research_history", JSON.stringify(next));
      return next;
    });
  }

  // Viral copy generator
  const [hookPattern, setHookPattern] = useState<"auto"|"curiosity"|"number"|"interrupt">("auto");
  const [viralResult, setViralResult] = useState<{
    title: string; description: string; comment: string; overlay_text: string;
    title_variants?: {title: string; hook_type: string; ctr_score: number}[];
    used_fallback?: boolean;
  } | null>(null);
  const [copiedVariant, setCopiedVariant] = useState<string | null>(null);

  const viralMut = useMutation({
    mutationFn: () => apiFetch<ApiJson>("/api/ai/preview", {
      method: "POST", tenantId,
      body: JSON.stringify({
        niche: niche.trim() || "YouTube Shorts",
        hook_pattern: hookPattern,
        n_variants: 5,
        competitor_examples: results.slice(0, 8).map((v) => ({ title: v.title, view_count: v.view_count })),
      }),
    }),
    onSuccess: (d) => {
      if (d.status === "ok") setViralResult(d as typeof viralResult);
      else showToast(String(d.message || "Ошибка AI"), "err");
    },
    onError: (e: Error) => showToast(e.message, "err"),
  });

  // Trending audio
  const [trendingAudio, setTrendingAudio] = useState<{track: string; artist: string; count: number; example_views: number}[] | null>(null);
  const audioMut = useMutation({
    mutationFn: () => apiFetch<ApiJson>("/api/research/trending-audio", {
      method: "POST", tenantId,
      body: JSON.stringify({ niche: niche.trim() || "YouTube Shorts", top_n: 20, region }),
    }),
    onSuccess: (d) => {
      if (d.status === "ok") setTrendingAudio((d.trending as typeof trendingAudio) ?? []);
      else showToast("Trending audio: " + String(d.message || "ошибка"), "err");
    },
    onError: (e: Error) => showToast(e.message, "err"),
  });

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
    if (arbExpandedGame && keys.includes(arbExpandedGame as (typeof keys)[number])) return arbExpandedGame;
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
          limit: 20,
          region: override?.region ?? region,
          use_ubt_seeds: parserUbtSeeds,
          shorts_only: true,
          fetch_multiplier: 4,
          recent_max_hours: parserFresh48h ? Math.min(48, period * 24) : 0,
        }),
      }),
    onSuccess: (data, vars) => {
      setResults((data.results as VideoResult[]) ?? []);
      setSelected(new Set());
      const q = (vars?.niche ?? niche).trim();
      if (q) pushHistory(q);
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
        body: JSON.stringify({
          mode: "stealth",
          period_days: arbScanPeriod,
          limit_per_query: 4,
        }),
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

  function exportCsv(videos: VideoResult[]) {
    if (!videos.length) return;
    const cols = ["id", "title", "channel", "view_count", "like_count", "comment_count", "duration", "upload_date", "url", "arb_score", "ubt_niche", "region", "source"] as const;
    const header = cols.join(",");
    const rows = videos.map((v) =>
      cols.map((k) => {
        const val = v[k as keyof VideoResult] ?? "";
        const str = String(val).replace(/"/g, '""');
        return str.includes(",") || str.includes('"') || str.includes("\n") ? `"${str}"` : str;
      }).join(",")
    );
    const csv = [header, ...rows].join("\n");
    const blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `research_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    showToast(`Экспортировано ${videos.length} видео`, "ok");
  }

  function copyVideoUrl(url: string) {
    navigator.clipboard.writeText(url).then(() => showToast("Ссылка скопирована", "ok")).catch(() => showToast("Не удалось скопировать", "err"));
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

      {/* ── Top navigation: tabs + live stats ── */}
      <div className="research-topnav">
        {/* Tab nav */}
        <div className="research-tab-nav">
          {([
            { key: "search", label: "Поиск контента", badge: results.length > 0 ? results.length : null },
            { key: "arb",    label: "Арбитраж-скан",  badge: arbScanResults ? Object.values(arbScanResults).reduce((s, v) => s + v.length, 0) : null },
            { key: "queue",  label: "Очередь",         badge: queueCount > 0 ? queueCount : null },
          ] as const).map(({ key, label, badge }) => (
            <button key={key} type="button" onClick={() => setActiveTab(key)}
              className={`research-tab-btn${activeTab === key ? " active" : ""}`}>
              {label}
              {badge !== null && (
                <span className={`research-tab-badge${activeTab === key ? " active" : ""}`}>{badge}</span>
              )}
            </button>
          ))}
        </div>

        {/* Live stats */}
        <div className="research-stats-row">
          {[
            { label: "Найдено",  value: results.length || "—", accent: true },
            { label: "Показано", value: filteredSorted.length, accent: false, hide: results.length === filteredSorted.length || results.length === 0 },
            { label: "Очередь",  value: queueCount, accent: false },
            { label: "Сегодня",  value: downloadedToday, green: true },
          ].filter((s) => !s.hide).map((s) => (
            <div key={s.label} className="research-stat-pill">
              <span className="research-stat-label">{s.label}</span>
              <span className="research-stat-value" style={{
                color: s.green ? "var(--accent-green)" : s.accent ? "var(--accent-cyan)" : "var(--text-primary)",
              }}>{s.value}</span>
            </div>
          ))}
          <span className="research-context-hint">
            {REGIONS.find(r => r.value === region)?.label ?? region} · {period}д
          </span>
        </div>
      </div>

      {/* ── Search command center ── */}
      <div className="search-cmd-card parser-spot-card">
        <header className="parser-spot-head">
          <div className="parser-spot-head-text">
            <span className="parser-spot-kicker">Парсер Shorts</span>
            <h2 className="parser-spot-h1">Контент-ресёрч</h2>
            <p className="parser-spot-desc">
              Поведенческие и теговые запросы без «названия игры». Включите UBT-сид — поиск уйдёт в широкие Shorts-комбо;
              «≤48 ч» отсекает старые заливки по дате загрузки.
            </p>
          </div>
          <ol className="parser-spot-steps" aria-label="Шаги">
            <li><span>1</span> Запрос</li>
            <li><span>2</span> Регион / период</li>
            <li><span>3</span> Результаты</li>
          </ol>
        </header>

        {/* Zone 1: main query */}
        <div className="search-cmd-query">
          <div className="search-cmd-input-wrap">
            <Search size={16} style={{ color: "var(--text-tertiary)", flexShrink: 0 }} aria-hidden />
            <input
              className="search-cmd-input"
              aria-label="Ниша или ключевые слова для поиска Shorts"
              placeholder={
                parserUbtSeeds
                  ? "Ниша опционально — пустое поле + «Найти» = только UBT-сид запросы"
                  : "Ниша или тема — например: korean streamer reaction shorts"
              }
              value={niche}
              onChange={(e) => setNiche(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (niche.trim() || parserUbtSeeds)) searchMut.mutate(undefined);
              }}
            />
            {niche.trim() && !showSavePreset && (
              <button type="button" className="search-cmd-icon-btn"
                onClick={() => setShowSavePreset(true)} title="Сохранить как пресет">
                <Save size={14} aria-hidden />
              </button>
            )}
          </div>
          <button
            type="button"
            className="search-cmd-btn"
            disabled={(!niche.trim() && !parserUbtSeeds) || searchMut.isPending}
            onClick={() => searchMut.mutate(undefined)}
          >
            {searchMut.isPending
              ? <><span className="spinner-sm" />Поиск…</>
              : <><Search size={14} aria-hidden />Найти</>}
          </button>
        </div>

        <div className="simple-preset-grid" aria-label="Fast niche presets">
          {SIMPLE_PRESETS.map((preset) => {
            const Icon = preset.icon;
            const isActive = niche === preset.query;
            return (
              <button
                key={preset.label}
                type="button"
                className={`simple-preset-card${isActive ? " active" : ""}`}
                style={{ "--preset-accent": preset.accent } as React.CSSProperties}
                onClick={() => applyPreset(preset.query, { niche: preset.query, source, period: preset.period, region: preset.region, name: preset.label, id: preset.label }, true)}
              >
                <span className="simple-preset-icon">
                  <Icon size={34} strokeWidth={2.25} aria-hidden />
                </span>
                <span className="simple-preset-copy">
                  <span className="simple-preset-label">{preset.label}</span>
                  <span className="simple-preset-hint">{preset.hint}</span>
                </span>
              </button>
            );
          })}
        </div>

        <div className="parser-tools-row" role="toolbar" aria-label="Режим парсера">
          <button
            type="button"
            className={`parser-tool-pill${parserUbtSeeds ? " on" : ""}`}
            onClick={() => setParserUbtSeeds((v) => !v)}
            title="Добавляет комбинированные Shorts-запросы (#темка, #баг…) к yt-dlp, как на бэкенде"
          >
            <Sparkles size={14} aria-hidden />
            UBT-сид
          </button>
          <button
            type="button"
            className={`parser-tool-pill${parserFresh48h ? " on" : ""}`}
            onClick={() => setParserFresh48h((v) => !v)}
            title="Оставить только ролики с известной датой загрузки не старше 48 часов"
          >
            <Clock size={14} aria-hidden />
            ≤48 ч
          </button>
        </div>

        <div className="parser-chip-strip" aria-label="Быстрые UBT-запросы">
          <span className="parser-chip-strip-label">Быстро</span>
          <div className="parser-chip-scroll">
            {UBT_PARSER_CHIPS.map((c) => (
              <button
                key={c.query}
                type="button"
                className="parser-ubt-chip"
                onClick={() => {
                  setNiche(c.query);
                  void searchMut.mutate({ niche: c.query });
                }}
              >
                {c.label}
              </button>
            ))}
          </div>
        </div>

        {/* Save preset inline */}
        {showSavePreset && (
          <div className="search-cmd-save-row">
            <input className="form-input" placeholder="Название пресета…" value={newPresetName}
              onChange={(e) => setNewPresetName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") savePreset(); if (e.key === "Escape") setShowSavePreset(false); }}
              style={{ flex: 1 }} autoFocus />
            <button type="button" className="btn-v3 btn-v3-sm btn-v3-primary" onClick={savePreset}
              disabled={!newPresetName.trim()}>Сохранить</button>
            <button type="button" className="btn-v3 btn-v3-sm btn-v3-ghost" onClick={() => setShowSavePreset(false)}>Отмена</button>
          </div>
        )}

        {/* Recent searches */}
        {searchHistory.length > 0 && (
          <div className="search-history-row">
            <span className="search-history-label">Недавние:</span>
            {searchHistory.slice(0, 7).map((q) => (
              <button key={q} type="button" className="search-history-chip"
                onClick={() => applyPreset(q, undefined, true)}>
                {q}
              </button>
            ))}
            <button type="button" className="search-history-clear"
              onClick={() => { setSearchHistory([]); localStorage.removeItem("research_history"); }}>
              очистить
            </button>
          </div>
        )}

        {/* Zone 2: params */}
        <div className="search-cmd-params">
          {/* Source */}
          <div className="search-cmd-seg-wrap">
            <span className="search-cmd-seg-label">Источник</span>
            <div className="search-seg-group">
              {SOURCES.map((s) => (
                <div key={s.value} title={!s.available ? "Скоро — прямой парсинг в разработке" : ""}>
                  <button type="button" onClick={() => s.available && setSource(s.value)}
                    className={`search-seg-btn${source === s.value ? " active" : ""}${!s.available ? " disabled" : ""}`}>
                    {s.label}
                    {!s.available && <span className="search-seg-soon">soon</span>}
                  </button>
                </div>
              ))}
            </div>
          </div>
          <div className="search-cmd-seg-wrap">
            <span className="search-cmd-seg-label">Период</span>
            <SegControl options={PERIODS} value={period} onChange={setPeriod} />
          </div>
          <div className="search-cmd-seg-wrap">
            <span className="search-cmd-seg-label">Регион</span>
            <SegControl options={REGIONS} value={region} onChange={setRegion} small />
          </div>
        </div>

        {/* Zone 3: sort + filters (contextual — shown when results exist) */}
        {results.length > 0 && (
          <div className="search-cmd-filters">
            <div className="search-cmd-filter-group">
              <span className="search-cmd-seg-label">Сортировка</span>
              <SegControl options={SORT_OPTIONS} value={sortBy} onChange={setSortBy} small />
            </div>
            <div className="search-cmd-filter-group">
              <span className="search-cmd-seg-label">Длина</span>
              <SegControl options={DURATION_FILTERS} value={durationFilter} onChange={setDurationFilter} small />
            </div>
            <div className="search-cmd-filter-group">
              <span className="search-cmd-seg-label">Просмотры</span>
              <SegControl options={VIEWS_FILTERS} value={viewsFilter} onChange={setViewsFilter} small />
            </div>
          </div>
        )}
      </div>

      {/* ── Search tab ── */}
      {activeTab === "search" && (<>

      {/* ── Preset niche tags (сворачиваемый блок — меньше шума при повторных сессиях) ── */}
      <details className="parser-presets-fold" open>
        <summary className="parser-presets-summary">
          <Layers size={15} aria-hidden />
          <span className="parser-presets-summary-title">Пресеты ниш и рынки</span>
          <ChevronDown size={16} className="parser-presets-chevron" aria-hidden />
          <span className="parser-presets-summary-meta">RU · KR · TH · сохранённые</span>
        </summary>
      <div className="card parser-presets-card">
        <div className="card-header" style={{ paddingBottom: 10 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flex: 1, minWidth: 0 }}>
            <span className="card-title">Пресеты ниш</span>
            {activeGroup !== "__saved" && currentGroup && (
              <div style={{ display: "flex", gap: 5 }}>
                <span className="preset-meta-chip">{REGIONS.find(r => r.value === currentGroup.region)?.label ?? currentGroup.region}</span>
                <span className="preset-meta-chip">{currentGroup.period}д</span>
              </div>
            )}
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexShrink: 0 }}>
            {activeGroup !== "__saved" && currentGroup && (
              <button type="button" className="btn-v3 btn-v3-sm btn-v3-ghost"
                onClick={() => {
                  setSource(currentGroup.source);
                  setRegion(currentGroup.region);
                  setPeriod(currentGroup.period);
                  showToast(`Профиль ${currentGroup.region} · ${currentGroup.period}д применён`, "ok");
                }}
                style={{ fontSize: 10.5, padding: "4px 10px" }}>
                ↳ Применить профиль
              </button>
            )}
            <span style={{ fontSize: 10.5, color: "var(--text-disabled)" }}>Shift = только вставить</span>
          </div>
        </div>

        {/* Category pills - horizontal scroll */}
        <div className="preset-cat-scroll">
          {savedPresets.length > 0 && (
            <button type="button"
              className={`preset-cat-pill${activeGroup === "__saved" ? " active-saved" : ""}`}
              onClick={() => setActiveGroup("__saved")}>
              ⭐ Мои
              <span className="preset-cat-count">{savedPresets.length}</span>
            </button>
          )}
          {PRESET_GROUPS.map((group) => {
            const isSel = currentGroup?.label === group.label && activeGroup !== "__saved";
            return (
              <button type="button" key={group.label}
                className={`preset-cat-pill${isSel ? " active" : ""}`}
                style={{ borderColor: isSel ? `${group.color}55` : undefined, color: isSel ? group.color : undefined }}
                onClick={() => setActiveGroup(group.label)}>
                {group.label}
                <span className="preset-cat-count" style={{ background: isSel ? `${group.color}25` : undefined, color: isSel ? group.color : undefined }}>
                  {group.presets.length}
                </span>
              </button>
            );
          })}
        </div>

        {/* Group note bar */}
        {activeGroup !== "__saved" && currentGroup?.note && (
          <div className="preset-note-bar" style={{ borderLeftColor: currentGroup.color }}>
            {currentGroup.note}
          </div>
        )}

        {/* Flat tag chips */}
        <div className="preset-tags-flat">
          {activeGroup === "__saved"
            ? savedPresets.map((p) => (
                <div key={p.id} style={{ display: "inline-flex", alignItems: "center", gap: 0 }}>
                  <button type="button"
                    className={`preset-flat-tag${niche === p.niche ? " active" : ""}`}
                    style={{ borderRadius: "20px 0 0 20px", borderColor: niche === p.niche ? "var(--accent-cyan)" : undefined }}
                    onClick={() => applyPreset(p.niche, p)}>
                    {p.name}
                    <span style={{ marginLeft: 5, fontSize: 9, opacity: 0.6, fontFamily: "var(--font-mono)" }}>{p.region}·{p.period}д</span>
                  </button>
                  <button type="button" className="preset-flat-delete"
                    style={{ borderRadius: "0 20px 20px 0", borderColor: niche === p.niche ? "var(--accent-cyan)" : undefined }}
                    onClick={() => deletePreset(p.id)}>✕</button>
                </div>
              ))
            : (currentGroup?.presets ?? []).map((p) => {
                const isActive = niche === p.value;
                const opts = { source: currentGroup?.source, region: currentGroup?.region, period: currentGroup?.period };
                return (
                  <button type="button" key={p.value}
                    className={`preset-flat-tag${isActive ? " active" : ""}`}
                    style={{ borderColor: isActive ? (currentGroup?.color ?? "var(--accent-cyan)") : undefined,
                             background: isActive ? `${currentGroup?.color ?? "var(--accent-cyan)"}15` : undefined,
                             color: isActive ? (currentGroup?.color ?? "var(--accent-cyan)") : undefined }}
                    title={p.value}
                    onClick={(e) => applyPreset(p.value, opts, !e.shiftKey)}>
                    {p.label}
                  </button>
                );
              })
          }
        </div>
      </div>
      </details>

      </>)}

      {/* ── Arbitrage tab ── */}
      {activeTab === "arb" && (
      <div className="card arb-scan-card">
        <div className="card-header arb-scan-card-header">
          <div className="arb-scan-header-top">
            <span className="card-title arb-scan-title">
              <span className="arb-scan-title-icon" aria-hidden>⚡</span>
              Арбитраж скан
              <span className="arb-scan-beta">BETA</span>
            </span>
            <span className="arb-scan-legend">
              Шок-реакция · Секретный метод · Новое приложение · Мультипликатор · Пассивный доход · Срочность · Вывод/Скрин · Экран телефона
            </span>
          </div>
          <p className="arb-scan-desc">
            Поиск по <b>поведенческим паттернам</b> — арбитражники не пишут названия игр в заголовке (YouTube банит).
            Ищем «реакцию на деньги», «секретный метод», «новое приложение» — без упоминания казино.
            UBT Score = пустое описание + профиль-CTA + мультипликатор + emoji-плотность + view/sub аномалия.
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
              <div className="arb-scan-placeholder-icon" aria-hidden>⚡</div>
              <div className="arb-scan-placeholder-title">Готов к сканированию</div>
              <p className="arb-scan-placeholder-text">
                8 поведенческих категорий · ~130 запросов на языках RU/EN/KO/TH/VI<br />
                UBT Score = пустое описание + profile-CTA + мультипликатор + view/sub аномалия + velocity
              </p>
              <button type="button" className="btn-v3 btn-v3-primary"
                style={{ marginTop: 12, alignSelf: "center" }}
                disabled={arbScanMut.isPending}
                onClick={() => arbScanMut.mutate(undefined)}>
                {arbScanMut.isPending ? <><span className="spinner-sm" />Сканирую…</> : <><Search size={14} />Запустить скан</>}
              </button>
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
                        Нет Shorts по этой категории за период — попробуйте окно 30д или другую категорию.
                      </div>
                    ) : (
                      <div className="arb-video-list">
                        <div className="arb-video-list-head">
                          <span>Видео</span>
                          <span>Метрики</span>
                          <span style={{ display: "flex", alignItems: "center", gap: 8, justifyContent: "flex-end" }}>
                            Действия
                            <button type="button" className="btn-v3 btn-v3-ghost" style={{ fontSize: 10, padding: "2px 8px", gap: 4 }}
                              onClick={() => exportCsv(videos)} title="Экспорт в CSV">
                              <FileDown size={11} />CSV
                            </button>
                          </span>
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
                                    <span className={`arb-meta-chip arb-er-chip ${(video.arb_score ?? 0) >= 75 ? "arb-er-high" : (video.arb_score ?? 0) >= 50 ? "arb-er-mid" : ""}`}>
                                      UBT {video.arb_score}
                                    </span>
                                  )}
                                  {video.ubt_marker && (
                                    <span className="arb-meta-chip arb-er-chip arb-er-high" title="Высокая вероятность маскировки">⚡ MASK</span>
                                  )}
                                  {video.ubt_niche && (
                                    <span className="arb-meta-chip" style={{ textTransform: "uppercase", fontSize: 9, letterSpacing: "0.04em", opacity: 0.85 }}>
                                      {video.ubt_niche}
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
                                      ER {er.toFixed(0)}%
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
      )}

      {/* ── Search results (search tab) ── */}
      {activeTab === "search" && (<>

      {/* ── Results header with batch controls ── */}
      {filteredSorted.length > 0 && (
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
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
              {batchLoading ? <><span className="spinner-sm" />Загрузка…</> : <><Download size={12} />Скачать выбранные ({selected.size})</>}
            </button>
          )}
          <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
            <span style={{ fontSize: 11, color: "var(--text-tertiary)" }}>
              {filteredSorted.length} из {results.length} видео
            </span>
            <button type="button" className="btn-v3 btn-v3-sm btn-v3-ghost"
              onClick={() => exportCsv(filteredSorted)}
              title="Экспорт в CSV"
              style={{ gap: 5, fontSize: 11 }}>
              <FileDown size={13} />
              CSV
            </button>
          </div>
        </div>
      )}

      {/* ── Results grid ── */}
      {results.length === 0 ? (
        <div className="card">
          {searchMut.isPending
            ? <ResearchSkeletonGrid />
            : (
              <div style={{ padding: "56px 24px", textAlign: "center", display: "flex", flexDirection: "column", alignItems: "center", gap: 14 }}>
                <div style={{ position: "relative", marginBottom: 4 }}>
                  <div style={{
                    width: 60, height: 60, borderRadius: 16,
                    background: "linear-gradient(135deg, rgba(94,234,212,0.12), rgba(94,234,212,0.04))",
                    border: "1px solid rgba(94,234,212,0.2)",
                    display: "flex", alignItems: "center", justifyContent: "center",
                    boxShadow: "0 0 24px rgba(94,234,212,0.1)",
                  }}>
                    <Search size={24} style={{ color: "var(--accent-cyan)", opacity: 0.7 }} aria-hidden />
                  </div>
                  <div style={{
                    position: "absolute", inset: -8, borderRadius: 24,
                    border: "1px solid rgba(94,234,212,0.08)",
                  }} />
                </div>
                <div style={{ fontSize: 15, fontWeight: 700, color: "var(--text-primary)", letterSpacing: "-0.2px" }}>Найдите трендовые Shorts</div>
                <div style={{ fontSize: 12.5, color: "var(--text-tertiary)", maxWidth: 380, lineHeight: 1.65 }}>
                  Включите <b style={{ color: "var(--text-secondary)" }}>UBT-сид</b> и жмите «Найти» с пустым полем — уйдём в широкие теговые комбо;
                  чипы ниже вставляют готовые запросы. Пресеты рынков — в сворачиваемом блоке.
                </div>
                <div style={{ display: "flex", gap: 7, marginTop: 2, flexWrap: "wrap", justifyContent: "center" }}>
                  {["#темка shorts", "реакция стримера выигрыш", "실제 출금 인증"].map((q) => (
                    <button key={q} type="button" className="search-history-chip"
                      onClick={() => applyPreset(q, undefined, true)}>
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            )}
        </div>
      ) : filteredSorted.length === 0 ? (
        <div className="card" style={{ padding: "32px 24px", textAlign: "center", color: "var(--text-tertiary)", fontSize: 13 }}>
          Нет видео по выбранным фильтрам — попробуйте изменить условия
        </div>
      ) : (
        <div className="vid-list">
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
            const ubtScore = video.arb_score ?? 0;
            const ubtHigh = ubtScore >= 75;
            const ubtMid = ubtScore >= 50;
            const accentColor = ubtHigh ? "#F23F5D" : ubtMid ? "#FBBF24" : hot?.label === "HOT" ? "#F23F5D" : hot?.label === "NEW" ? "#FBBF24" : isSelected ? "var(--accent-cyan)" : advice ? "rgba(94,234,212,0.3)" : "transparent";

            return (
              <div key={video.id}
                className={`vid-item${isSelected ? " vid-item-selected" : ""}${adviceOpen ? " vid-item-open" : ""}`}
                style={{ "--vid-accent": accentColor } as React.CSSProperties}>

                <div className="vid-row">
                  {/* Checkbox */}
                  <button type="button" className="vid-row-check-btn"
                    onClick={() => toggleSelect(video.id)}
                    aria-label={isSelected ? "Снять выбор" : "Выбрать"}>
                    <div className={`vid-row-check${isSelected ? " checked" : ""}`}>
                      {isSelected && <Check size={10} strokeWidth={3.5} color="#0a0a0b" aria-hidden />}
                    </div>
                  </button>

                  {/* Thumbnail — portrait strip */}
                  <div
                    className="vid-row-thumb" style={{ background: gradient }}
                    title="Открыть в YouTube">
                    {video.thumbnail && (
                      <img src={video.thumbnail} alt="" className="vid-row-img"
                        onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }} />
                    )}
                    <div className="vid-row-thumb-shade" />
                    {hot && (
                      <span className={`vid-row-hot${hot.label === "HOT" ? " hot-badge-pulse" : ""}`}
                        style={{ background: hot.bg }}>{hot.label}</span>
                    )}
                    {video.duration > 0 && (
                      <span className="vid-row-dur">{formatDuration(video.duration)}</span>
                    )}
                    {ubtScore > 0 && (
                      <span className="vid-row-ubt"
                        style={{ background: ubtHigh ? "rgba(242,63,93,0.92)" : ubtMid ? "rgba(245,158,11,0.92)" : "rgba(0,0,0,0.72)" }}>
                        {ubtScore}
                      </span>
                    )}
                    {video.ubt_marker && !ubtScore && (
                      <span className="vid-row-ubt" style={{ background: "rgba(242,63,93,0.85)" }}>⚡</span>
                    )}
                    <button
                      type="button"
                      className={`video-download-overlay ${hasDownloadError ? "error" : isDownloaded ? "done" : isQueued || isDownloading ? "busy" : ""}`}
                      disabled={isQueued || isDownloading}
                      onClick={() => downloadMut.mutate(video)}
                    >
                      {hasDownloadError ? "Retry" : isDownloaded ? "Done" : isQueued || isDownloading ? "Loading" : "Download"}
                    </button>
                  </div>

                  {/* Body */}
                  <div className="vid-row-body">
                    <a href={video.url} target="_blank" rel="noreferrer" className="vid-row-title">
                      {video.title || "Без названия"}
                    </a>
                    <div className="vid-row-meta">
                      {video.channel_url ? (
                        <a href={video.channel_url} target="_blank" rel="noreferrer" className="vid-row-channel">
                          {video.channel || "Channel"}
                        </a>
                      ) : (
                        <span className="vid-row-channel vid-row-channel-dim">{video.channel || "Channel"}</span>
                      )}
                      {video.upload_date && <span className="vid-row-time">· {timeAgo(video.upload_date)}</span>}
                      {video.region && (
                        <span className="vid-row-region">{REGIONS.find(r => r.value === video.region)?.label ?? video.region}</span>
                      )}
                    </div>
                    <div className="vid-row-chips">
                      <span className="vid-metric-chip vid-metric-chip-views">
                        <Eye {...R12} aria-hidden />{formatNum(video.view_count)}
                      </span>
                      {(video.like_count ?? 0) > 0 && (
                        <span className="vid-metric-chip vid-metric-chip-likes">
                          <Heart {...R12} aria-hidden />{formatNum(video.like_count ?? 0)}
                        </span>
                      )}
                      {(video.comment_count ?? 0) > 0 && (
                        <span className="vid-metric-chip vid-metric-chip-comments">
                          <MessageCircle {...R12} aria-hidden />{formatNum(video.comment_count ?? 0)}
                        </span>
                      )}
                      {er > 0 && (
                        <span className={`vid-metric-chip ${er >= 5 ? "vid-metric-chip-er-hot" : er >= 2 ? "vid-metric-chip-er-warm" : "vid-metric-chip-er-cold"}`}>
                          ER {er.toFixed(1)}%
                        </span>
                      )}
                      {video.ubt_marker && (
                        <span className="vid-mask-chip">⚡ MASK</span>
                      )}
                      <span className="vid-src-tag" style={video.source === "youtube" ? { background: "rgba(255,0,0,0.12)", color: "#FF5555", borderColor: "rgba(255,0,0,0.2)" } : {}}>
                        {sourceLabel(video.source)}
                      </span>
                    </div>
                  </div>

                  {/* Score ring — only when score exists */}
                  {ubtScore > 0 && (
                    <div className="vid-row-score-col">
                      <ScoreRing score={ubtScore} risk={video.risk_tier ?? "low"} />
                    </div>
                  )}

                  {/* Actions */}
                  <div className="vid-row-actions">
                    <button type="button"
                      className={`btn-v3 btn-v3-sm vid-action-btn ${hasDownloadError ? "btn-v3-danger" : isDownloaded ? "btn-v3-success" : isQueued || isDownloading ? "btn-v3-primary" : "btn-v3-ghost"}`}
                      disabled={isQueued || isDownloading}
                      onClick={() => downloadMut.mutate(video)}
                      title={hasDownloadError ? "Ошибка — повторить" : isDownloaded ? "Скачано" : "Скачать"}>
                      {hasDownloadError ? "⚠" : isDownloaded ? <Check size={12} /> : isQueued ? "⏳" : isDownloading ? "⬇" : <Download size={12} />}
                    </button>
                    <button type="button"
                      className={`btn-v3 btn-v3-sm vid-action-btn ${advice ? "btn-v3-primary" : "btn-v3-ghost"}`}
                      disabled={isGettingAdvice}
                      onClick={() => {
                        if (advice && adviceOpen) setAdviceOpenId(null);
                        else if (advice) setAdviceOpenId(video.id);
                        else adviceMut.mutate(video);
                      }}
                      title="AI анализ">
                      {isGettingAdvice ? <span className="spinner-sm" /> : advice ? (adviceOpen ? "▲" : String(advice.score)) : "AI"}
                    </button>
                    <button type="button" className="btn-v3 btn-v3-sm btn-v3-ghost vid-action-btn"
                      onClick={() => copyVideoUrl(video.url)} title="Копировать ссылку">
                      <Copy size={12} />
                    </button>
                    <a href={video.url} target="_blank" rel="noreferrer"
                      className="btn-v3 btn-v3-sm btn-v3-ghost vid-action-btn"
                      title="Открыть в YouTube">
                      <ExternalLink size={12} />
                    </a>
                  </div>
                </div>

                {hasDownloadError && (
                  <div className="vid-row-error">{downloadErrors[video.id]}</div>
                )}

                {advice && adviceOpen && (
                  <div className="vid-advice-wrap">
                    <AdvicePanel advice={advice} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* ── Viral Copy Generator ── */}
      <div className="card" style={{ marginTop: 12 }}>
        <div className="card-header">
          <span className="card-title">Viral Copy Generator</span>
          <span style={{ fontSize: 11, color: "var(--accent-cyan)", background: "rgba(94,234,212,0.08)", padding: "2px 7px", borderRadius: 4 }}>
            AI · конкурентный промпт
          </span>
        </div>
        <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {/* Hook selector */}
          <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
            <span style={{ fontSize: 11.5, color: "var(--text-tertiary)", marginRight: 2 }}>Hook:</span>
            {(["auto","curiosity","number","interrupt"] as const).map((h) => (
              <button key={h} type="button" onClick={() => setHookPattern(h)}
                style={{
                  fontSize: 11, padding: "3px 9px", borderRadius: 5, cursor: "pointer",
                  border: `1px solid ${hookPattern === h ? "rgba(94,234,212,0.5)" : "var(--border-default)"}`,
                  background: hookPattern === h ? "rgba(94,234,212,0.08)" : "transparent",
                  color: hookPattern === h ? "var(--accent-cyan)" : "var(--text-tertiary)",
                  transition: "all 0.15s",
                }}>
                {h === "auto" ? "Auto" : h === "curiosity" ? "Curiosity gap" : h === "number" ? "Number hook" : "Pattern interrupt"}
              </button>
            ))}
            <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
              <button type="button" className="btn-v3 btn-v3-sm btn-v3-ghost"
                disabled={audioMut.isPending}
                onClick={() => audioMut.mutate()}
                style={{ fontSize: 11 }}>
                {audioMut.isPending ? "…" : "🎵 Trending audio"}
              </button>
              <button type="button" className="btn-v3 btn-v3-sm btn-v3-primary"
                disabled={viralMut.isPending}
                onClick={() => viralMut.mutate()}
                style={{ fontSize: 11 }}>
                {viralMut.isPending ? "Генерирую…" : results.length > 0 ? `✦ Генерировать (${Math.min(results.length,8)} примеров)` : "✦ Генерировать"}
              </button>
            </div>
          </div>

          {/* Trending audio results */}
          {trendingAudio !== null && (
            <div style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 7, padding: "8px 12px" }}>
              <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginBottom: 6 }}>Трендовые звуки в нише (последние 14 дней)</div>
              {trendingAudio.length === 0 ? (
                <div style={{ fontSize: 11.5, color: "var(--text-muted)" }}>Трек-метаданные не найдены. Попробуй другую нишу или дождись yt-dlp.</div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {trendingAudio.map((t, i) => (
                    <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12 }}>
                      <span style={{ color: "var(--accent-cyan)", fontWeight: 700, width: 16 }}>#{i+1}</span>
                      <span style={{ color: "var(--text-primary)", fontWeight: 600 }}>{t.track}</span>
                      {t.artist && <span style={{ color: "var(--text-tertiary)" }}>· {t.artist}</span>}
                      <span style={{ marginLeft: "auto", color: "var(--text-muted)", fontSize: 11 }}>
                        {t.count}× · {t.example_views >= 1000000 ? `${(t.example_views/1000000).toFixed(1)}M` : `${Math.round(t.example_views/1000)}K`} views
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Title variants */}
          {viralResult && (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {(viralResult.title_variants ?? [{ title: viralResult.title, hook_type: "auto", ctr_score: 70 }]).map((v, i) => (
                <div key={i} style={{
                  display: "flex", alignItems: "center", gap: 8,
                  padding: "7px 10px", borderRadius: 7,
                  background: i === 0 ? "rgba(94,234,212,0.06)" : "rgba(255,255,255,0.02)",
                  border: `1px solid ${i === 0 ? "rgba(94,234,212,0.2)" : "rgba(255,255,255,0.06)"}`,
                }}>
                  <span style={{ fontSize: 10, fontWeight: 700, color: i === 0 ? "var(--accent-cyan)" : "var(--text-muted)", width: 18, flexShrink: 0 }}>
                    {i === 0 ? "★" : `#${i+1}`}
                  </span>
                  <span style={{ flex: 1, fontSize: 12.5, color: "var(--text-primary)", lineHeight: 1.4 }}>{v.title}</span>
                  <span style={{ fontSize: 10, color: "var(--text-tertiary)", background: "rgba(255,255,255,0.05)", padding: "1px 6px", borderRadius: 4, flexShrink: 0 }}>
                    {v.hook_type}
                  </span>
                  <span style={{ fontSize: 10.5, fontWeight: 700, color: v.ctr_score >= 85 ? "var(--accent-green)" : v.ctr_score >= 70 ? "var(--accent-amber)" : "var(--text-tertiary)", flexShrink: 0 }}>
                    {v.ctr_score}
                  </span>
                  <button type="button" onClick={() => { navigator.clipboard.writeText(v.title); setCopiedVariant(v.title); setTimeout(() => setCopiedVariant(null), 1500); }}
                    style={{ background: "none", border: "none", cursor: "pointer", color: copiedVariant === v.title ? "var(--accent-cyan)" : "var(--text-muted)", padding: "2px 4px", flexShrink: 0 }}>
                    {copiedVariant === v.title ? <Check size={13} /> : <Copy size={13} />}
                  </button>
                </div>
              ))}
              {/* Description + Comment */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginTop: 4 }}>
                {[
                  { label: "Описание", value: viralResult.description },
                  { label: "Закреплённый комментарий", value: viralResult.comment },
                ].map(({ label, value }) => (
                  <div key={label} style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 6, padding: "8px 10px" }}>
                    <div style={{ fontSize: 10, color: "var(--text-tertiary)", marginBottom: 4 }}>{label}</div>
                    <div style={{ fontSize: 11.5, color: "var(--text-secondary)", lineHeight: 1.5 }}>{value}</div>
                    <button type="button" onClick={() => navigator.clipboard.writeText(value)}
                      style={{ marginTop: 6, fontSize: 10.5, color: "var(--text-muted)", background: "none", border: "none", cursor: "pointer", padding: 0 }}>
                      копировать
                    </button>
                  </div>
                ))}
              </div>
              {viralResult.used_fallback && (
                <div style={{ fontSize: 10.5, color: "var(--accent-amber)" }}>⚠ Использован fallback (нет ключа Groq или ошибка API)</div>
              )}
            </div>
          )}
        </div>
      </div>

      </>)}

      {/* ── Queue tab ── */}
      {activeTab === "queue" && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">Очередь скачанных файлов</span>
            <span style={{ fontSize: 11, color: "var(--text-tertiary)" }}>{queueCount} файл(ов) · {downloadedToday} сегодня</span>
          </div>
          <div className="card-body" style={{ padding: "0 0 8px" }}>
            {queuedFiles.length === 0 ? (
              <div style={{ padding: "40px 24px", textAlign: "center", color: "var(--text-tertiary)", fontSize: 13 }}>
                Очередь пуста — скачайте видео на вкладке Поиск или Арбитраж-скан
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column" }}>
                {queuedFiles.map((f, i) => (
                  <div key={f.filename} className="queue-file-row" style={{
                    borderBottom: i < queuedFiles.length - 1 ? "1px solid var(--border-subtle)" : "none",
                  }}>
                    <div style={{
                      width: 32, height: 32, borderRadius: 8, flexShrink: 0,
                      background: "rgba(94,234,212,0.08)", border: "1px solid rgba(94,234,212,0.15)",
                      display: "flex", alignItems: "center", justifyContent: "center",
                    }}>
                      <FileDown size={14} style={{ color: "var(--accent-cyan)" }} aria-hidden />
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 12, fontWeight: 500, color: "var(--text-primary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {f.filename}
                      </div>
                      <div style={{ fontSize: 10, color: "var(--text-tertiary)", marginTop: 2, display: "flex", gap: 8 }}>
                        <span style={{ color: "var(--accent-green)", fontFamily: "var(--font-mono)", fontWeight: 600 }}>{f.size_mb.toFixed(1)} MB</span>
                        <span>·</span>
                        <span>{new Date(f.modified * 1000).toLocaleString("ru-RU")}</span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;600;700&family=IBM+Plex+Mono:wght@400;500;600;700&family=Syne:wght@600;700;800&display=swap');

        /* ── Spinner ── */
        .spinner-sm {
          display: inline-block; width: 11px; height: 11px;
          border: 2px solid rgba(255,255,255,0.2); border-top-color: var(--accent-cyan);
          border-radius: 50%; animation: spin 0.65s linear infinite; flex-shrink: 0;
        }

        /* ── Top navigation ── */
        .research-topnav {
          display: flex; align-items: center; gap: 16px;
          padding-bottom: 0;
          border-bottom: 1px solid var(--border-subtle);
          margin-bottom: 16px;
        }
        .research-tab-nav { display: flex; gap: 0; }
        .research-tab-btn {
          display: inline-flex; align-items: center; gap: 6px;
          padding: 9px 18px 13px;
          border: none; background: transparent;
          color: var(--text-disabled); font-size: 12px; font-weight: 700;
          cursor: pointer; position: relative;
          transition: color .15s; font-family: 'Rajdhani', var(--font-sans); border-radius: 0;
          letter-spacing: 0.5px; text-transform: uppercase;
        }
        .research-tab-btn:hover { color: var(--text-secondary); }
        .research-tab-btn.active {
          color: var(--accent-cyan);
        }
        .research-tab-btn.active::after {
          content: ''; position: absolute; bottom: -1px; left: 8px; right: 8px;
          height: 2px;
          background: linear-gradient(90deg, transparent, var(--accent-cyan) 20%, var(--accent-cyan) 80%, transparent);
          border-radius: 1px 1px 0 0;
          box-shadow: 0 0 10px rgba(94,234,212,0.6);
        }
        .research-tab-badge {
          display: inline-flex; align-items: center; justify-content: center;
          min-width: 16px; height: 15px; padding: 0 4px;
          border-radius: 4px; font-size: 9px; font-weight: 700;
          font-family: 'IBM Plex Mono', var(--font-mono);
          background: rgba(255,255,255,0.05);
          color: var(--text-disabled);
          transition: all .15s; letter-spacing: 0;
        }
        .research-tab-badge.active {
          background: rgba(94,234,212,0.12);
          color: var(--accent-cyan);
          box-shadow: 0 0 6px rgba(94,234,212,0.15);
        }
        .research-stats-row {
          display: flex; gap: 5px; align-items: center;
          margin-left: auto; flex-wrap: wrap;
        }
        .research-stat-pill {
          display: flex; align-items: center; gap: 4px;
          padding: 3px 10px; border-radius: 4px;
          background: var(--bg-elevated); border: 1px solid var(--border-subtle);
          font-size: 11px;
        }
        .research-stat-label { color: var(--text-disabled); font-size: 9.5px; text-transform: uppercase; letter-spacing: 0.5px; }
        .research-stat-value { font-weight: 700; font-family: 'IBM Plex Mono', var(--font-mono); color: var(--text-primary); }
        .research-context-hint {
          font-size: 10px; color: var(--text-disabled);
          padding: 3px 8px;
          background: var(--bg-elevated);
          border: 1px solid var(--border-subtle);
          border-radius: 4px;
          font-family: 'IBM Plex Mono', var(--font-mono);
        }

        /* ── Parser spotlight (контент-ресёрч) ── */
        .parser-spot-card { border-radius: 12px; }
        .parser-spot-head {
          display: grid;
          grid-template-columns: 1fr auto;
          gap: 16px 20px;
          padding: 16px 18px 14px;
          border-bottom: 1px solid var(--border-subtle);
          background: linear-gradient(165deg, rgba(94,234,212,0.06) 0%, transparent 55%);
        }
        @media (max-width: 720px) {
          .parser-spot-head { grid-template-columns: 1fr; }
        }
        .parser-spot-kicker {
          display: inline-block;
          font-size: 9px; font-weight: 800; letter-spacing: 0.14em;
          text-transform: uppercase;
          color: rgba(94,234,212,0.85);
          font-family: 'IBM Plex Mono', var(--font-mono);
          margin-bottom: 4px;
        }
        .parser-spot-h1 {
          margin: 0 0 8px;
          font-size: 1.35rem;
          font-weight: 800;
          letter-spacing: -0.03em;
          font-family: 'Rajdhani', var(--font-sans);
          color: var(--text-primary);
        }
        .parser-spot-desc {
          margin: 0;
          font-size: 12px;
          line-height: 1.55;
          color: var(--text-secondary);
          max-width: 52ch;
        }
        .parser-spot-steps {
          margin: 0; padding: 0;
          list-style: none;
          display: flex; flex-direction: column; gap: 6px;
          align-self: center;
          font-size: 10px; font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.06em;
          color: var(--text-disabled);
          font-family: 'IBM Plex Mono', var(--font-mono);
        }
        .parser-spot-steps li {
          display: flex; align-items: center; gap: 8px;
          white-space: nowrap;
        }
        .parser-spot-steps span {
          display: inline-flex; align-items: center; justify-content: center;
          width: 20px; height: 20px; border-radius: 6px;
          background: rgba(94,234,212,0.12);
          border: 1px solid rgba(94,234,212,0.35);
          color: var(--accent-cyan);
          font-size: 11px;
        }
        .parser-tools-row {
          display: flex; flex-wrap: wrap; gap: 8px;
          padding: 8px 16px 4px;
          border-bottom: 1px solid var(--border-subtle);
          background: rgba(0,0,0,0.12);
        }
        .parser-tool-pill {
          display: inline-flex; align-items: center; gap: 6px;
          padding: 5px 12px;
          border-radius: 999px;
          border: 1px solid var(--border-subtle);
          background: var(--bg-elevated);
          color: var(--text-tertiary);
          font-size: 11px; font-weight: 600;
          cursor: pointer;
          transition: border-color .15s, color .15s, background .15s, box-shadow .15s;
          font-family: var(--font-sans);
        }
        .parser-tool-pill:hover {
          border-color: rgba(94,234,212,0.35);
          color: var(--text-secondary);
        }
        .parser-tool-pill.on {
          border-color: rgba(94,234,212,0.55);
          background: rgba(94,234,212,0.1);
          color: var(--accent-cyan);
          box-shadow: 0 0 12px rgba(94,234,212,0.12);
        }
        .parser-chip-strip {
          display: flex; align-items: center; gap: 10px;
          padding: 8px 16px 10px;
          border-bottom: 1px solid var(--border-subtle);
          background: rgba(94,234,212,0.02);
        }
        .parser-chip-strip-label {
          flex-shrink: 0;
          font-size: 9px; font-weight: 800;
          letter-spacing: 0.1em;
          text-transform: uppercase;
          color: var(--text-disabled);
          font-family: 'IBM Plex Mono', var(--font-mono);
        }
        .parser-chip-scroll {
          display: flex; flex-wrap: wrap; gap: 6px;
          min-width: 0;
        }
        .parser-ubt-chip {
          padding: 4px 10px;
          border-radius: 999px;
          border: 1px dashed rgba(94,234,212,0.35);
          background: rgba(0,0,0,0.2);
          color: var(--text-secondary);
          font-size: 11px;
          font-family: 'IBM Plex Mono', var(--font-mono);
          cursor: pointer;
          transition: all .12s;
        }
        .parser-ubt-chip:hover {
          border-style: solid;
          border-color: rgba(94,234,212,0.6);
          color: var(--accent-cyan);
          background: rgba(94,234,212,0.08);
        }
        .parser-presets-fold {
          border: 1px solid var(--border-subtle);
          border-radius: 12px;
          overflow: hidden;
          background: var(--bg-surface);
        }
        .parser-presets-summary {
          display: flex; align-items: center; gap: 10px;
          padding: 12px 16px;
          cursor: pointer;
          list-style: none;
          font-size: 12px; font-weight: 700;
          color: var(--text-secondary);
          font-family: 'Rajdhani', var(--font-sans);
          letter-spacing: 0.04em;
          text-transform: uppercase;
          user-select: none;
        }
        .parser-presets-summary::-webkit-details-marker { display: none; }
        .parser-presets-summary-title { flex: 1; }
        .parser-presets-summary-meta {
          font-size: 10px; font-weight: 600;
          color: var(--text-disabled);
          text-transform: none;
          letter-spacing: 0;
          font-family: 'IBM Plex Mono', var(--font-mono);
        }
        .parser-presets-chevron {
          color: var(--text-tertiary);
          transition: transform .2s ease;
        }
        .parser-presets-fold[open] .parser-presets-chevron {
          transform: rotate(180deg);
        }
        .parser-presets-card {
          border: none;
          border-radius: 0;
          border-top: 1px solid var(--border-subtle);
        }

        /* ── Search command card ── */
        .search-cmd-card {
          background: var(--bg-surface);
          border: 1px solid var(--border-default);
          border-radius: 8px;
          overflow: hidden;
          box-shadow: 0 2px 12px rgba(0,0,0,0.35);
          position: relative;
        }
        .search-cmd-card::before {
          content: '';
          position: absolute; top: 0; left: 0; right: 0; height: 1px;
          background: linear-gradient(90deg, transparent 0%, rgba(94,234,212,0.25) 25%, rgba(94,234,212,0.5) 50%, rgba(94,234,212,0.25) 75%, transparent 100%);
          z-index: 1;
        }
        .search-cmd-query {
          display: flex; align-items: center; gap: 10px;
          padding: 12px 16px;
          background: linear-gradient(180deg, rgba(255,255,255,0.025), transparent);
          border-bottom: 1px solid var(--border-subtle);
        }
        .search-cmd-input-wrap {
          flex: 1; display: flex; align-items: center; gap: 10px;
          background: var(--bg-deep);
          border: 1px solid var(--border-default);
          border-radius: 6px; padding: 0 14px;
          transition: border-color .18s, box-shadow .18s;
        }
        .search-cmd-input-wrap::before {
          content: '›'; color: rgba(94,234,212,0.5); font-size: 20px; line-height: 1;
          font-family: monospace; margin-right: -2px; flex-shrink: 0;
        }
        .search-cmd-input-wrap:focus-within {
          border-color: rgba(94,234,212,0.5);
          box-shadow: 0 0 0 3px rgba(94,234,212,0.08), inset 0 1px 0 rgba(94,234,212,0.04);
        }
        .search-cmd-input-wrap:focus-within::before { color: rgba(94,234,212,0.9); }
        .search-cmd-input {
          flex: 1; background: transparent; border: none; outline: none;
          color: var(--text-primary); font-family: 'IBM Plex Mono', var(--font-mono);
          font-size: 13px; font-weight: 400; padding: 11px 0;
          letter-spacing: 0;
        }
        .search-cmd-input::placeholder { color: var(--text-disabled); font-weight: 400; }
        .search-cmd-icon-btn {
          display: flex; align-items: center; justify-content: center;
          width: 27px; height: 27px; border-radius: 5px;
          border: 1px solid var(--border-subtle); background: var(--bg-elevated);
          color: var(--text-tertiary); cursor: pointer; transition: all .15s; flex-shrink: 0;
        }
        .search-cmd-icon-btn:hover { background: var(--bg-hover); color: var(--text-primary); }
        .search-cmd-btn {
          display: inline-flex; align-items: center; gap: 7px;
          padding: 9px 22px; border-radius: 6px;
          background: rgba(94,234,212,0.12);
          border: 1px solid rgba(94,234,212,0.4);
          color: var(--accent-cyan); font-family: 'Rajdhani', var(--font-sans);
          font-size: 13px; font-weight: 700; cursor: pointer;
          transition: all .18s; white-space: nowrap; flex-shrink: 0;
          letter-spacing: 0.5px; text-transform: uppercase;
          box-shadow: 0 0 0 0 rgba(94,234,212,0);
        }
        .search-cmd-btn:hover {
          background: rgba(94,234,212,0.2);
          border-color: rgba(94,234,212,0.65);
          box-shadow: 0 0 16px rgba(94,234,212,0.2);
          transform: translateY(-1px);
        }
        .search-cmd-btn:disabled {
          opacity: 0.35; pointer-events: none; transform: none; box-shadow: none;
        }
        .search-cmd-save-row {
          display: flex; gap: 7px; align-items: center;
          padding: 8px 14px; border-bottom: 1px solid var(--border-subtle);
          background: rgba(255,255,255,0.01);
        }
        .search-history-row {
          display: flex; gap: 5px; flex-wrap: wrap; align-items: center;
          padding: 6px 14px; border-bottom: 1px solid var(--border-subtle);
          background: rgba(94,234,212,0.015);
        }
        .search-history-label {
          font-size: 9px; font-weight: 700; text-transform: uppercase;
          letter-spacing: 0.8px; color: var(--text-disabled); white-space: nowrap;
          font-family: 'IBM Plex Mono', var(--font-mono);
        }
        .search-history-chip {
          padding: 2px 9px; border-radius: 3px;
          border: 1px solid var(--border-subtle);
          background: var(--bg-elevated); color: var(--text-tertiary);
          font-size: 11px; font-family: 'IBM Plex Mono', var(--font-mono);
          cursor: pointer; transition: all 0.12s;
          max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
        }
        .search-history-chip:hover {
          border-color: rgba(94,234,212,0.35); color: var(--accent-cyan);
          background: rgba(94,234,212,0.06);
        }
        .search-history-clear {
          padding: 2px 7px; border-radius: 3px; border: none;
          background: transparent; color: var(--text-disabled);
          font-size: 9px; cursor: pointer; font-family: 'IBM Plex Mono', var(--font-mono);
          transition: color .12s; letter-spacing: 0.3px;
        }
        .search-history-clear:hover { color: var(--text-tertiary); }
        .search-cmd-params {
          display: flex; align-items: flex-start;
          padding: 10px 16px; gap: 22px; flex-wrap: wrap;
          border-bottom: 1px solid var(--border-subtle);
          background: rgba(255,255,255,0.005);
        }
        .search-cmd-seg-wrap {
          display: flex; flex-direction: column; gap: 5px;
        }
        .search-cmd-seg-label {
          font-size: 9px; font-weight: 700; text-transform: uppercase;
          letter-spacing: 0.8px; color: var(--text-disabled);
          font-family: 'IBM Plex Mono', var(--font-mono);
        }
        .search-seg-group {
          display: flex; gap: 2px; background: var(--bg-elevated);
          border-radius: 5px; padding: 2px;
          border: 1px solid var(--border-subtle);
        }
        .search-seg-btn {
          padding: 4px 10px; border-radius: 4px; border: none;
          font-size: 11px; font-weight: 600; font-family: var(--font-sans);
          background: transparent; color: var(--text-tertiary);
          cursor: pointer; transition: all .12s; white-space: nowrap;
        }
        .search-seg-btn:hover:not(.disabled) { color: var(--text-secondary); }
        .search-seg-btn.active {
          background: var(--bg-surface); color: var(--text-primary);
          box-shadow: 0 1px 3px rgba(0,0,0,0.35);
        }
        .search-seg-btn.disabled { opacity: 0.35; cursor: not-allowed; }
        .search-seg-soon {
          margin-left: 4px; font-size: 8px; padding: 1px 3px;
          border-radius: 2px; background: var(--bg-hover);
          color: var(--text-disabled); vertical-align: middle; font-weight: 700;
        }
        .search-cmd-filters {
          display: flex; gap: 22px; flex-wrap: wrap; align-items: flex-end;
          padding: 10px 16px;
          background: rgba(255,255,255,0.005);
          border-top: 1px solid rgba(94,234,212,0.06);
        }
        .search-cmd-filter-group {
          display: flex; flex-direction: column; gap: 5px;
        }

        /* ── Preset compact layout ── */
        .preset-cat-scroll {
          display: flex; gap: 5px; overflow-x: auto;
          padding: 10px 14px 8px; scrollbar-width: none; flex-wrap: wrap;
        }
        .preset-cat-scroll::-webkit-scrollbar { display: none; }
        .preset-cat-pill {
          display: inline-flex; align-items: center; gap: 5px;
          padding: 4px 11px; border-radius: 4px;
          border: 1px solid var(--border-subtle); background: var(--bg-elevated);
          color: var(--text-tertiary); font-size: 11px; font-weight: 600;
          cursor: pointer; transition: all .15s; white-space: nowrap;
          font-family: 'Rajdhani', var(--font-sans); letter-spacing: 0.2px;
        }
        .preset-cat-pill:hover {
          border-color: var(--border-default); color: var(--text-secondary);
        }
        .preset-cat-pill.active {
          background: rgba(255,255,255,0.04);
          border-color: rgba(255,255,255,0.18);
          color: var(--text-primary);
        }
        .preset-cat-pill.active-saved {
          border-color: rgba(94,234,212,0.4); color: var(--accent-cyan);
          background: rgba(94,234,212,0.07);
        }
        .preset-cat-count {
          font-size: 9px; font-weight: 700; font-family: 'IBM Plex Mono', var(--font-mono);
          padding: 1px 4px; border-radius: 3px;
          background: rgba(255,255,255,0.05); color: var(--text-disabled);
        }
        .preset-note-bar {
          padding: 7px 14px 7px 12px; border-left: 2px solid var(--accent-cyan);
          margin: 0 14px 8px; background: rgba(94,234,212,0.03);
          font-size: 11px; color: var(--text-secondary); line-height: 1.55;
          border-radius: 0 4px 4px 0;
        }
        .preset-meta-chip {
          font-size: 9.5px; color: var(--text-tertiary);
          border: 1px solid var(--border-subtle); background: rgba(255,255,255,0.02);
          border-radius: 3px; padding: 2px 7px; white-space: nowrap;
          font-family: 'IBM Plex Mono', var(--font-mono);
        }
        .preset-tags-flat {
          display: flex; flex-wrap: wrap; gap: 6px;
          padding: 4px 14px 12px;
        }
        .preset-flat-tag {
          display: inline-flex; align-items: center; gap: 5px;
          padding: 5px 12px; border-radius: 4px;
          border: 1px solid var(--border-subtle); background: var(--bg-elevated);
          color: var(--text-secondary); font-size: 11px; font-weight: 500;
          cursor: pointer; transition: all .15s; font-family: var(--font-sans);
        }
        .preset-flat-tag:hover {
          border-color: rgba(94,234,212,0.35); color: var(--text-primary);
          background: rgba(94,234,212,0.05);
        }
        .preset-flat-tag.active { font-weight: 700; }
        .preset-flat-delete {
          display: inline-flex; align-items: center; padding: 5px 8px;
          border: 1px solid var(--border-subtle); border-left: none;
          background: var(--bg-elevated); color: var(--text-disabled);
          font-size: 9px; cursor: pointer; transition: all .12s; border-radius: 0 4px 4px 0;
          font-family: var(--font-sans);
        }
        .preset-flat-delete:hover {
          color: var(--accent-red); border-color: rgba(242,63,93,0.3);
          background: rgba(242,63,93,0.05);
        }

        /* ── btn-v3 system ── */
        .btn-v3 {
          display: inline-flex; align-items: center; gap: 5px;
          padding: 6px 13px; border-radius: 6px; border: none;
          font-family: var(--font-sans); font-size: 12px; font-weight: 600;
          cursor: pointer; transition: all .15s; white-space: nowrap;
          text-decoration: none; flex-shrink: 0;
        }
        .btn-v3-sm { padding: 5px 10px; font-size: 11px; border-radius: 5px; }
        .btn-v3-primary {
          background: rgba(94,234,212,0.1);
          border: 1px solid rgba(94,234,212,0.3); color: var(--accent-cyan);
        }
        .btn-v3-primary:hover:not(:disabled) {
          background: rgba(94,234,212,0.18);
          border-color: rgba(94,234,212,0.5);
          box-shadow: 0 0 12px rgba(94,234,212,0.15);
          transform: translateY(-1px);
        }
        .btn-v3-ghost {
          background: var(--bg-elevated); border: 1px solid var(--border-subtle);
          color: var(--text-secondary);
        }
        .btn-v3-ghost:hover:not(:disabled) {
          background: var(--bg-hover); border-color: var(--border-default);
          color: var(--text-primary);
        }
        .btn-v3-danger {
          background: rgba(242,63,93,0.1); border: 1px solid rgba(242,63,93,0.25);
          color: var(--accent-red);
        }
        .btn-v3-success {
          background: rgba(74,222,128,0.09); border: 1px solid rgba(74,222,128,0.25);
          color: var(--accent-green);
        }
        .btn-v3:disabled { opacity: 0.4; cursor: not-allowed; transform: none !important; }

        /* ── Video list — horizontal rows ── */
        .vid-list {
          display: flex; flex-direction: column;
          border: 1px solid var(--border-subtle);
          border-radius: 8px; overflow: hidden;
          background: var(--bg-surface);
        }
        .vid-item {
          border-top: 1px solid var(--border-subtle);
          border-left: 2px solid var(--vid-accent, transparent);
          transition: border-color .15s, background .15s;
        }
        .vid-item:first-child { border-top: none; }
        .vid-item:hover { background: rgba(255,255,255,0.015); }
        .vid-item-selected {
          background: rgba(94,234,212,0.04) !important;
          border-left-color: var(--accent-cyan) !important;
        }
        .vid-item-open { background: rgba(94,234,212,0.03); }

        .vid-row {
          display: flex; align-items: center; gap: 0;
          min-height: 84px;
        }

        /* Checkbox col */
        .vid-row-check-btn {
          display: flex; align-items: center; justify-content: center;
          width: 40px; flex-shrink: 0; align-self: stretch;
          background: transparent; border: none; cursor: pointer;
          transition: background .12s;
        }
        .vid-row-check-btn:hover { background: rgba(255,255,255,0.03); }
        .vid-row-check {
          width: 16px; height: 16px; border-radius: 3px;
          border: 1.5px solid rgba(255,255,255,0.25);
          background: transparent; display: flex; align-items: center;
          justify-content: center; transition: all .12s; flex-shrink: 0;
        }
        .vid-row-check.checked {
          background: var(--accent-cyan); border-color: var(--accent-cyan);
        }

        /* Thumbnail col */
        .vid-row-thumb {
          position: relative; width: 52px; flex-shrink: 0;
          align-self: stretch; overflow: hidden; display: block;
          text-decoration: none; background: var(--bg-elevated);
        }
        .vid-row-img {
          width: 100%; height: 100%; object-fit: cover; display: block;
          transition: opacity .2s;
        }
        .vid-row-thumb:hover .vid-row-img { opacity: 0.85; }
        .vid-row-thumb-shade {
          position: absolute; inset: 0;
          background: linear-gradient(to top, rgba(0,0,0,0.65) 0%, transparent 50%);
          pointer-events: none;
        }
        .vid-row-hot {
          position: absolute; top: 4px; left: 4px;
          font-size: 7px; font-weight: 800; letter-spacing: 0.5px;
          padding: 1px 4px; border-radius: 2px; color: #fff;
          font-family: 'IBM Plex Mono', var(--font-mono);
        }
        .vid-row-dur {
          position: absolute; bottom: 3px; right: 3px;
          font-size: 9px; font-weight: 600; color: #fff;
          font-family: 'IBM Plex Mono', var(--font-mono);
          background: rgba(0,0,0,0.75); padding: 1px 3px; border-radius: 2px;
        }
        .vid-row-ubt {
          position: absolute; bottom: 3px; left: 3px;
          font-size: 9px; font-weight: 800; color: #fff;
          font-family: 'IBM Plex Mono', var(--font-mono);
          padding: 1px 3px; border-radius: 2px; letter-spacing: 0.3px;
        }

        /* Body col */
        .vid-row-body {
          flex: 1; min-width: 0; padding: 10px 14px;
          display: flex; flex-direction: column; gap: 5px;
        }
        .vid-row-title {
          font-size: 12.5px; font-weight: 600; color: var(--text-primary);
          text-decoration: none; line-height: 1.4;
          display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
          overflow: hidden; letter-spacing: -0.1px;
          transition: color .12s;
        }
        .vid-row-title:hover { color: var(--accent-cyan); }
        .vid-row-meta {
          display: flex; align-items: center; gap: 5px;
          font-size: 10.5px; color: var(--text-tertiary); flex-wrap: wrap;
        }
        .vid-row-channel {
          font-weight: 600; color: rgba(94,234,212,0.75);
          text-decoration: none; max-width: 160px;
          overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
        }
        .vid-row-channel:hover { color: var(--accent-cyan); }
        .vid-row-channel-dim { color: var(--text-secondary); }
        .vid-row-time { color: var(--text-disabled); }
        .vid-row-region { margin-left: auto; font-size: 12px; }
        .vid-row-chips { display: flex; gap: 4px; flex-wrap: wrap; align-items: center; }

        /* Metric chips */
        .vid-metric-chip {
          display: inline-flex; align-items: center; gap: 3px;
          padding: 2px 7px; border-radius: 3px;
          font-size: 10.5px; font-weight: 600;
          font-family: 'IBM Plex Mono', var(--font-mono);
          border: 1px solid transparent;
        }
        .vid-metric-chip-views {
          background: rgba(96,165,250,0.08); color: #7eb8ff;
          border-color: rgba(96,165,250,0.15);
        }
        .vid-metric-chip-likes {
          background: rgba(244,114,182,0.08); color: #f4a0cc;
          border-color: rgba(244,114,182,0.15);
        }
        .vid-metric-chip-comments {
          background: rgba(167,139,250,0.08); color: #c4b0fa;
          border-color: rgba(167,139,250,0.15);
        }
        .vid-metric-chip-er-hot {
          background: rgba(74,222,128,0.1); color: var(--accent-green);
          border-color: rgba(74,222,128,0.2);
        }
        .vid-metric-chip-er-warm {
          background: rgba(251,191,36,0.08); color: var(--accent-amber);
          border-color: rgba(251,191,36,0.18);
        }
        .vid-metric-chip-er-cold {
          background: rgba(255,255,255,0.03); color: var(--text-disabled);
          border-color: var(--border-subtle);
        }
        .vid-mask-chip {
          display: inline-flex; align-items: center; gap: 3px;
          padding: 2px 6px; border-radius: 3px;
          font-size: 9.5px; font-weight: 800; letter-spacing: 0.4px;
          font-family: 'IBM Plex Mono', var(--font-mono);
          background: rgba(242,63,93,0.1); color: #F23F5D;
          border: 1px solid rgba(242,63,93,0.22);
        }
        .vid-src-tag {
          display: inline-flex; align-items: center;
          padding: 2px 6px; border-radius: 3px;
          font-size: 9px; font-weight: 700; letter-spacing: 0.5px;
          font-family: 'IBM Plex Mono', var(--font-mono);
          background: rgba(255,255,255,0.04); color: var(--text-disabled);
          border: 1px solid var(--border-subtle);
        }

        /* Score col */
        .vid-row-score-col {
          flex-shrink: 0; padding: 0 12px;
          display: flex; align-items: center; justify-content: center;
        }

        /* Actions col */
        .vid-row-actions {
          display: flex; align-items: center; gap: 4px;
          padding: 0 10px; flex-shrink: 0;
        }
        .vid-action-btn { padding: 0 8px !important; min-width: 30px; height: 28px; justify-content: center; }

        /* Error / advice rows */
        .vid-row-error {
          padding: 4px 14px 6px 102px; font-size: 10px; color: var(--accent-red);
        }
        .vid-advice-wrap {
          padding: 0 14px 14px 102px;
        }

        /* ── Queue file row ── */
        .queue-file-row {
          display: flex; align-items: center; gap: 12px;
          padding: 10px 16px;
          transition: background .12s;
        }
        .queue-file-row:hover { background: rgba(255,255,255,0.02); }

        /* ── HOT badge pulse ── */
        @keyframes hot-pulse {
          0%, 100% { box-shadow: 0 0 0 0 rgba(242,63,93,0.6); }
          50% { box-shadow: 0 0 0 3px rgba(242,63,93,0); }
        }
        .hot-badge-pulse { animation: hot-pulse 2s ease-in-out infinite; }

        .research-page {
          --research-glow: 0 0 0 1px rgba(94,234,212,0.24), 0 0 34px rgba(94,234,212,0.14), 0 18px 60px rgba(0,0,0,0.45);
        }
        .research-page .search-cmd-card {
          border-radius: 14px;
          border-color: rgba(94,234,212,0.18);
          background:
            linear-gradient(145deg, rgba(94,234,212,0.07), transparent 28%),
            linear-gradient(315deg, rgba(167,139,250,0.08), transparent 34%),
            var(--bg-surface);
          box-shadow: var(--research-glow);
        }
        .research-page .parser-spot-head {
          padding: 22px 24px 12px;
          border-bottom: 0;
          background: transparent;
        }
        .research-page .parser-spot-kicker,
        .research-page .parser-spot-desc,
        .research-page .parser-spot-steps,
        .research-page .parser-chip-strip,
        .research-page .parser-presets-fold {
          display: none;
        }
        .research-page .parser-spot-h1 {
          font-size: clamp(24px, 3vw, 42px);
          margin: 0;
          letter-spacing: -0.02em;
        }
        .research-page .search-cmd-query {
          padding: 18px 24px 16px;
          border-bottom: 0;
          background: transparent;
        }
        .research-page .search-cmd-input-wrap {
          min-height: 68px;
          border-radius: 14px;
          border-color: rgba(94,234,212,0.38);
          background: rgba(8,9,12,0.86);
          box-shadow: inset 0 0 0 1px rgba(255,255,255,0.03), 0 0 26px rgba(94,234,212,0.13);
        }
        .research-page .search-cmd-input-wrap::before {
          content: none;
        }
        .research-page .search-cmd-input {
          font-family: var(--font-sans);
          font-size: 22px;
          font-weight: 700;
          padding: 16px 0;
        }
        .research-page .search-cmd-input::placeholder {
          color: rgba(237,238,240,0.34);
        }
        .research-page .search-cmd-btn {
          min-height: 68px;
          padding: 0 30px;
          border-radius: 14px;
          font-size: 15px;
          background: linear-gradient(135deg, var(--accent-cyan), #8ffff0);
          color: #06110f;
          border: 0;
          box-shadow: 0 0 26px rgba(94,234,212,0.25);
        }
        .simple-preset-grid {
          display: grid;
          grid-template-columns: repeat(3, minmax(0, 1fr));
          gap: 14px;
          padding: 0 24px 18px;
        }
        .simple-preset-card {
          min-height: 118px;
          display: flex;
          align-items: center;
          gap: 14px;
          padding: 16px;
          border-radius: 12px;
          border: 1px solid color-mix(in srgb, var(--preset-accent) 36%, transparent);
          background:
            linear-gradient(145deg, color-mix(in srgb, var(--preset-accent) 18%, transparent), rgba(255,255,255,0.015)),
            var(--bg-elevated);
          color: var(--text-primary);
          text-align: left;
          transition: transform .16s, border-color .16s, box-shadow .16s;
          overflow: hidden;
          position: relative;
        }
        .simple-preset-card::after {
          content: "";
          position: absolute;
          inset: auto -24px -36px auto;
          width: 120px;
          height: 120px;
          border-radius: 50%;
          background: color-mix(in srgb, var(--preset-accent) 18%, transparent);
          filter: blur(18px);
        }
        .simple-preset-card:hover,
        .simple-preset-card.active {
          transform: translateY(-2px);
          border-color: color-mix(in srgb, var(--preset-accent) 70%, transparent);
          box-shadow: 0 0 28px color-mix(in srgb, var(--preset-accent) 18%, transparent);
        }
        .simple-preset-icon {
          width: 64px;
          height: 64px;
          border-radius: 16px;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          color: #07100f;
          background: linear-gradient(145deg, #fff, var(--preset-accent));
          box-shadow: inset 0 1px 0 rgba(255,255,255,0.75), 0 14px 28px rgba(0,0,0,0.34);
          transform: rotate(-4deg);
          flex-shrink: 0;
          position: relative;
          z-index: 1;
        }
        .simple-preset-copy {
          display: flex;
          flex-direction: column;
          gap: 2px;
          min-width: 0;
          position: relative;
          z-index: 1;
        }
        .simple-preset-label {
          font-size: 20px;
          font-weight: 800;
          letter-spacing: 0;
        }
        .simple-preset-hint {
          font-size: 13px;
          font-weight: 700;
          color: var(--text-tertiary);
        }
        .research-page .parser-tools-row,
        .research-page .search-cmd-params,
        .research-page .search-cmd-filters,
        .research-page .search-history-row {
          border-top: 1px solid var(--border-subtle);
          border-bottom: 0;
          padding-left: 24px;
          padding-right: 24px;
        }
        /* ── Intelligence Card Grid ── */
        .research-page .vid-list {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 20px;
          border: 0;
          background: transparent;
          overflow: visible;
        }

        /* ── Card shell ── */
        .research-page .vid-item {
          position: relative;
          border: 1px solid rgba(255,255,255,0.07);
          border-radius: 14px;
          overflow: hidden;
          background: #0e1014;
          box-shadow: 0 2px 0 rgba(255,255,255,0.04) inset,
                      0 20px 48px rgba(0,0,0,0.5);
          transition: transform 0.22s cubic-bezier(.22,1,.36,1),
                      border-color 0.22s ease,
                      box-shadow 0.22s ease;
        }
        .research-page .vid-item::before {
          content: '';
          position: absolute;
          inset: 0;
          border-radius: 14px;
          background: linear-gradient(180deg,
            rgba(255,255,255,0.03) 0%,
            transparent 40%);
          pointer-events: none;
          z-index: 1;
        }
        .research-page .vid-item:hover {
          transform: translateY(-5px);
          border-color: rgba(94,234,212,0.22);
          box-shadow: 0 0 0 1px rgba(94,234,212,0.1),
                      0 28px 60px rgba(0,0,0,0.6),
                      0 0 40px rgba(94,234,212,0.06);
        }

        /* ── Flex column ── */
        .research-page .vid-row {
          display: flex;
          flex-direction: column;
          align-items: stretch;
          min-height: 0;
        }

        /* ── Checkbox ── */
        .research-page .vid-row-check-btn {
          position: absolute;
          z-index: 5;
          width: 28px;
          height: 28px;
          top: 10px;
          left: 10px;
          border-radius: 6px;
          background: rgba(0,0,0,0.55);
          backdrop-filter: blur(10px);
          border: 1px solid rgba(255,255,255,0.12);
        }

        /* ── Thumbnail ── */
        .research-page .vid-row-thumb {
          width: 100%;
          aspect-ratio: 9 / 16;
          position: relative;
          overflow: hidden;
          cursor: default;
          background: #0a0c0f;
        }
        .research-page .vid-row-img {
          object-fit: cover;
          transition: transform 0.5s cubic-bezier(.22,1,.36,1);
        }
        .research-page .vid-item:hover .vid-row-img {
          transform: scale(1.04);
        }

        /* scan-line shimmer on hover */
        .research-page .vid-row-thumb::after {
          content: '';
          position: absolute;
          inset: 0;
          background: linear-gradient(180deg,
            transparent 0%, transparent 45%,
            rgba(94,234,212,0.04) 50%,
            transparent 55%, transparent 100%);
          background-size: 100% 200%;
          opacity: 0;
          transition: opacity 0.3s;
          pointer-events: none;
          z-index: 2;
          animation: none;
        }
        .research-page .vid-item:hover .vid-row-thumb::after {
          opacity: 1;
          animation: scanline 2s linear infinite;
        }
        @keyframes scanline {
          0%   { background-position: 0 -100%; }
          100% { background-position: 0 200%; }
        }

        /* ── HOT/NEW badge — sharp corner tag ── */
        .research-page .vid-row-hot {
          position: absolute !important;
          top: 0 !important;
          left: 0 !important;
          z-index: 4;
          padding: 4px 9px !important;
          border-radius: 0 0 8px 0 !important;
          font-family: 'IBM Plex Mono', monospace !important;
          font-size: 9px !important;
          font-weight: 700 !important;
          letter-spacing: 0.12em !important;
          text-transform: uppercase !important;
        }

        /* ── Duration badge ── */
        .research-page .vid-row-dur {
          position: absolute !important;
          bottom: 10px !important;
          right: 10px !important;
          z-index: 4;
          font-family: 'IBM Plex Mono', monospace !important;
          font-size: 11px !important;
          font-weight: 500 !important;
          color: #fff !important;
          background: rgba(0,0,0,0.72) !important;
          backdrop-filter: blur(6px) !important;
          padding: 3px 7px !important;
          border-radius: 5px !important;
          border: 1px solid rgba(255,255,255,0.1) !important;
          letter-spacing: 0.02em !important;
        }

        /* ── Download overlay — glass command button ── */
        .video-download-overlay {
          position: absolute;
          left: 10px;
          right: 10px;
          bottom: 10px;
          z-index: 3;
          min-height: 44px;
          border: 1px solid rgba(94,234,212,0.35);
          border-radius: 10px;
          background: rgba(10,14,18,0.82);
          backdrop-filter: blur(12px);
          color: #5EEAD4;
          font-family: 'IBM Plex Mono', monospace;
          font-size: 13px;
          font-weight: 600;
          letter-spacing: 0.06em;
          text-transform: uppercase;
          opacity: 0;
          transform: translateY(6px);
          transition: opacity 0.2s ease, transform 0.2s ease,
                      background 0.15s, border-color 0.15s;
          box-shadow: 0 0 20px rgba(94,234,212,0.15),
                      0 8px 24px rgba(0,0,0,0.4);
        }
        .research-page .vid-item:hover .video-download-overlay {
          opacity: 1;
          transform: translateY(0);
        }
        .video-download-overlay:hover {
          background: rgba(94,234,212,0.12) !important;
          border-color: rgba(94,234,212,0.7) !important;
          box-shadow: 0 0 30px rgba(94,234,212,0.25) !important;
        }
        .video-download-overlay.busy,
        .video-download-overlay.done {
          opacity: 1 !important;
          transform: translateY(0) !important;
          border-color: rgba(52,211,153,0.5);
          color: #34D399;
          background: rgba(10,14,18,0.82);
        }
        .video-download-overlay.error {
          opacity: 1 !important;
          transform: translateY(0) !important;
          border-color: rgba(248,113,113,0.5);
          color: #F87171;
          background: rgba(10,14,18,0.82);
        }

        /* ── Card body ── */
        .research-page .vid-row-body {
          padding: 14px 14px 10px;
          gap: 8px;
          display: flex;
          flex-direction: column;
        }

        /* ── Title ── */
        .research-page .vid-row-title {
          font-family: 'Syne', sans-serif;
          font-size: 15px;
          font-weight: 700;
          line-height: 1.35;
          min-height: 0;
          color: #E8EDF2;
          display: -webkit-box;
          -webkit-line-clamp: 3;
          -webkit-box-orient: vertical;
          overflow: hidden;
          letter-spacing: -0.01em;
        }
        .research-page .vid-row-title:hover {
          color: #fff;
        }

        /* ── Meta row (channel · time · region) ── */
        .research-page .vid-row-meta {
          display: flex;
          align-items: center;
          gap: 5px;
          font-family: 'IBM Plex Mono', monospace;
          font-size: 11px;
          flex-wrap: wrap;
        }
        .research-page .vid-row-channel {
          color: #5EEAD4 !important;
          font-weight: 500;
          text-decoration: none !important;
          letter-spacing: 0.01em;
        }
        .research-page .vid-row-channel:hover { color: #9ef7ee !important; }
        .research-page .vid-row-channel-dim { color: rgba(94,234,212,0.55) !important; }
        .research-page .vid-row-time {
          color: rgba(255,255,255,0.3);
          font-size: 10px;
        }
        .research-page .vid-row-region {
          margin-left: auto;
          color: rgba(255,255,255,0.25);
          font-size: 10px;
          letter-spacing: 0.05em;
        }

        /* ── Metrics strip ── */
        .research-page .vid-row-chips {
          display: flex;
          align-items: center;
          gap: 6px;
          flex-wrap: wrap;
          padding: 8px 0 2px;
          border-top: 1px solid rgba(255,255,255,0.05);
        }
        .research-page .vid-metric-chip {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          font-family: 'IBM Plex Mono', monospace;
          font-size: 12px;
          font-weight: 500;
          padding: 4px 8px;
          border-radius: 6px;
          border: 1px solid transparent;
          letter-spacing: 0.01em;
        }
        .research-page .vid-metric-chip-views {
          font-size: 13px;
          font-weight: 600;
          color: #E8EDF2;
          background: rgba(255,255,255,0.05);
          border-color: rgba(255,255,255,0.08);
          padding: 5px 10px;
        }
        .research-page .vid-metric-chip-likes {
          color: #F472B6;
          background: rgba(244,114,182,0.08);
          border-color: rgba(244,114,182,0.15);
        }
        .research-page .vid-metric-chip-comments {
          color: #818CF8;
          background: rgba(129,140,248,0.08);
          border-color: rgba(129,140,248,0.15);
        }
        .research-page .vid-metric-chip-er-hot {
          color: #34D399;
          background: rgba(52,211,153,0.1);
          border-color: rgba(52,211,153,0.2);
          font-weight: 600;
        }
        .research-page .vid-metric-chip-er-warm {
          color: #FBBF24;
          background: rgba(251,191,36,0.08);
          border-color: rgba(251,191,36,0.15);
        }
        .research-page .vid-metric-chip-er-cold {
          color: rgba(255,255,255,0.3);
          background: transparent;
          border-color: rgba(255,255,255,0.07);
        }
        .research-page .vid-src-tag {
          margin-left: auto;
          font-family: 'IBM Plex Mono', monospace;
          font-size: 10px;
          font-weight: 600;
          padding: 3px 7px;
          border-radius: 4px;
          letter-spacing: 0.06em;
          text-transform: uppercase;
          background: rgba(255,0,0,0.1);
          color: #FF6B6B;
          border: 1px solid rgba(255,0,0,0.18);
        }
        .research-page .vid-mask-chip {
          font-family: 'IBM Plex Mono', monospace;
          font-size: 10px;
          font-weight: 700;
          padding: 3px 7px;
          border-radius: 4px;
          letter-spacing: 0.05em;
          background: rgba(245,158,11,0.12);
          color: #FBBF24;
          border: 1px solid rgba(245,158,11,0.22);
        }

        /* ── Score ring position ── */
        .research-page .vid-row-score-col {
          position: absolute;
          z-index: 5;
          top: 10px;
          right: 10px;
          padding: 0;
        }

        /* ── Actions bar ── */
        .research-page .vid-row-actions {
          padding: 0 12px 12px;
          justify-content: flex-end;
          gap: 6px;
          display: flex;
        }
        .research-page .vid-row-actions .vid-action-btn:first-child {
          display: none;
        }
        .research-page .vid-row-actions .vid-action-btn {
          width: 32px;
          height: 32px;
          border-radius: 8px;
          border: 1px solid rgba(255,255,255,0.08);
          background: rgba(255,255,255,0.04);
          color: rgba(255,255,255,0.45);
          font-family: 'IBM Plex Mono', monospace;
          font-size: 11px;
          transition: background 0.15s, color 0.15s, border-color 0.15s;
        }
        .research-page .vid-row-actions .vid-action-btn:hover {
          background: rgba(94,234,212,0.1);
          border-color: rgba(94,234,212,0.3);
          color: #5EEAD4;
        }

        /* ── Advice / error padding ── */
        .research-page .vid-advice-wrap,
        .research-page .vid-row-error {
          padding: 0 12px 12px;
        }
        @media (max-width: 900px) {
          .simple-preset-grid {
            grid-template-columns: repeat(2, minmax(0, 1fr));
          }
          .research-page .vid-list {
            grid-template-columns: repeat(2, 1fr);
          }
        }
        @media (max-width: 560px) {
          .simple-preset-grid {
            grid-template-columns: 1fr;
          }
          .research-page .vid-list {
            grid-template-columns: 1fr;
          }
        }
        @media (max-width: 720px) {
          .research-page .search-cmd-query {
            flex-direction: column;
            align-items: stretch;
          }
          .research-page .search-cmd-btn {
            width: 100%;
          }
          .simple-preset-grid {
            grid-template-columns: 1fr;
          }
          .research-page .vid-list {
            grid-template-columns: repeat(2, minmax(0, 1fr));
          }
        }
        @media (max-width: 520px) {
          .research-page .vid-list {
            grid-template-columns: 1fr;
          }
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
              ER: <span style={{ color: "var(--accent-cyan)", fontWeight: 600 }}>{advice.engagement_rate!.toFixed(0)}%</span>
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
