"""Rebuilds DashboardPage.tsx with all 8 UX improvements."""
import pathlib

src = pathlib.Path("frontend/src/pages/DashboardPage.tsx")
text = src.read_text(encoding="utf-8")

# 1. Add useNavigate import
text = text.replace(
    'import { useMemo, useState } from "react";',
    'import { useMemo, useState } from "react";\nimport { useNavigate } from "react-router-dom";',
    1
)

# 2. Extend TaskRow type
text = text.replace(
    """type TaskRow = {
  id: number;
  target_profile?: string;
  status?: string;
  created_at?: string;
};""",
    """type TaskRow = {
  id: number;
  target_profile?: string;
  status?: string;
  created_at?: string;
  updated_at?: string;
  original_video?: string;
};""",
    1
)

# 3. Add useNavigate hook
text = text.replace(
    '  const { tenantId } = useTenant();',
    '  const { tenantId } = useTenant();\n  const navigate = useNavigate();',
    1
)

# 4. Replace return statement
marker = '\n  return (\n    <div className="dashboard-page">'
return_idx = text.index(marker) + 1  # +1 to skip the leading newline
preamble = text[:return_idx]

new_jsx = r"""  // UI-only helpers
  const isDemoData = analytics.length === 0 && tasks.length === 0;
  const recentTasks = [...tasks]
    .sort((a, b) => new Date(b.updated_at ?? b.created_at ?? 0).getTime() - new Date(a.updated_at ?? a.created_at ?? 0).getTime())
    .slice(0, 8);
  const relTime = (ts?: string) => {
    if (!ts) return "";
    const d = Date.now() - new Date(ts).getTime();
    if (d < 60_000) return "только что";
    if (d < 3_600_000) return `${Math.floor(d / 60_000)}м назад`;
    if (d < 86_400_000) return `${Math.floor(d / 3_600_000)}ч назад`;
    return `${Math.floor(d / 86_400_000)}д назад`;
  };
  const taskSt = (s?: string) =>
    s === "success" ? "ok" : s === "error" ? "err" : (s === "rendering" || s === "uploading") ? "active" : "pend";
  const taskLabel = (s?: string) =>
    s === "success" ? "done" : s === "error" ? "error" : s === "rendering" ? "render…" : s === "uploading" ? "upload…" : "pending";
  const xIdxs = chartLabels.length <= 7
    ? Array.from({ length: chartLabels.length }, (_, i) => i)
    : [0, Math.floor(chartLabels.length * 0.2), Math.floor(chartLabels.length * 0.4),
       Math.floor(chartLabels.length * 0.6), Math.floor(chartLabels.length * 0.8), chartLabels.length - 1];

  return (
    <div className="dashboard-page">
      <style>{`
        .db2-demo-banner{background:rgba(251,191,36,.06);border:1px solid rgba(251,191,36,.2);border-radius:var(--radius-lg);padding:10px 16px;margin-bottom:14px;font-size:11.5px;color:var(--accent-amber);display:flex;align-items:center;gap:8px}
        .db2-alert-bar{background:rgba(242,63,93,.05);border:1px solid rgba(242,63,93,.2);border-radius:var(--radius-lg);padding:10px 16px;margin-bottom:14px;display:flex;align-items:center;gap:14px;flex-wrap:wrap}
        .db2-alert-item{display:flex;align-items:center;gap:7px;font-size:11.5px;color:var(--text-secondary)}
        .db2-alert-dot{width:7px;height:7px;border-radius:50%;flex-shrink:0}
        .db2-alert-cta{margin-left:auto;padding:5px 12px;border-radius:6px;border:1px solid rgba(242,63,93,.3);background:rgba(242,63,93,.08);color:#F23F5D;font-size:11.5px;font-weight:600;cursor:pointer;transition:all 160ms;font-family:inherit;white-space:nowrap}
        .db2-alert-cta:hover{background:rgba(242,63,93,.14)}
        .db2-hero-row{display:grid;grid-template-columns:1fr 1fr 1fr 1fr 220px;gap:12px;margin-bottom:14px}
        .db2-hero-metric{background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-xl);padding:16px 18px}
        .db2-hero-metric.is-primary{border-color:rgba(94,234,212,.22);background:linear-gradient(135deg,rgba(94,234,212,.04) 0%,transparent 100%)}
        .db2-hero-label{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.7px;color:var(--text-tertiary);margin-bottom:8px}
        .db2-hero-value{font-size:28px;font-weight:800;color:var(--text-primary);line-height:1;margin-bottom:6px;font-family:var(--font-mono);letter-spacing:-.5px}
        .db2-hero-sub{font-size:11px;color:var(--text-tertiary);line-height:1.4}
        .db2-quick-actions{background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-xl);padding:14px;display:flex;flex-direction:column;gap:10px}
        .db2-qa-title{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.7px;color:var(--text-tertiary)}
        .db2-qa-buttons{display:grid;grid-template-columns:1fr 1fr;gap:6px}
        .db2-qa-btn{display:flex;align-items:center;gap:6px;padding:8px 10px;border-radius:8px;border:1px solid var(--border-subtle);background:var(--bg-elevated);cursor:pointer;transition:all 160ms;font-family:inherit;font-size:11.5px;color:var(--text-secondary);white-space:nowrap;justify-content:flex-start}
        .db2-qa-btn:hover{border-color:var(--border-strong);background:var(--bg-hover);color:var(--text-primary)}
        .db2-qa-btn.primary{border-color:rgba(94,234,212,.3);background:rgba(94,234,212,.07);color:var(--accent-cyan)}
        .db2-qa-btn.primary:hover{border-color:rgba(94,234,212,.5);background:rgba(94,234,212,.12)}
        .db2-qa-icon{font-size:14px;line-height:1;flex-shrink:0}
        .db2-range-seg{display:flex;gap:2px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.06);border-radius:8px;padding:3px;flex-shrink:0}
        .db2-range-btn{padding:5px 12px;border-radius:6px;font-size:11.5px;font-weight:600;color:var(--text-secondary);background:transparent;border:none;cursor:pointer;transition:all 160ms;font-family:inherit}
        .db2-range-btn.active{background:var(--bg-elevated);color:var(--text-primary);box-shadow:0 1px 4px rgba(0,0,0,.35)}
        .db2-x-labels{display:flex;padding:4px 0 0}
        .db2-x-label{font-size:9px;color:var(--text-tertiary);font-family:var(--font-mono);flex:1}
        .db2-donut-hint{font-size:10px;color:var(--text-tertiary);text-align:center;margin-top:6px;opacity:.65}
        .db2-task-row{display:flex;align-items:center;gap:10px;padding:8px 16px;border-bottom:1px solid var(--border-subtle)}
        .db2-task-row:last-child{border-bottom:none}
        .db2-task-dot{width:7px;height:7px;border-radius:50%;flex-shrink:0}
        .db2-task-dot.ok{background:#4ADE80}
        .db2-task-dot.err{background:#F23F5D}
        .db2-task-dot.active{background:#5EEAD4;box-shadow:0 0 0 3px rgba(94,234,212,.2);animation:db2-pulse 2s infinite}
        .db2-task-dot.pend{background:rgba(255,255,255,.2)}
        .db2-task-meta{flex:1;min-width:0}
        .db2-task-name{font-size:10.5px;color:var(--text-secondary);font-family:var(--font-mono);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:block}
        .db2-task-time{font-size:9px;color:var(--text-tertiary);display:block;margin-top:1px}
        .db2-task-badge{font-size:8.5px;font-weight:700;font-family:var(--font-mono);padding:2px 6px;border-radius:3px;flex-shrink:0}
        .db2-task-badge.ok{background:rgba(74,222,128,.1);color:#4ADE80;border:1px solid rgba(74,222,128,.2)}
        .db2-task-badge.err{background:rgba(242,63,93,.1);color:#F23F5D;border:1px solid rgba(242,63,93,.2)}
        .db2-task-badge.active{background:rgba(94,234,212,.1);color:#5EEAD4;border:1px solid rgba(94,234,212,.2)}
        .db2-task-badge.pend{background:rgba(255,255,255,.04);color:var(--text-tertiary);border:1px solid rgba(255,255,255,.08)}
        @keyframes db2-pulse{0%,100%{box-shadow:0 0 0 3px rgba(94,234,212,.2)}50%{box-shadow:0 0 0 5px rgba(94,234,212,.08)}}
      `}</style>

      {isDemoData && (
        <div className="db2-demo-banner">
          <span>⚠</span>
          <span>Демо-режим — реальных данных пока нет. Добавьте каналы и запустите первый рендер чтобы увидеть live-статистику.</span>
        </div>
      )}

      {derived.alerts.length > 0 && (
        <div className="db2-alert-bar">
          {derived.alerts.map((a, i) => (
            <div key={i} className="db2-alert-item">
              <div className="db2-alert-dot" style={{ background: a.color }} />
              <strong style={{ color: "var(--text-primary)" }}>{a.name}</strong>
              <span>{a.text}</span>
            </div>
          ))}
          <button type="button" className="db2-alert-cta" onClick={() => navigate("/accounts")}>
            Перейти к каналам →
          </button>
        </div>
      )}

      <div className="db2-hero-row">
        <div className="db2-hero-metric is-primary">
          <div className="db2-hero-label">Просмотры 7д</div>
          <div className="db2-hero-value" style={{ color: "var(--accent-cyan)" }}>{compact(derived.views7)}</div>
          <div className="db2-hero-sub">всего {compact(derived.totalViews)} · like {derived.likeRate.toFixed(2)}%</div>
        </div>
        <div className="db2-hero-metric">
          <div className="db2-hero-label">В очереди</div>
          <div className="db2-hero-value" style={{ color: "var(--accent-purple)" }}>{derived.queueCount}</div>
          <div className="db2-hero-sub">активно прямо сейчас: <strong style={{ color: "var(--text-secondary)" }}>{derived.activeTasks}</strong></div>
        </div>
        <div className="db2-hero-metric">
          <div className="db2-hero-label">Каналы</div>
          <div className="db2-hero-value">{derived.channelsCount}</div>
          <div className="db2-hero-sub">
            <span style={{ color: "#4ADE80" }}>{derived.healthy}</span>{" здоровых · "}{derived.watch} риск · {derived.banned} бан
          </div>
        </div>
        <div className="db2-hero-metric">
          <div className="db2-hero-label">Видео залито</div>
          <div className="db2-hero-value">{derived.totalVideos}</div>
          <div className="db2-hero-sub">успешно {derived.successTasks} · ошибок {derived.failedTasks}</div>
        </div>
        <div className="db2-quick-actions">
          <div className="db2-qa-title">Быстрые действия</div>
          <div className="db2-qa-buttons">
            <button type="button" className="db2-qa-btn primary" onClick={() => navigate("/uniqualizer")}>
              <span className="db2-qa-icon">🎬</span> Рендер
            </button>
            <button type="button" className="db2-qa-btn" onClick={() => navigate("/queue")}>
              <span className="db2-qa-icon">⚡</span> Очередь
            </button>
            <button type="button" className="db2-qa-btn" onClick={() => navigate("/analytics")}>
              <span className="db2-qa-icon">📊</span> Аналитика
            </button>
            <button type="button" className="db2-qa-btn" onClick={() => navigate("/accounts")}>
              <span className="db2-qa-icon">📺</span> Каналы
            </button>
          </div>
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
                {isDemoData ? "Демо-данные · подключите бэкенд для live-статистики" : "Данные бэкенда"}
              </div>
            </div>
            <div className="db2-range-seg">
              {([{ id: "24h", label: "24ч" }, { id: "7d", label: "7д" }, { id: "30d", label: "30д" }, { id: "90d", label: "90д" }] as const).map((r) => (
                <button key={r.id} type="button" className={`db2-range-btn${chartRange === r.id ? " active" : ""}`}
                  onClick={() => setChartRange(r.id)}>
                  {r.label}
                </button>
              ))}
            </div>
          </div>
          <svg className="sparkline-svg" width="100%" height="180" viewBox="0 0 600 180" preserveAspectRatio="none"
            onMouseMove={(e) => {
              const rect = e.currentTarget.getBoundingClientRect();
              const x = ((e.clientX - rect.left) / rect.width) * 600;
              const y = ((e.clientY - rect.top) / rect.height) * 180;
              setChartHoverIndex(Math.round(x / chartStep));
              setChartHoverPos({ x, y });
            }}
            onMouseLeave={() => { setChartHoverIndex(null); setChartHoverPos(null); }}
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
          <div className="db2-x-labels">
            {xIdxs.map((idx, pos) => (
              <span key={idx} className="db2-x-label" style={{ textAlign: pos === 0 ? "left" : pos === xIdxs.length - 1 ? "right" : "center" }}>
                {chartLabels[idx] ?? ""}
              </span>
            ))}
          </div>
          {hoverIndex != null && chartHoverPos && (
            <div style={{ position: "absolute", left: `${(Math.max(12, Math.min(600 - 164, chartHoverPos.x + 12)) / 600) * 100}%`, top: Math.max(48, Math.min(210, chartHoverPos.y + 58)), background: "rgba(13,14,17,0.92)", border: "1px solid var(--border-default)", borderRadius: 8, padding: "8px 10px", fontSize: 11, lineHeight: 1.45, minWidth: 140, boxShadow: "var(--shadow-md)", pointerEvents: "none", transform: "translate(0,-100%)" }}>
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
              <span style={{ color: "#5EEAD4", fontFamily: "var(--font-mono)", marginRight: 4 }}>{compact(derived.views7)}</span>за 7д
            </div>
          </div>
        </div>

        <div className="viz-card" style={{ cursor: "pointer" }} onClick={() => navigate("/accounts")} title="Перейти к управлению каналами">
          <div className="viz-header">
            <div>
              <div className="viz-title">Здоровье каналов</div>
              <div className="viz-subtitle">{derived.channelsCount} каналов</div>
            </div>
          </div>
          <div className="donut-container">
            <svg width="100%" height="100%" viewBox="0 0 140 140">
              <circle cx="70" cy="70" r="56" fill="none" stroke="var(--bg-elevated)" strokeWidth="14" />
              <circle cx="70" cy="70" r="56" fill="none" stroke="#4ADE80" strokeWidth="14"
                strokeDasharray={`${healthyLen} ${donutCirc}`} strokeLinecap="round" transform="rotate(-90 70 70)" />
              <circle cx="70" cy="70" r={donutRadius} fill="none" stroke="#FBBF24" strokeWidth="14"
                strokeDasharray={`${watchLen} ${donutCirc}`} strokeDashoffset={-healthyLen}
                strokeLinecap="butt" transform="rotate(-90 70 70)" />
              <circle cx="70" cy="70" r={donutRadius} fill="none" stroke="#F23F5D" strokeWidth="14"
                strokeDasharray={`${bannedLen} ${donutCirc}`} strokeDashoffset={-(healthyLen + watchLen)}
                strokeLinecap="butt" transform="rotate(-90 70 70)" />
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
          <div className="db2-donut-hint">Нажмите для перехода к каналам →</div>
        </div>
      </div>

      <div className="viz-card section-gap">
        <div className="viz-header">
          <div>
            <div className="viz-title">Активность заливов · последние 7 дней × 24 часа</div>
            <div className="viz-subtitle">Каждая ячейка — час, цвет = количество заливов</div>
          </div>
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 7, fontSize: 10, color: "var(--text-tertiary)" }}>
            <span>Меньше</span>
            <div style={{ display: "flex", gap: 3 }}>
              {["", "l2", "l3", "l4", "l5"].map((c) => <div key={c} className={`heatmap-cell${c ? " " + c : ""}`} style={{ width: 10, height: 10 }} />)}
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
              <span>03:00</span><span>08:00</span><span>12:00</span><span>15:00</span>
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
              <thead><tr><th>Канал</th><th>Success</th><th>Тренд</th><th>Health</th><th></th></tr></thead>
              <tbody>
                {derived.channels.map((ch) => {
                  const lineColor = ch.health > 60 ? "#4ADE80" : ch.health > 30 ? "#FBBF24" : "#F23F5D";
                  const pts = `0,${16 - ch.success} 20,${15 - ch.active} 40,${14 - ch.error} 60,${10 + Math.max(0, 6 - ch.success)} 80,${18 - Math.min(12, ch.health / 8)}`;
                  return (
                    <tr key={ch.name}>
                      <td>{ch.name}</td>
                      <td className="mono" style={{ color: lineColor, fontWeight: 600 }}>{ch.success}</td>
                      <td><svg width="80" height="20" viewBox="0 0 80 20"><polyline fill="none" stroke={lineColor} strokeWidth="1.5" points={pts} /></svg></td>
                      <td>
                        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                          <div className="health-bar" style={{ width: 60 }}>
                            <div className={`health-bar-fill ${ch.health > 60 ? "health-good" : ch.health > 25 ? "health-warn" : "health-bad"}`} style={{ width: `${ch.health}%` }} />
                          </div>
                          <span className="mono" style={{ fontSize: 10, color: "var(--text-tertiary)" }}>{Math.max(0, Math.min(100, Number(ch.health || 0))).toFixed(0)}%</span>
                        </div>
                      </td>
                      <td><span className={`badge ${ch.health > 60 ? "badge-success" : ch.health > 25 ? "badge-warning" : "badge-error"}`}>{ch.health > 60 ? "healthy" : ch.health > 25 ? "watch" : "risk"}</span></td>
                    </tr>
                  );
                })}
                {derived.channels.length === 0 && <tr><td colSpan={5}><div className="empty-state">Нет данных по каналам</div></td></tr>}
              </tbody>
            </table>
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div className="viz-card" style={{ padding: 16 }}>
            <div className="viz-header" style={{ marginBottom: 12 }}>
              <div className="viz-title">Ключевые коэффициенты</div>
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
              <span className="card-title">Последние задачи</span>
              <span className="live-indicator"><span className="pulse-dot" />LIVE</span>
            </div>
            {recentTasks.length === 0 ? (
              <div className="empty-state">Нет задач</div>
            ) : recentTasks.map((t) => {
              const st = taskSt(t.status);
              return (
                <div key={t.id} className="db2-task-row">
                  <div className={`db2-task-dot ${st}`} />
                  <div className="db2-task-meta">
                    <span className="db2-task-name">{t.original_video ? t.original_video.split(/[/\\]/).pop() : `Задача #${t.id}`}</span>
                    <span className="db2-task-time">{relTime(t.updated_at ?? t.created_at)}</span>
                  </div>
                  <span className={`db2-task-badge ${st}`}>{taskLabel(t.status)}</span>
                </div>
              );
            })}
          </div>

          <div className="card">
            <div className="card-header">
              <span className="card-title">Алерты</span>
              <span className={`badge ${derived.alerts.length ? "badge-error" : "badge-success"}`}>{derived.alerts.length}</span>
            </div>
            <div className="card-body" style={{ padding: 0 }}>
              {derived.alerts.length === 0 ? (
                <div className="empty-state">Критичных алертов нет</div>
              ) : derived.alerts.map((a, i) => (
                <div key={`${a.name}-${i}`} style={{ padding: "12px 18px", borderBottom: i === derived.alerts.length - 1 ? "none" : "1px solid var(--border-subtle)", display: "flex", alignItems: "flex-start", gap: 10 }}>
                  <div style={{ width: 6, height: 6, borderRadius: "50%", background: a.color, marginTop: 6, flexShrink: 0 }} />
                  <div>
                    <div style={{ fontSize: 12, color: "var(--text-primary)", fontWeight: 500 }}>{a.name}</div>
                    <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginTop: 2 }}>{a.text}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
"""

content = preamble + new_jsx
src.write_text(content, encoding="utf-8")
print(f"Done. Written {len(content.splitlines())} lines.")
