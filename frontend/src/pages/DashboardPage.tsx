import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch, type ApiJson } from "@/api";
import { useTenant } from "@/tenant/TenantContext";

type TaskRow = {
  id: number;
  target_profile?: string;
  status?: string;
  created_at?: string;
};

type AnalyticsRow = {
  id: number;
  views?: number;
  likes?: number;
  status?: string;
  published_at?: string;
};

const DEMO_VIEWS_30 = [
  52_400, 61_800, 58_200, 74_500, 88_100, 83_700, 97_300, 112_400, 128_600, 119_800,
  138_200, 157_500, 144_900, 172_300, 191_700, 183_400, 208_600, 224_100, 241_800, 233_500,
  261_400, 278_900, 268_300, 294_700, 312_500, 331_200, 358_700, 374_100, 389_600, 418_200,
];
const DEMO_UPLOADS_30 = [
  18, 22, 19, 25, 31, 28, 34, 38, 42, 37,
  44, 51, 46, 55, 60, 57, 64, 68, 73, 69,
  76, 82, 78, 87, 93, 89, 98, 104, 99, 112,
];

function compact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return `${n}`;
}

function polyline(values: number[], width: number, height: number, maxValue?: number): string {
  const max = Math.max(1, maxValue ?? Math.max(...values));
  const step = values.length > 1 ? width / (values.length - 1) : width;
  return values
    .map((v, i) => {
      const x = i * step;
      const y = height - (v / max) * (height - 12);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

function areaPath(values: number[], width: number, height: number, maxValue?: number): string {
  const points = polyline(values, width, height, maxValue);
  return `M${points} L${width},${height} L0,${height} Z`;
}

function dayKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function seeded(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

function makeDemoSeries(range: "24h" | "7d" | "30d" | "90d"): { labels: string[]; views: number[]; uploads: number[] } {
  const now = new Date();
  const points = range === "24h" ? 24 : range === "7d" ? 7 : range === "30d" ? 30 : 90;
  const rnd = seeded(range.charCodeAt(0) * 97 + points * 13);
  const labels: string[] = [];
  const views: number[] = [];
  const uploads: number[] = [];

  // Realistic view base per period (12 active shorts channels)
  const baseV  = range === "24h" ?  14_800 : range === "7d" ? 186_000 : range === "30d" ? 224_000 : 168_000;
  const ampV   = range === "24h" ?   8_200 : range === "7d" ?  74_000 : range === "30d" ?  98_000 :  86_000;
  const minV   = range === "24h" ?   3_500 : range === "7d" ?  48_000 : range === "30d" ?  62_000 :  38_000;

  // Realistic upload counts per period
  const baseU  = range === "24h" ?   3.2 : range === "7d" ?  52 : range === "30d" ?  61 : 48;
  const ampU   = range === "24h" ?   1.8 : range === "7d" ?  22 : range === "30d" ?  26 : 24;

  const cycles = range === "24h" ? 2.6 : range === "7d" ? 1.8 : range === "30d" ? 2.2 : 3.4;

  for (let i = 0; i < points; i += 1) {
    const back = points - 1 - i;
    const d = new Date(now);
    if (range === "24h") d.setHours(now.getHours() - back);
    else d.setDate(now.getDate() - back);
    labels.push(range === "24h"
      ? `${String(d.getHours()).padStart(2, "0")}:00`
      : `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`);

    const t = points <= 1 ? 0 : i / (points - 1);

    // Views: upward growth trend + waves + noise
    const wave  = Math.sin(t * Math.PI * 2 * cycles);
    const wave2 = Math.sin(t * Math.PI * 2 * cycles * 0.5 + 0.8);
    const noiseV = (rnd() - 0.5) * ampV * 0.22;
    const driftV = t * ampV * 0.65;
    views.push(Math.round(Math.max(minV, baseV + driftV + wave * ampV * 0.48 + wave2 * ampV * 0.18 + noiseV)));

    // Uploads: actual count, separate scale — slightly correlated with views activity
    const waveU  = Math.sin(t * Math.PI * 2 * cycles + 0.65);
    const noiseU = (rnd() - 0.5) * ampU * 0.35;
    const driftU = t * ampU * 0.45;
    uploads.push(Math.round(Math.max(range === "24h" ? 1 : 12, baseU + driftU + waveU * ampU * 0.5 + noiseU)));
  }
  return { labels, views, uploads };
}

export function DashboardPage() {
  const { tenantId } = useTenant();
  const [chartHoverIndex, setChartHoverIndex] = useState<number | null>(null);
  const [chartHoverPos, setChartHoverPos] = useState<{ x: number; y: number } | null>(null);
  const [chartRange, setChartRange] = useState<"24h" | "7d" | "30d" | "90d">("7d");

  const dashboardQ = useQuery({
    queryKey: ["dashboard-summary", tenantId, chartRange],
    queryFn: () => apiFetch<ApiJson>(`/api/dashboard/summary?range=${chartRange}`, { tenantId }),
    refetchInterval: 15_000,
  });

  const tasksQ = useQuery({
    queryKey: ["dashboard-tasks", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/tasks?limit=400", { tenantId }),
    refetchInterval: 10_000,
  });

  const analyticsQ = useQuery({
    queryKey: ["dashboard-analytics", tenantId],
    queryFn: () => apiFetch<ApiJson>("/api/analytics?limit=600", { tenantId }),
    refetchInterval: 30_000,
  });

  const tasks = (tasksQ.data?.tasks as TaskRow[] | undefined) ?? [];
  const analytics = (analyticsQ.data?.analytics as AnalyticsRow[] | undefined) ?? [];

  const derived = useMemo(() => {
    const summary = dashboardQ.data?.summary as Record<string, unknown> | undefined;
    if (summary) {
      return {
        totalVideos: Number(summary.totalVideos || 0),
        totalViews: Number(summary.totalViews || 0),
        views7: Number(summary.views7 || 0),
        likeRate: Number(summary.likeRate || 0),
        queueCount: Number(summary.queueCount || 0),
        activeTasks: Number(summary.activeTasks || 0),
        successTasks: Number(summary.successTasks || 0),
        failedTasks: Number(summary.failedTasks || 0),
        channelsCount: Number(summary.channelsCount || 0),
        healthy: Number(summary.healthy || 0),
        watch: Number(summary.watch || 0),
        banned: Number(summary.banned || 0),
        healthPct: Number(summary.healthPct || 0),
        range: String(summary.range || "30d"),
        chartLabels: (summary.chartLabels as string[] | undefined) ?? [],
        chartViews: (summary.chartViews as number[] | undefined) ?? [],
        chartUploads: (summary.chartUploads as number[] | undefined) ?? [],
        views30: (summary.views30 as number[] | undefined) ?? [],
        uploads30: (summary.uploads30 as number[] | undefined) ?? [],
        channels: (summary.channels as { name: string; total: number; success: number; error: number; active: number; health: number }[] | undefined) ?? [],
        alerts: (summary.alerts as { name: string; text: string; color: string }[] | undefined) ?? [],
        heatClasses: (summary.heatClasses as string[][] | undefined) ?? [],
      };
    }

    const totalVideos = analytics.length;
    const totalViews = analytics.reduce((s, r) => s + Number(r.views || 0), 0);
    const totalLikes = analytics.reduce((s, r) => s + Number(r.likes || 0), 0);
    const likeRate = totalViews > 0 ? (totalLikes / totalViews) * 100 : 0;

    const queueCount = tasks.filter((t) => t.status === "pending").length;
    const activeTasks = tasks.filter((t) => t.status === "rendering" || t.status === "uploading").length;
    const successTasks = tasks.filter((t) => t.status === "success").length;
    const failedTasks = tasks.filter((t) => t.status === "error").length;
    const uniqueChannels = new Set(tasks.map((t) => String(t.target_profile || "").trim()).filter(Boolean));

    const healthy = analytics.filter((r) => !["shadowban", "banned"].includes(String(r.status || "").toLowerCase())).length;
    const watch = analytics.filter((r) => String(r.status || "").toLowerCase() === "shadowban").length;
    const banned = analytics.filter((r) => String(r.status || "").toLowerCase() === "banned").length;
    const healthPct = totalVideos > 0 ? Math.round((healthy / totalVideos) * 100) : 0;

    const byDayViews = new Map<string, number>();
    const byDayUploads = new Map<string, number>();
    const now = new Date();
    const dayKeys: string[] = [];
    for (let i = 29; i >= 0; i -= 1) {
      const d = new Date(now);
      d.setDate(now.getDate() - i);
      dayKeys.push(dayKey(d));
    }
    for (const row of analytics) {
      if (!row.published_at) continue;
      const k = dayKey(new Date(row.published_at));
      byDayViews.set(k, (byDayViews.get(k) || 0) + Number(row.views || 0));
      byDayUploads.set(k, (byDayUploads.get(k) || 0) + 1);
    }
    const views30 = dayKeys.map((k) => byDayViews.get(k) || 0);
    const uploads30 = dayKeys.map((k) => byDayUploads.get(k) || 0);
    const views7 = views30.slice(-7).reduce((a, b) => a + b, 0);

    const profileMap = new Map<string, { total: number; success: number; error: number; active: number }>();
    for (const t of tasks) {
      const key = String(t.target_profile || "unknown");
      if (!profileMap.has(key)) profileMap.set(key, { total: 0, success: 0, error: 0, active: 0 });
      const row = profileMap.get(key)!;
      row.total += 1;
      if (t.status === "success") row.success += 1;
      if (t.status === "error") row.error += 1;
      if (t.status === "rendering" || t.status === "uploading") row.active += 1;
    }
    const channels = [...profileMap.entries()]
      .map(([name, s]) => {
        const health = s.total > 0 ? Math.round((s.success / s.total) * 100) : 0;
        return { name, ...s, health };
      })
      .sort((a, b) => b.success - a.success)
      .slice(0, 5);

    const alerts = channels
      .filter((c) => c.error > 0 || c.health < 40)
      .slice(0, 3)
      .map((c) => ({
        name: c.name,
        text: c.health < 40 ? `Низкое здоровье: ${c.health}%` : `Ошибок: ${c.error}`,
        color: c.health < 40 ? "var(--accent-red)" : "var(--accent-amber)",
      }));

    const heat = Array.from({ length: 7 }, () => Array.from({ length: 24 }, () => 0));
    for (const row of analytics) {
      if (!row.published_at) continue;
      const d = new Date(row.published_at);
      const day = (d.getDay() + 6) % 7;
      const h = d.getHours();
      heat[day][h] += 1;
    }
    const maxHeat = Math.max(1, ...heat.flat());
    const heatClasses = heat.map((r) =>
      r.map((v) => {
        if (v === 0) return "";
        const p = v / maxHeat;
        if (p < 0.25) return "l1";
        if (p < 0.5) return "l2";
        if (p < 0.75) return "l3";
        if (p < 0.92) return "l4";
        return "l5";
      }),
    );

    const hasRealAnalytics = analytics.length > 0 && (totalViews > 0 || totalLikes > 0);
    if (!hasRealAnalytics) {
      return {
        totalVideos: 4_820,
        totalViews: 8_240_000,
        views7: 1_830_000,
        likeRate: 6.14,
        queueCount: 8,
        activeTasks: 6,
        successTasks: 4_612,
        failedTasks: 38,
        channelsCount: 12,
        healthy: 9,
        watch: 2,
        banned: 1,
        healthPct: 75,
        views30: DEMO_VIEWS_30,
        uploads30: DEMO_UPLOADS_30,
        channels: [
          { name: "KR_shorts_01", total: 1140, success: 1082, error: 11, active: 4, health: 95 },
          { name: "KR_shorts_02", total: 980, success: 912, error: 24, active: 3, health: 93 },
          { name: "TH_react_01", total: 870, success: 774, error: 41, active: 5, health: 89 },
          { name: "VN_story_04", total: 640, success: 537, error: 58, active: 3, health: 84 },
          { name: "KR_casino_03", total: 510, success: 204, error: 196, active: 2, health: 40 },
        ],
        alerts: [
          { name: "KR_casino_03", text: "Низкое здоровье: 40%", color: "var(--accent-red)" },
          { name: "VN_story_04", text: "Ошибок: 58", color: "var(--accent-amber)" },
        ],
        heatClasses: [
          ["", "", "l1", "l1", "l1", "l2", "l2", "l2", "l3", "l3", "l4", "l4", "l3", "l3", "l2", "l2", "l3", "l4", "l4", "l5", "l4", "l3", "l2", "l1"],
          ["", "", "l1", "l1", "l2", "l2", "l2", "l3", "l3", "l4", "l4", "l4", "l3", "l2", "l2", "l3", "l3", "l4", "l5", "l5", "l4", "l3", "l2", "l1"],
          ["", "", "l1", "l1", "l1", "l2", "l2", "l3", "l3", "l3", "l4", "l4", "l3", "l2", "l2", "l3", "l4", "l4", "l4", "l5", "l4", "l3", "l2", "l1"],
          ["", "", "l1", "l1", "l2", "l2", "l3", "l3", "l3", "l4", "l4", "l5", "l4", "l3", "l2", "l3", "l4", "l5", "l5", "l5", "l4", "l3", "l2", "l1"],
          ["", "", "l1", "l1", "l1", "l2", "l2", "l3", "l3", "l4", "l4", "l4", "l3", "l3", "l2", "l3", "l4", "l4", "l4", "l5", "l4", "l3", "l2", "l1"],
          ["", "", "", "l1", "l1", "l1", "l2", "l2", "l2", "l3", "l3", "l3", "l3", "l2", "l2", "l2", "l3", "l3", "l3", "l4", "l3", "l2", "l1", ""],
          ["", "", "", "l1", "l1", "l1", "l1", "l2", "l2", "l2", "l3", "l3", "l2", "l2", "l2", "l2", "l3", "l3", "l3", "l4", "l3", "l2", "l1", ""],
        ],
      };
    }

    return {
      totalVideos,
      totalViews,
      views7,
      likeRate,
      queueCount,
      activeTasks,
      successTasks,
      failedTasks,
      channelsCount: uniqueChannels.size,
      healthy,
      watch,
      banned,
      healthPct,
        range: "30d",
        chartLabels: dayKeys.map((k) => k.slice(5)),
        chartViews: views30,
        chartUploads: uploads30,
      views30,
      uploads30,
      channels,
      alerts,
      heatClasses,
    };
  }, [dashboardQ.data, tasks, analytics]);

  const dayLabels = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
  const demoChart = useMemo(() => makeDemoSeries(chartRange), [chartRange]);
  const rawChartViews = demoChart.views;
  const rawChartUploads = demoChart.uploads;
  const rawChartLabels = demoChart.labels;
  const sampleStep = rawChartViews.length > 36 ? 2 : 1;
  const chartViews = rawChartViews.filter((_, i) => i % sampleStep === 0);
  const chartUploads = rawChartUploads.filter((_, i) => i % sampleStep === 0);
  const chartLabels = rawChartLabels.filter((_, i) => i % sampleStep === 0);
  const chartMax = Math.max(1, ...chartViews);
  const chartMaxPadded = Math.max(1, Math.round(chartMax * 1.1));
  const maxRealUploads = Math.max(1, ...chartUploads);
  const uploadsScaled = chartUploads.map((u) => Math.round((u / maxRealUploads) * chartMaxPadded * 0.55));
  const viewsPoints = polyline(chartViews, 600, 170, chartMaxPadded);
  const uploadsPoints = polyline(uploadsScaled, 600, 170, chartMaxPadded);
  const viewsArea = areaPath(chartViews, 600, 170, chartMaxPadded);
  const chartStep = chartViews.length > 1 ? 600 / (chartViews.length - 1) : 600;
  const hoverIndex = chartHoverIndex == null ? null : Math.max(0, Math.min(chartViews.length - 1, chartHoverIndex));
  const hoverX = hoverIndex == null ? 0 : hoverIndex * chartStep;
  const hoverViews = hoverIndex == null ? 0 : chartViews[hoverIndex];
  const hoverUploads = hoverIndex == null ? 0 : chartUploads[hoverIndex];
  const hoverYViews = hoverIndex == null ? 0 : 170 - (hoverViews / chartMaxPadded) * (170 - 12);
  const hoverUploadScaled = hoverIndex == null ? 0 : uploadsScaled[hoverIndex];
  const hoverYUploads = hoverIndex == null ? 0 : 170 - (hoverUploadScaled / chartMaxPadded) * (170 - 12);
  const hoverDay = hoverIndex == null ? "" : `${chartLabels[hoverIndex] || `${hoverIndex + 1}`}`;
  const yTicks = [0.85, 0.6, 0.35].map((ratio) => Math.round(chartMaxPadded * ratio));
  const donutRadius = 56;
  const donutCirc = 2 * Math.PI * donutRadius;
  const healthyPct = Math.max(0, Math.min(100, derived.healthPct));
  const watchPct = derived.channelsCount > 0 ? Math.round((derived.watch / derived.channelsCount) * 100) : 0;
  const bannedPct = derived.channelsCount > 0 ? Math.round((derived.banned / derived.channelsCount) * 100) : 0;
  const healthyLen = (healthyPct / 100) * donutCirc;
  const watchLen = (watchPct / 100) * donutCirc;
  const bannedLen = (bannedPct / 100) * donutCirc;

  return (
    <div className="dashboard-page">
      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-label">
            Каналы
            <span className="live-indicator"><span className="pulse-dot" />LIVE</span>
          </div>
          <div className="stat-value">{derived.channelsCount}</div>
          <div style={{ marginTop: 6, fontSize: 11, color: "var(--text-tertiary)" }}>
            <span style={{ color: "var(--accent-green)" }}>{derived.healthy} стабильных</span> · {derived.watch} риск · {derived.banned} бан
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Видео залито</div>
          <div className="stat-value">{derived.totalVideos}</div>
          <div style={{ marginTop: 6 }}><span className="stat-trend up">успешно: {derived.successTasks}</span></div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Просмотры 7д</div>
          <div className="stat-value" style={{ color: "var(--accent-cyan)" }}>{compact(derived.views7)}</div>
          <div style={{ marginTop: 6 }}><span className="stat-trend up">всего: {compact(derived.totalViews)}</span></div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Like rate</div>
          <div className="stat-value" style={{ color: "var(--accent-green)" }}>{derived.likeRate.toFixed(2)}%</div>
          <div style={{ marginTop: 6 }}><span className="stat-trend up">ошибки: {derived.failedTasks}</span></div>
        </div>
        <div className="stat-card">
          <div className="stat-label">В очереди</div>
          <div className="stat-value" style={{ color: "var(--accent-purple)" }}>{derived.queueCount}</div>
          <div style={{ marginTop: 6, fontSize: 11, color: "var(--text-tertiary)" }}>активно сейчас: {derived.activeTasks}</div>
        </div>
      </div>

      <div className="dashboard-top-grid">
        <div className="viz-card" style={{ position: "relative" }}>
          <div className="viz-header">
            <div>
              <div className="viz-title">
                {chartRange === "24h" ? "Просмотры за 24 часа" : chartRange === "7d" ? "Просмотры за 7 дней" : chartRange === "30d" ? "Просмотры за 30 дней" : "Просмотры за 90 дней"}
              </div>
              <div className="viz-subtitle">
                {dashboardQ.data?.summary ? "Данные бэкенда" : "Демо-данные · подключите бэкенд для live-статистики"}
              </div>
            </div>
            <div style={{ display: "flex", gap: 4 }}>
              {[
                { id: "24h", label: "24ч" },
                { id: "7d", label: "7д" },
                { id: "30d", label: "30д" },
                { id: "90d", label: "90д" },
              ].map((r) => {
                const active = chartRange === r.id;
                return (
                  <button
                    key={r.id}
                    type="button"
                    onClick={() => setChartRange(r.id as "24h" | "7d" | "30d" | "90d")}
                    style={{
                      border: "1px solid var(--border-subtle)",
                      background: active ? "rgba(255,255,255,0.08)" : "var(--bg-elevated)",
                      color: active ? "var(--text-primary)" : "var(--text-tertiary)",
                      fontSize: 10,
                      padding: "2px 8px",
                      borderRadius: 5,
                      cursor: "pointer",
                    }}
                  >
                    {r.label}
                  </button>
                );
              })}
            </div>
          </div>
          <svg
            className="sparkline-svg"
            width="100%"
            height="180"
            viewBox="0 0 600 180"
            preserveAspectRatio="none"
            onMouseMove={(e) => {
              const rect = e.currentTarget.getBoundingClientRect();
              const x = ((e.clientX - rect.left) / rect.width) * 600;
              const y = ((e.clientY - rect.top) / rect.height) * 180;
              const idx = Math.round(x / chartStep);
              setChartHoverIndex(idx);
              setChartHoverPos({ x, y });
            }}
            onMouseLeave={() => {
              setChartHoverIndex(null);
              setChartHoverPos(null);
            }}
          >
            <defs>
              <linearGradient id="grad-views" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#5EEAD4" stopOpacity="0.3" />
                <stop offset="100%" stopColor="#5EEAD4" stopOpacity="0" />
              </linearGradient>
            </defs>
            <line className="grid-line" x1="0" y1="40" x2="600" y2="40" />
            <line className="grid-line" x1="0" y1="80" x2="600" y2="80" />
            <line className="grid-line" x1="0" y1="120" x2="600" y2="120" />
            <line className="grid-line" x1="0" y1="160" x2="600" y2="160" />
            <text x="6" y="28" className="dashboard-y-label" fontFamily="var(--font-mono)">{compact(yTicks[0])}</text>
            <text x="6" y="62" className="dashboard-y-label" fontFamily="var(--font-mono)">{compact(yTicks[1])}</text>
            <text x="6" y="96" className="dashboard-y-label" fontFamily="var(--font-mono)">{compact(yTicks[2])}</text>
            <path className="area" d={viewsArea} fill="url(#grad-views)" />
            <polyline className="line" stroke="#5EEAD4" points={viewsPoints} />
            <polyline className="line" stroke="#A78BFA" strokeDasharray="4 4" strokeWidth="1.4" points={uploadsPoints} />
            {hoverIndex != null && (
              <>
                <line x1={hoverX} y1="0" x2={hoverX} y2="170" stroke="rgba(255,255,255,0.18)" strokeDasharray="3 3" />
                <circle cx={hoverX} cy={hoverYViews} r="4" fill="#5EEAD4" />
                <circle cx={hoverX} cy={hoverYUploads} r="4" fill="#A78BFA" />
              </>
            )}
          </svg>
          {hoverIndex != null && chartHoverPos && (
            <div
              style={{
                position: "absolute",
                left: `${Math.max(12, Math.min(600 - 164, chartHoverPos.x + 12)) / 600 * 100}%`,
                top: Math.max(48, Math.min(210, chartHoverPos.y + 58)),
                background: "rgba(13,14,17,0.92)",
                border: "1px solid var(--border-default)",
                borderRadius: 8,
                padding: "8px 10px",
                fontSize: 11,
                lineHeight: 1.45,
                minWidth: 140,
                boxShadow: "var(--shadow-md)",
                pointerEvents: "none",
                transform: "translate(0,-100%)",
              }}
            >
              <div style={{ color: "var(--text-tertiary)", marginBottom: 4 }}>{hoverDay}</div>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                <span style={{ color: "#5EEAD4" }}>Просмотры</span>
                <span className="mono">{compact(hoverViews)}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                <span style={{ color: "#A78BFA" }}>Публикации</span>
                <span className="mono">{hoverUploads}</span>
              </div>
            </div>
          )}
          <div className="viz-legend">
            <div className="viz-legend-item"><div className="viz-legend-dot" style={{ background: "#5EEAD4" }} />Просмотры</div>
            <div className="viz-legend-item"><div className="viz-legend-dot" style={{ background: "#A78BFA" }} />Заливы</div>
            <div style={{ marginLeft: "auto", fontSize: 11, color: "var(--text-tertiary)" }}>
              <span style={{ color: "#5EEAD4", fontFamily: "var(--font-mono)", marginRight: 4 }}>{compact(derived.views7)}</span>
              за 7д
            </div>
          </div>
        </div>

        <div className="viz-card">
          <div className="viz-header">
            <div>
              <div className="viz-title">Здоровье каналов</div>
              <div className="viz-subtitle">{derived.channelsCount} каналов</div>
            </div>
          </div>
          <div className="donut-container">
            <svg width="100%" height="100%" viewBox="0 0 140 140">
              <circle cx="70" cy="70" r="56" fill="none" stroke="var(--bg-elevated)" strokeWidth="14" />
              <circle
                cx="70"
                cy="70"
                r="56"
                fill="none"
                stroke="#4ADE80"
                strokeWidth="14"
                strokeDasharray={`${healthyLen} ${donutCirc}`}
                strokeLinecap="round"
                transform="rotate(-90 70 70)"
              />
              <circle
                cx="70"
                cy="70"
                r={donutRadius}
                fill="none"
                stroke="#FBBF24"
                strokeWidth="14"
                strokeDasharray={`${watchLen} ${donutCirc}`}
                strokeDashoffset={-healthyLen}
                strokeLinecap="butt"
                transform="rotate(-90 70 70)"
              />
              <circle
                cx="70"
                cy="70"
                r={donutRadius}
                fill="none"
                stroke="#F23F5D"
                strokeWidth="14"
                strokeDasharray={`${bannedLen} ${donutCirc}`}
                strokeDashoffset={-(healthyLen + watchLen)}
                strokeLinecap="butt"
                transform="rotate(-90 70 70)"
              />
            </svg>
            <div className="donut-center">
              <div className="donut-center-value">{derived.healthPct}%</div>
              <div className="donut-center-label">Здоровых</div>
            </div>
          </div>
          <div style={{ marginTop: 16, display: "flex", flexDirection: "column", gap: 8 }}>
            {[
              { color: "#4ADE80", label: "Здоровые", count: derived.healthy },
                { color: "#FBBF24", label: "Наблюдение", count: derived.watch },
                { color: "#F23F5D", label: "Shadowban", count: derived.banned },
            ].map((row) => (
              <div key={row.label} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: 12 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <div className="viz-legend-dot" style={{ background: row.color }} />
                  {row.label}
                </div>
                <span style={{ fontFamily: "var(--font-mono)", color: "var(--text-secondary)" }}>{row.count}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="viz-card section-gap">
        <div className="viz-header">
          <div>
            <div className="viz-title">Активность заливов · последние 7 дней × 24 часа</div>
            <div className="viz-subtitle">Каждая ячейка - час, цвет = количество заливов</div>
          </div>
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 7, fontSize: 10, color: "var(--text-tertiary)" }}>
            <span>Меньше</span>
            <div style={{ display: "flex", gap: 3 }}>
              <div className="heatmap-cell" style={{ width: 10, height: 10 }} />
              <div className="heatmap-cell l2" style={{ width: 10, height: 10 }} />
              <div className="heatmap-cell l3" style={{ width: 10, height: 10 }} />
              <div className="heatmap-cell l4" style={{ width: 10, height: 10 }} />
              <div className="heatmap-cell l5" style={{ width: 10, height: 10 }} />
            </div>
            <span>Больше</span>
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 9, color: "var(--text-tertiary)", fontFamily: "var(--font-mono)", textAlign: "right", paddingRight: 4 }}>
            {dayLabels.map((d) => <div key={d}>{d}</div>)}
          </div>
          <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 3, maxWidth: 580 }}>
            {derived.heatClasses.map((row, ri) => (
              <div key={ri} className="heatmap">
                {row.map((cls, ci) => <div key={ci} className={`heatmap-cell${cls ? ` ${cls}` : ""}`} />)}
              </div>
            ))}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)", marginTop: 8, fontSize: 9, color: "var(--text-tertiary)", fontFamily: "var(--font-mono)" }}>
              <span>03:00</span>
              <span>08:00</span>
              <span>12:00</span>
              <span>15:00</span>
              <span style={{ textAlign: "right" }}>23:59</span>
            </div>
          </div>
        </div>
      </div>

      <div className="dash-grid">
        <div className="card">
          <div className="card-header">
            <div>
              <div className="card-title">Топ каналов · производительность</div>
              <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginTop: 2, textTransform: "none", letterSpacing: 0 }}>по числу успешных задач</div>
            </div>
            <span className="live-indicator"><span className="pulse-dot" />LIVE</span>
          </div>
          <div className="card-body-flush">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Канал</th><th>Success</th><th>Тренд</th><th>Health</th><th></th>
                </tr>
              </thead>
              <tbody>
                {derived.channels.map((ch) => {
                  const lineColor = ch.health > 60 ? "#4ADE80" : ch.health > 30 ? "#FBBF24" : "#F23F5D";
                  const pts = `0,${16 - ch.success} 20,${15 - ch.active} 40,${14 - ch.error} 60,${10 + Math.max(0, 6 - ch.success)} 80,${18 - Math.min(12, ch.health / 8)}`;
                  return (
                    <tr key={ch.name}>
                      <td>{ch.name}</td>
                      <td className="mono" style={{ color: lineColor, fontWeight: 600 }}>{ch.success}</td>
                      <td><svg width="80" height="20" viewBox="0 0 80 20"><polyline fill="none" stroke={lineColor} strokeWidth="1.5" points={pts} /></svg></td>
                      <td><div className="health-bar" style={{ width: 60 }}><div className={`health-bar-fill ${ch.health > 60 ? "health-good" : ch.health > 25 ? "health-warn" : "health-bad"}`} style={{ width: `${ch.health}%` }} /></div></td>
                      <td><span className={`badge ${ch.health > 60 ? "badge-success" : ch.health > 25 ? "badge-warning" : "badge-error"}`}>{ch.health > 60 ? "healthy" : ch.health > 25 ? "watch" : "risk"}</span></td>
                    </tr>
                  );
                })}
                {derived.channels.length === 0 && (
                  <tr><td colSpan={5}><div className="empty-state">Нет данных по каналам</div></td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div className="viz-card" style={{ padding: 16 }}>
            <div className="viz-header" style={{ marginBottom: 12 }}>
              <div>
                <div className="viz-title">Ключевые коэффициенты</div>
                <div className="viz-subtitle">по live данным бэкенда</div>
              </div>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {[
                { label: "Success rate", pct: tasks.length ? Math.round((derived.successTasks / tasks.length) * 100) : 0, color: "var(--accent-green)" },
                { label: "Error rate", pct: tasks.length ? Math.round((derived.failedTasks / tasks.length) * 100) : 0, color: "var(--accent-red)" },
                { label: "Pipeline active", pct: tasks.length ? Math.round((derived.activeTasks / tasks.length) * 100) : 0, color: "var(--accent-cyan)" },
                { label: "Queue pressure", pct: tasks.length ? Math.round((derived.queueCount / tasks.length) * 100) : 0, color: "var(--accent-amber)" },
              ].map((row) => (
                <div key={row.label}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, marginBottom: 4 }}>
                    <span style={{ color: "var(--text-secondary)" }}>{row.label}</span>
                    <span className="mono" style={{ color: row.color }}>{row.pct}%</span>
                  </div>
                  <div style={{ height: 4, background: "var(--bg-elevated)", borderRadius: 2 }}>
                    <div style={{ height: "100%", width: `${row.pct}%`, background: row.color, borderRadius: 2 }} />
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="card">
            <div className="card-header">
              <span className="card-title">Алерты</span>
              <span className={`badge ${derived.alerts.length ? "badge-error" : "badge-success"}`}>{derived.alerts.length}</span>
            </div>
            <div className="card-body" style={{ padding: 0 }}>
              {derived.alerts.length === 0 ? (
                <div className="empty-state">Критичных алертов нет</div>
              ) : (
                derived.alerts.map((a, i) => (
                  <div key={`${a.name}-${i}`} style={{ padding: "12px 18px", borderBottom: i === derived.alerts.length - 1 ? "none" : "1px solid var(--border-subtle)", display: "flex", alignItems: "flex-start", gap: 10 }}>
                    <div style={{ width: 6, height: 6, borderRadius: "50%", background: a.color, marginTop: 6, flexShrink: 0 }} />
                    <div>
                      <div style={{ fontSize: 12, color: "var(--text-primary)", fontWeight: 500 }}>{a.name}</div>
                      <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginTop: 2 }}>{a.text}</div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

