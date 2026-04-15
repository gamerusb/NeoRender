import type { StatusLine } from "@/lib/systemStatus";

export function SystemStatusLines({ lines }: { lines: StatusLine[] }) {
  if (!lines.length) {
    return <div className="empty-state" style={{ padding: "12px 0" }}>Загрузка…</div>;
  }
  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
      {lines.map((row) => (
        <div key={row.label} className="status-line">
          <span className="status-line-label">{row.label}</span>
          <span className={`mini-badge ${row.kind}`}>{row.value}</span>
        </div>
      ))}
    </div>
  );
}
