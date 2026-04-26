/**
 * Skeleton loading components — заменяют «Загрузка…» во всех страницах.
 *
 * Использование:
 *   <SkeletonTable rows={5} cols={4} />          — таблица данных
 *   <SkeletonStatGrid count={4} />               — строка стат-карточек
 *   <SkeletonList rows={4} />                    — список (кампании, браузеры)
 *   <SkeletonText lines={3} />                   — параграф текста
 *   <Skeleton width="60%" height={16} />         — произвольный блок
 */

import type { CSSProperties } from "react";

// ── Base ─────────────────────────────────────────────────────────────────────

type SkeletonProps = {
  width?: string | number;
  height?: string | number;
  radius?: string | number;
  style?: CSSProperties;
  className?: string;
};

export function Skeleton({ width = "100%", height = 14, radius = "var(--radius-md)", style, className }: SkeletonProps) {
  return (
    <div
      className={`skeleton${className ? ` ${className}` : ""}`}
      style={{
        width,
        height,
        borderRadius: radius,
        flexShrink: 0,
        ...style,
      }}
    />
  );
}

// ── Text lines ────────────────────────────────────────────────────────────────

export function SkeletonText({ lines = 3, gap = 10 }: { lines?: number; gap?: number }) {
  const widths = ["92%", "78%", "85%", "65%", "88%", "72%", "80%"];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap }}>
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} width={widths[i % widths.length]} height={13} />
      ))}
    </div>
  );
}

// ── Stat grid ─────────────────────────────────────────────────────────────────

export function SkeletonStatGrid({ count = 4, cols }: { count?: number; cols?: number }) {
  const gridCols = cols ?? count;
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: `repeat(${gridCols}, 1fr)`,
        gap: 12,
        marginBottom: 24,
      }}
    >
      {Array.from({ length: count }, (_, i) => (
        <div
          key={i}
          className="stat-card"
          style={{ display: "flex", flexDirection: "column", gap: 10, padding: 16 }}
        >
          <Skeleton width="55%" height={11} />
          <Skeleton width="40%" height={32} />
          <Skeleton width="30%" height={10} />
        </div>
      ))}
    </div>
  );
}

// ── Table rows ────────────────────────────────────────────────────────────────

const COL_WIDTHS = [
  ["15%", "35%", "20%", "15%", "15%"],
  ["10%", "40%", "25%", "25%"],
  ["8%", "30%", "22%", "18%", "12%", "10%"],
];

export function SkeletonTable({ rows = 5, cols = 4 }: { rows?: number; cols?: number }) {
  const widths = COL_WIDTHS[Math.min(cols, 3) - 2] ?? COL_WIDTHS[1];
  return (
    <div style={{ padding: "4px 0" }}>
      {Array.from({ length: rows }, (_, ri) => (
        <div
          key={ri}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 16,
            padding: "13px 16px",
            borderBottom: "1px solid var(--border-subtle)",
            animationDelay: `${ri * 60}ms`,
          }}
        >
          {Array.from({ length: cols }, (_, ci) => (
            <Skeleton
              key={ci}
              width={widths[ci % widths.length] ?? "20%"}
              height={13}
              style={{ animationDelay: `${(ri * cols + ci) * 30}ms` }}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

// ── List items ────────────────────────────────────────────────────────────────

export function SkeletonList({ rows = 4, showAvatar = false }: { rows?: number; showAvatar?: boolean }) {
  return (
    <div style={{ padding: "4px 0" }}>
      {Array.from({ length: rows }, (_, i) => (
        <div
          key={i}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            padding: "14px 16px",
            borderBottom: "1px solid var(--border-subtle)",
          }}
        >
          {showAvatar && (
            <Skeleton width={32} height={32} radius="50%" style={{ flexShrink: 0 }} />
          )}
          <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 7 }}>
            <Skeleton width={`${55 + (i % 3) * 12}%`} height={13} />
            <Skeleton width={`${30 + (i % 4) * 8}%`} height={11} />
          </div>
          <Skeleton width={64} height={26} radius="var(--radius-md)" />
        </div>
      ))}
    </div>
  );
}

// ── Card body ─────────────────────────────────────────────────────────────────

export function SkeletonCard({ lines = 4 }: { lines?: number }) {
  return (
    <div style={{ padding: "16px 20px", display: "flex", flexDirection: "column", gap: 12 }}>
      <SkeletonText lines={lines} />
    </div>
  );
}

// ── Inline (for small inline spots) ──────────────────────────────────────────

export function SkeletonInline({ width = 80 }: { width?: number }) {
  return <Skeleton width={width} height={13} style={{ display: "inline-block" }} />;
}
