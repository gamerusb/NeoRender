export function ProxyPage() {
  const proxies = [
    { dot:"alive", ip:"103.152.34.12:8080", geo:"🇰🇷 Seoul",   lat:"42ms",    latColor:"var(--accent-green)", badge:"badge-success", ch:"KR_shorts_01" },
    { dot:"alive", ip:"103.152.34.15:8080", geo:"🇰🇷 Busan",   lat:"51ms",    latColor:"var(--accent-green)", badge:"badge-success", ch:"KR_shorts_02" },
    { dot:"alive", ip:"103.152.34.18:8080", geo:"🇰🇷 Seoul",   lat:"38ms",    latColor:"var(--accent-green)", badge:"badge-info",    ch:"KR_casino_03" },
    { dot:"slow",  ip:"185.234.12.90:3128", geo:"🇰🇷 Incheon", lat:"340ms",   latColor:"var(--accent-amber)", badge:"badge-warning", ch:"KR_shorts_04" },
    { dot:"dead",  ip:"45.77.88.102:1080",  geo:"🇹🇭 Bangkok", lat:"timeout", latColor:"var(--accent-red)",   badge:"badge-error",   ch:"TH_react_01"  },
    { dot:"alive", ip:"103.152.34.22:8080", geo:"🇰🇷 Seoul",   lat:"45ms",    latColor:"var(--accent-green)", badge:"badge-neutral", ch:"Резерв" },
  ];

  return (
    <div className="page">
      <div className="stats-grid-4">
        <div className="stat-card"><div className="stat-label">Всего прокси</div><div className="stat-value">8</div></div>
        <div className="stat-card"><div className="stat-label">Alive</div><div className="stat-value green">6</div></div>
        <div className="stat-card"><div className="stat-label">Dead</div><div className="stat-value red">1</div></div>
        <div className="stat-card"><div className="stat-label">Slow</div><div className="stat-value amber">1</div></div>
      </div>
      <div className="settings-grid">
        <div>
          <div className="card">
            <div className="card-header"><span className="card-title">Список прокси</span><button className="btn btn-sm btn-cyan">Проверить все</button></div>
            <div className="card-body">
              {proxies.map((p) => (
                <div key={p.ip} className="proxy-row">
                  <div className={`proxy-dot ${p.dot}`}></div>
                  <div className="proxy-ip">{p.ip}</div>
                  <div className="proxy-geo">{p.geo}</div>
                  <div className="proxy-latency" style={{ color:p.latColor }}>{p.lat}</div>
                  <span className={`badge ${p.badge}`}>{p.ch}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
        <div>
          <div className="card section-gap">
            <div className="card-header"><span className="card-title">Алерты прокси</span></div>
            <div className="card-body" style={{ fontSize:12 }}>
              <div style={{ padding:"8px 0", borderBottom:"1px solid var(--border-subtle)", color:"var(--accent-red)" }}>45.77.88.102 — timeout (TH_react_01 без прокси!)</div>
              <div style={{ padding:"8px 0", borderBottom:"1px solid var(--border-subtle)", color:"var(--accent-amber)" }}>185.234.12.90 — latency 340ms (&gt;200ms порог)</div>
              <div style={{ padding:"8px 0", color:"var(--accent-amber)" }}>TH_react_01 гео: Bangkok, прокси: Bangkok ✓ (но dead)</div>
            </div>
          </div>
          <div className="card">
            <div className="card-header"><span className="card-title">Проверка гео-совпадения</span></div>
            <div className="card-body">
              <div style={{ display:"flex", alignItems:"center", gap:10, marginBottom:12 }}><span style={{ fontSize:13, color:"var(--text-secondary)" }}>Автопроверка IP-гео</span><div className="toggle-switch on"></div></div>
              <div style={{ display:"flex", alignItems:"center", gap:10, marginBottom:12 }}><span style={{ fontSize:13, color:"var(--text-secondary)" }}>Алерт при несовпадении</span><div className="toggle-switch on"></div></div>
              <div className="form-group"><label className="form-label">Макс. latency (ms)</label><input className="form-input" defaultValue="200" style={{ fontFamily:"var(--font-mono)" }}/></div>
              <button className="btn btn-primary">Сохранить</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
