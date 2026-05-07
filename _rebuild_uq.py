"""Rebuilds UniqualizerPage.tsx: keeps lines 1-1001 (logic) and replaces the return statement."""
import pathlib, sys

src = pathlib.Path("frontend/src/pages/UniqualizerPage.tsx")
lines = src.read_text(encoding="utf-8").splitlines(keepends=True)
top = "".join(lines[:1001])  # everything up to (not including) the return statement

new_jsx = r"""
  return (
    <section className="page uq2-page">
      <style>{`
        .uq2-page{display:flex;flex-direction:column;height:100%;overflow:hidden}
        .uq2-wrapper{flex:1;overflow-y:auto;overflow-x:hidden;padding:18px 22px 24px}
        .uq2-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:18px;gap:12px;flex-wrap:wrap}
        .uq2-title-row{display:flex;align-items:baseline;gap:10px}
        .uq2-title{font-size:20px;font-weight:800;letter-spacing:-.5px;background:linear-gradient(120deg,#EDEEF0 0%,#6e87aa 100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
        .uq2-version{font-family:'IBM Plex Mono',monospace;font-size:10px;font-weight:700;padding:2px 8px;border-radius:20px;background:rgba(242,63,93,0.1);color:#F23F5D;border:1px solid rgba(242,63,93,0.2)}
        .uq2-mode-toggle{display:flex;gap:2px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.06);border-radius:8px;padding:3px}
        .uq2-mode-btn{padding:5px 14px;border-radius:6px;font-size:12px;font-weight:600;color:var(--text-secondary);background:transparent;border:none;cursor:pointer;transition:all 160ms}
        .uq2-mode-btn.active{background:var(--bg-elevated);color:var(--text-primary);box-shadow:0 1px 4px rgba(0,0,0,.35)}
        .uq2-stepper{display:flex;align-items:flex-start;margin-bottom:18px}
        .uq2-step{display:flex;flex-direction:column;align-items:center;gap:5px;cursor:pointer;transition:opacity 160ms;flex:0 0 auto;min-width:56px}
        .uq2-step.locked{pointer-events:none;opacity:.38}
        .uq2-step-dot{width:30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;border:1.5px solid rgba(255,255,255,0.1);background:var(--bg-surface);color:var(--text-tertiary);transition:all 200ms;position:relative;z-index:1}
        .uq2-step.active .uq2-step-dot{border-color:var(--accent-cyan);color:var(--accent-cyan);box-shadow:0 0 0 3px rgba(94,234,212,.1),0 0 12px rgba(94,234,212,.18)}
        .uq2-step.done .uq2-step-dot{background:rgba(94,234,212,.1);border-color:rgba(94,234,212,.45);color:var(--accent-cyan)}
        .uq2-step-label{font-size:10px;font-weight:600;color:var(--text-tertiary);text-align:center;white-space:nowrap}
        .uq2-step.active .uq2-step-label,.uq2-step.done .uq2-step-label{color:var(--text-secondary)}
        .uq2-step-conn{flex:1;display:flex;align-items:center;padding-top:15px}
        .uq2-step-line{height:1.5px;width:100%;background:rgba(255,255,255,0.07);border-radius:1px;transition:background 400ms}
        .uq2-step-line.done{background:rgba(94,234,212,.28)}
        .uq2-layout{display:grid;grid-template-columns:1fr 272px;gap:14px;align-items:start}
        .uq2-main{display:flex;flex-direction:column;gap:14px;min-width:0}
        .uq2-card{background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-xl);overflow:hidden}
        .uq2-card-head{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;border-bottom:1px solid var(--border-subtle);gap:10px;flex-wrap:wrap}
        .uq2-card-title{font-size:12.5px;font-weight:700;color:var(--text-primary);display:flex;align-items:center;gap:7px}
        .uq2-card-num{font-family:'IBM Plex Mono',monospace;font-size:9.5px;font-weight:700;background:rgba(94,234,212,.1);color:var(--accent-cyan);border:1px solid rgba(94,234,212,.2);border-radius:4px;padding:1px 6px}
        .uq2-card-body{padding:16px;display:flex;flex-direction:column;gap:14px}
        .uq2-dropzone{border:1.5px dashed rgba(255,255,255,.1);border-radius:var(--radius-xl);padding:36px 20px;text-align:center;cursor:pointer;transition:all 200ms;background:linear-gradient(135deg,rgba(255,255,255,.02) 0%,transparent 100%);position:relative;overflow:hidden}
        .uq2-dropzone::before{content:'';position:absolute;inset:0;background:radial-gradient(ellipse 60% 40% at 50% 100%,rgba(94,234,212,.04),transparent);pointer-events:none}
        .uq2-dropzone:hover,.uq2-dropzone.drag{border-color:rgba(94,234,212,.35);background:rgba(94,234,212,.02)}
        .uq2-dropzone.drag{border-color:var(--accent-cyan)}
        .uq2-dz-icon{color:rgba(94,234,212,.45);margin-bottom:10px}
        .uq2-dz-title{font-size:14px;font-weight:700;color:var(--text-primary);margin-bottom:5px}
        .uq2-dz-sub{font-size:11.5px;color:var(--text-tertiary)}
        .uq2-filelist{display:flex;flex-direction:column;gap:4px}
        .uq2-filerow{display:flex;align-items:center;gap:10px;padding:8px 12px;background:var(--bg-elevated);border:1px solid var(--border-subtle);border-radius:var(--radius-md)}
        .uq2-filerow-icon{color:var(--accent-cyan);flex-shrink:0;opacity:.65}
        .uq2-filerow-meta{flex:1;min-width:0}
        .uq2-filerow-name{font-family:'IBM Plex Mono',monospace;font-size:10.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--text-primary)}
        .uq2-filerow-sz{font-size:10px;color:var(--text-tertiary);margin-top:1px}
        .uq2-filerow-rm{background:none;border:none;color:var(--text-tertiary);cursor:pointer;padding:4px;border-radius:var(--radius-sm);transition:color 160ms;line-height:1;font-size:16px}
        .uq2-filerow-rm:hover{color:#F23F5D}
        .uq2-toolbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
        .uq2-section-label{font-size:10px;font-weight:700;letter-spacing:.7px;text-transform:uppercase;color:var(--text-tertiary)}
        .uq2-preset-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
        .uq2-preset-card{border:1.5px solid var(--border-subtle);border-radius:var(--radius-lg);padding:10px 8px;cursor:pointer;transition:all 180ms;background:var(--bg-surface);text-align:center}
        .uq2-preset-card:hover{border-color:var(--border-strong);transform:translateY(-1px)}
        .uq2-preset-card.sel{border-color:rgba(94,234,212,.5);background:rgba(94,234,212,.05);box-shadow:0 0 0 1px rgba(94,234,212,.12)}
        .uq2-preset-swatch{height:3px;border-radius:2px;margin-bottom:8px}
        .uq2-preset-name{font-size:11.5px;font-weight:700;color:var(--text-primary);margin-bottom:3px}
        .uq2-preset-desc{font-family:'IBM Plex Mono',monospace;font-size:9px;color:var(--text-tertiary)}
        .uq2-tmpl-row{display:flex;gap:6px;flex-wrap:wrap}
        .uq2-tmpl-chip{padding:6px 10px;border-radius:var(--radius-md);border:1px solid var(--border-subtle);background:var(--bg-elevated);cursor:pointer;transition:all 160ms;text-align:center;min-width:58px}
        .uq2-tmpl-chip:hover{border-color:var(--border-strong);background:var(--bg-hover)}
        .uq2-tmpl-chip.sel{border-color:rgba(94,234,212,.45);background:rgba(94,234,212,.06)}
        .uq2-tmpl-name{font-size:11.5px;font-weight:600;color:var(--text-primary)}
        .uq2-tmpl-badge{font-size:9px;font-family:'IBM Plex Mono',monospace;color:var(--text-tertiary);margin-top:2px}
        .uq2-intensity{display:grid;grid-template-columns:repeat(3,1fr);border:1.5px solid var(--border-subtle);border-radius:var(--radius-lg);overflow:hidden}
        .uq2-int-item{padding:9px 10px;text-align:center;cursor:pointer;transition:all 160ms;border-right:1px solid var(--border-subtle)}
        .uq2-int-item:last-child{border-right:none}
        .uq2-int-item:hover{background:var(--bg-elevated)}
        .uq2-int-item.sel-low{background:rgba(74,222,128,.1);border-color:rgba(74,222,128,.25);color:#4ADE80}
        .uq2-int-item.sel-med{background:rgba(251,191,36,.1);color:#FBBF24}
        .uq2-int-item.sel-high{background:rgba(242,63,93,.1);color:#F23F5D}
        .uq2-int-label{font-size:12px;font-weight:700}
        .uq2-int-key{font-family:'IBM Plex Mono',monospace;font-size:9px;margin-top:2px;opacity:.6}
        .uq2-fx-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
        .uq2-fx-card{background:var(--bg-elevated);border:1px solid var(--border-subtle);border-radius:var(--radius-lg);padding:10px 12px;cursor:pointer;transition:all 160ms;display:flex;flex-direction:column;gap:7px;user-select:none}
        .uq2-fx-card:hover{border-color:var(--border-default)}
        .uq2-fx-card.on{border-color:rgba(94,234,212,.3);background:rgba(94,234,212,.04)}
        .uq2-fx-top{display:flex;align-items:center;justify-content:space-between;gap:8px}
        .uq2-fx-name{font-size:12px;font-weight:600;color:var(--text-primary)}
        .uq2-fx-sub{font-size:10px;color:var(--text-tertiary);line-height:1.35}
        .uq2-toggle{position:relative;display:inline-flex;width:36px;height:20px;flex-shrink:0}
        .uq2-toggle input{opacity:0;width:0;height:0;position:absolute}
        .uq2-toggle-slider{position:absolute;inset:0;cursor:pointer;border-radius:10px;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.1);transition:all 180ms}
        .uq2-toggle-slider::after{content:'';position:absolute;width:14px;height:14px;top:2px;left:2px;border-radius:50%;background:rgba(255,255,255,.3);transition:all 180ms}
        .uq2-toggle input:checked+.uq2-toggle-slider{background:rgba(94,234,212,.2);border-color:rgba(94,234,212,.5)}
        .uq2-toggle input:checked+.uq2-toggle-slider::after{transform:translateX(16px);background:#5EEAD4}
        .uq2-level-strip{display:flex;gap:3px;margin-top:2px}
        .uq2-lvl-btn{flex:1;padding:3px 0;font-size:9.5px;font-weight:700;font-family:'IBM Plex Mono',monospace;border-radius:3px;border:1px solid rgba(255,255,255,.07);background:rgba(255,255,255,.04);color:var(--text-tertiary);cursor:pointer;transition:all 140ms}
        .uq2-lvl-btn:hover{background:rgba(255,255,255,.08);color:var(--text-secondary)}
        .uq2-lvl-btn.sel-low{background:rgba(74,222,128,.14);border-color:rgba(74,222,128,.4);color:#4ADE80}
        .uq2-lvl-btn.sel-med{background:rgba(251,191,36,.14);border-color:rgba(251,191,36,.4);color:#FBBF24}
        .uq2-lvl-btn.sel-high{background:rgba(242,63,93,.14);border-color:rgba(242,63,93,.4);color:#F23F5D}
        .uq2-accord{border-bottom:1px solid var(--border-subtle)}
        .uq2-accord:last-child{border-bottom:none}
        .uq2-accord-head{display:flex;align-items:center;gap:10px;padding:12px 0;cursor:pointer;background:transparent;border:none;color:var(--text-primary);width:100%;text-align:left}
        .uq2-accord-title{font-size:12px;font-weight:600;flex:1;text-align:left}
        .uq2-accord-badge{font-size:9.5px;font-weight:600;padding:2px 7px;border-radius:20px}
        .uq2-accord-badge.ok{background:rgba(74,222,128,.12);color:#4ADE80;border:1px solid rgba(74,222,128,.25)}
        .uq2-accord-badge.muted{background:rgba(255,255,255,.04);color:var(--text-tertiary);border:1px solid rgba(255,255,255,.06)}
        .uq2-accord-badge.warn{background:rgba(251,191,36,.1);color:#FBBF24;border:1px solid rgba(251,191,36,.2)}
        .uq2-accord-chev{color:var(--text-tertiary);transition:transform 200ms;flex-shrink:0}
        .uq2-accord-chev.open{transform:rotate(180deg)}
        .uq2-accord-body{padding-bottom:14px;display:flex;flex-direction:column;gap:10px}
        .uq2-field-label{font-size:9.5px;font-weight:700;letter-spacing:.7px;text-transform:uppercase;color:var(--text-tertiary)}
        .uq2-layer-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
        .uq2-file-row{display:flex;gap:6px;align-items:center}
        .uq2-dest-btn{padding:9px 12px;border-radius:var(--radius-lg);border:1.5px solid var(--border-subtle);background:var(--bg-elevated);cursor:pointer;transition:all 160ms;text-align:left;width:100%}
        .uq2-dest-btn:hover{border-color:var(--border-strong)}
        .uq2-dest-btn.active{border-color:rgba(94,234,212,.45);background:rgba(94,234,212,.06)}
        .uq2-dest-name{font-size:12.5px;font-weight:700;color:var(--text-primary)}
        .uq2-dest-sub{font-size:10.5px;color:var(--text-tertiary);margin-top:2px}
        .uq2-count-row{display:flex;align-items:center;gap:10px}
        .uq2-count-btn{width:32px;height:32px;border-radius:var(--radius-md);border:1px solid var(--border-default);background:var(--bg-elevated);color:var(--text-primary);font-size:16px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all 140ms;flex-shrink:0;font-family:inherit}
        .uq2-count-btn:hover{background:var(--bg-hover);border-color:var(--border-strong)}
        .uq2-count-input{width:68px;text-align:center;font-size:20px;font-weight:700;height:40px;background:transparent;border:1.5px solid var(--border-default);border-radius:var(--radius-md);color:var(--text-primary);font-family:'IBM Plex Mono',monospace;outline:none}
        .uq2-qcounts{display:flex;gap:4px;flex-wrap:wrap}
        .uq2-qc{padding:3px 9px;border-radius:var(--radius-sm);border:1px solid var(--border-subtle);background:var(--bg-elevated);font-size:10.5px;font-weight:600;color:var(--text-secondary);cursor:pointer;transition:all 140ms;font-family:inherit}
        .uq2-qc:hover{background:var(--bg-hover);border-color:var(--border-strong)}
        .uq2-qc.active{background:rgba(94,234,212,.1);border-color:rgba(94,234,212,.35);color:var(--accent-cyan)}
        .uq2-render-btn{width:100%;padding:13px 18px;border-radius:var(--radius-lg);border:1.5px solid rgba(94,234,212,.35);font-size:13.5px;font-weight:700;cursor:pointer;transition:all 180ms;display:flex;align-items:center;justify-content:center;gap:8px;background:linear-gradient(135deg,rgba(94,234,212,.18) 0%,rgba(94,234,212,.1) 100%);color:var(--accent-cyan);font-family:inherit}
        .uq2-render-btn:hover:not(:disabled){background:linear-gradient(135deg,rgba(94,234,212,.26) 0%,rgba(94,234,212,.16) 100%);border-color:rgba(94,234,212,.55);box-shadow:0 0 22px rgba(94,234,212,.1)}
        .uq2-render-btn:disabled{opacity:.35;cursor:not-allowed}
        .uq2-batch-btn{width:100%;padding:13px 18px;border-radius:var(--radius-lg);border:1.5px solid rgba(129,140,248,.3);font-size:13.5px;font-weight:700;cursor:pointer;transition:all 180ms;display:flex;align-items:center;justify-content:center;gap:8px;background:linear-gradient(135deg,rgba(129,140,248,.16) 0%,rgba(129,140,248,.08) 100%);color:#818CF8;font-family:inherit}
        .uq2-batch-btn:hover:not(:disabled){background:linear-gradient(135deg,rgba(129,140,248,.24) 0%,rgba(129,140,248,.14) 100%)}
        .uq2-batch-btn:disabled{opacity:.35;cursor:not-allowed}
        .uq2-preview-btn{width:100%;padding:9px 14px;border-radius:var(--radius-md);border:1px solid var(--border-default);background:transparent;color:var(--text-secondary);font-size:12px;font-weight:600;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:6px;transition:all 160ms;font-family:inherit;margin-top:6px}
        .uq2-preview-btn:hover:not(:disabled){background:var(--bg-elevated);color:var(--text-primary)}
        .uq2-preview-btn:disabled{opacity:.35;cursor:not-allowed}
        .uq2-sidebar{display:flex;flex-direction:column;gap:10px;position:sticky;top:0}
        .uq2-video-preview{aspect-ratio:9/16;border-radius:var(--radius-xl);overflow:hidden;background:var(--bg-surface);border:1px solid var(--border-subtle);display:flex;align-items:center;justify-content:center;max-height:240px}
        .uq2-video-preview video{width:100%;height:100%;object-fit:cover}
        .uq2-preview-empty{display:flex;flex-direction:column;align-items:center;gap:8px}
        .uq2-preview-play-ic{width:40px;height:40px;border-radius:50%;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.08);display:flex;align-items:center;justify-content:center;color:var(--text-tertiary)}
        .uq2-preview-hint{font-size:10.5px;color:var(--text-tertiary);text-align:center}
        .uq2-config-card{background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-xl);padding:12px}
        .uq2-config-title{font-size:9.5px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;color:var(--text-tertiary);margin-bottom:10px}
        .uq2-config-row{display:flex;justify-content:space-between;align-items:center;padding:3.5px 0;border-bottom:1px solid rgba(255,255,255,.03)}
        .uq2-config-row:last-child{border-bottom:none}
        .uq2-cfg-k{font-size:10.5px;color:var(--text-tertiary)}
        .uq2-cfg-v{font-size:10.5px;font-weight:600;color:var(--text-secondary);font-family:'IBM Plex Mono',monospace}
        .uq2-cfg-v.hi{color:var(--accent-cyan)}
        .uq2-prot{margin-top:8px;padding-top:10px;border-top:1px solid rgba(255,255,255,.04)}
        .uq2-prot-label{font-size:9.5px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;color:var(--text-tertiary);margin-bottom:6px}
        .uq2-prot-row{display:flex;align-items:center;gap:8px}
        .uq2-prot-bar{flex:1;height:4px;background:rgba(255,255,255,.05);border-radius:2px;overflow:hidden}
        .uq2-prot-fill{height:100%;border-radius:2px;transition:width 600ms cubic-bezier(.4,0,.2,1)}
        .uq2-prot-fill.good{background:linear-gradient(90deg,#4ADE80,#22d3ee);box-shadow:0 0 6px rgba(74,222,128,.3)}
        .uq2-prot-fill.med{background:linear-gradient(90deg,#FBBF24,#F59E0B)}
        .uq2-prot-fill.low{background:linear-gradient(90deg,#F23F5D,#DC2626)}
        .uq2-prot-pct{font-family:'IBM Plex Mono',monospace;font-size:11px;font-weight:700;min-width:32px;text-align:right}
        .uq2-prot-hint{font-size:9.5px;color:var(--text-tertiary);margin-top:3px}
        .uq2-sidebar-launch{background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-xl);padding:12px;display:flex;flex-direction:column;gap:8px}
        .uq2-sidebar-dest{display:grid;grid-template-columns:1fr 1fr;gap:5px;margin-bottom:4px}
        .uq2-sidebar-foot{display:flex;align-items:center;justify-content:space-between;padding:4px 0}
        .uq2-foot-text{font-size:10px;color:var(--text-tertiary);font-family:'IBM Plex Mono',monospace}
        .uq2-kbd-row{display:flex;align-items:center;gap:3px}
        .uq2-kbd{background:var(--bg-elevated);border:1px solid var(--border-default);border-radius:3px;padding:1px 5px;font-size:9.5px;font-family:'IBM Plex Mono',monospace;color:var(--text-tertiary)}
        .uq2-toast-wrap{position:fixed;top:18px;right:18px;z-index:9999;display:flex;flex-direction:column;gap:7px;pointer-events:none}
        .uq2-toast{display:flex;align-items:center;gap:10px;padding:10px 13px;border-radius:var(--radius-lg);pointer-events:all;max-width:360px;box-shadow:0 4px 20px rgba(0,0,0,.45);animation:uq2-in 180ms ease}
        .uq2-toast.ok{background:rgba(74,222,128,.1);border:1px solid rgba(74,222,128,.28);color:#4ADE80}
        .uq2-toast.err{background:rgba(242,63,93,.1);border:1px solid rgba(242,63,93,.28);color:#F23F5D}
        .uq2-toast-icon{font-size:13px;flex-shrink:0}
        .uq2-toast-msg{flex:1;color:var(--text-primary);font-size:12px;line-height:1.4}
        .uq2-toast-x{background:none;border:none;cursor:pointer;color:var(--text-tertiary);font-size:14px;padding:2px;line-height:1;opacity:.7}
        .uq2-toast-x:hover{opacity:1}
        @keyframes uq2-in{from{transform:translateX(16px);opacity:0}to{transform:none;opacity:1}}
        .uq2-prog-overlay{position:fixed;inset:0;z-index:9000;background:rgba(0,0,0,.75);backdrop-filter:blur(4px);display:flex;align-items:center;justify-content:center;padding:20px}
        .uq2-prog-modal{background:var(--bg-surface);border:1px solid var(--border-default);border-radius:var(--radius-2xl);padding:26px;max-width:420px;width:100%;box-shadow:var(--shadow-lg)}
        .uq2-prog-title{font-size:15px;font-weight:700;color:var(--text-primary);margin-bottom:3px}
        .uq2-prog-sub{font-size:11.5px;color:var(--text-secondary);margin-bottom:14px;min-height:17px}
        .uq2-prog-bar-bg{height:5px;background:rgba(255,255,255,.05);border-radius:3px;overflow:hidden;margin-bottom:14px}
        .uq2-prog-bar-fill{height:100%;border-radius:3px;background:linear-gradient(90deg,var(--accent-cyan),rgba(94,234,212,.55));transition:width 400ms ease;box-shadow:0 0 8px rgba(94,234,212,.28)}
        .uq2-prog-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:14px}
        .uq2-prog-stat-lbl{font-size:9.5px;color:var(--text-tertiary);text-transform:uppercase;letter-spacing:.5px;margin-bottom:3px}
        .uq2-prog-stat-val{font-family:'IBM Plex Mono',monospace;font-size:13px;font-weight:700;color:var(--text-primary)}
        .uq2-prog-actions{display:flex;gap:7px;margin-top:4px}
        .uq2-dl-box{background:rgba(74,222,128,.06);border:1px solid rgba(74,222,128,.18);border-radius:var(--radius-xl);padding:12px 14px;margin-bottom:12px;display:flex;flex-direction:column;gap:8px}
        .uq2-dl-title{font-size:12.5px;font-weight:700;color:#4ADE80;display:flex;align-items:center;gap:7px}
        .uq2-dl-desc{font-size:11.5px;color:var(--text-secondary)}
        .uq2-dl-row{display:flex;align-items:center;justify-content:space-between;gap:10px}
        .uq2-dl-id{font-family:'IBM Plex Mono',monospace;font-size:10.5px;color:var(--text-tertiary)}
        .uq2-check-group{display:flex;flex-direction:column;gap:8px;padding:10px 12px;background:var(--bg-elevated);border-radius:var(--radius-lg);border:1px solid var(--border-subtle)}
        .uq2-check-row{display:flex;align-items:flex-start;gap:9px;cursor:pointer}
        .uq2-check-row input[type=checkbox]{margin-top:2px;accent-color:var(--accent-cyan);width:13px;height:13px;flex-shrink:0;cursor:pointer}
        .uq2-check-text{font-size:12px;color:var(--text-secondary);line-height:1.35}
        .uq2-check-sub{display:block;font-size:10px;color:var(--text-tertiary);margin-top:1px}
        .uq2-inline-note{font-size:10.5px;color:var(--text-tertiary);line-height:1.4}
        .uq2-ai-btn{background:rgba(167,139,250,.1);border:1px solid rgba(167,139,250,.25);color:#A78BFA;border-radius:var(--radius-md);padding:4px 10px;font-size:11px;font-weight:600;cursor:pointer;transition:all 160ms;display:flex;align-items:center;gap:5px;font-family:inherit}
        .uq2-ai-btn:hover:not(:disabled){background:rgba(167,139,250,.16)}
        .uq2-ai-btn:disabled{opacity:.45;cursor:not-allowed}
        .uq2-amber-btn{background:rgba(251,191,36,.08);border:1px solid rgba(251,191,36,.28);color:#FBBF24;border-radius:var(--radius-md);padding:5px 10px;font-size:11px;font-weight:600;cursor:pointer;transition:all 160ms;display:flex;align-items:center;gap:5px;font-family:inherit}
        .uq2-amber-btn:hover{background:rgba(251,191,36,.14)}
        .uq2-save-btn{padding:8px 14px;border-radius:var(--radius-md);border:1px solid rgba(94,234,212,.3);background:rgba(94,234,212,.08);color:var(--accent-cyan);font-size:12px;font-weight:600;cursor:pointer;transition:all 160ms;display:flex;align-items:center;gap:6px;font-family:inherit}
        .uq2-save-btn:hover:not(:disabled){background:rgba(94,234,212,.13)}
        .uq2-save-btn:disabled{opacity:.4;cursor:not-allowed}
        .uq2-next-btn{padding:8px 14px;border-radius:var(--radius-md);border:1px solid var(--border-default);background:var(--bg-elevated);color:var(--text-primary);font-size:12px;font-weight:600;cursor:pointer;transition:all 160ms;font-family:inherit}
        .uq2-next-btn:hover:not(:disabled){background:var(--bg-hover);border-color:var(--border-strong)}
        .uq2-next-btn:disabled{opacity:.4;cursor:not-allowed}
        .uq2-ghost-btn{padding:7px 12px;border-radius:var(--radius-md);border:1px solid var(--border-default);background:transparent;color:var(--text-secondary);font-size:11.5px;font-weight:600;cursor:pointer;transition:all 160ms;display:flex;align-items:center;gap:5px;font-family:inherit}
        .uq2-ghost-btn:hover:not(:disabled){background:var(--bg-elevated);border-color:var(--border-strong);color:var(--text-primary)}
        .uq2-ghost-btn:disabled{opacity:.35;cursor:not-allowed}
        .uq2-cyan-btn{padding:7px 12px;border-radius:var(--radius-md);border:1px solid rgba(94,234,212,.28);background:rgba(94,234,212,.06);color:var(--accent-cyan);font-size:11.5px;font-weight:600;cursor:pointer;transition:all 160ms;display:flex;align-items:center;gap:5px;font-family:inherit}
        .uq2-cyan-btn:hover:not(:disabled){background:rgba(94,234,212,.12)}
        .uq2-cyan-btn:disabled{opacity:.35;cursor:not-allowed}
        .uq2-textarea{width:100%;resize:vertical;min-height:72px;background:var(--bg-elevated);border:1px solid var(--border-subtle);border-radius:var(--radius-md);color:var(--text-primary);font-family:inherit;font-size:12.5px;padding:9px 11px;line-height:1.5;outline:none;transition:border-color 160ms}
        .uq2-textarea:focus{border-color:rgba(94,234,212,.3)}
        .uq2-sub-preview{padding:12px;border-radius:var(--radius-lg);border:1px solid var(--border-subtle);background:#000;text-align:center;word-break:break-word;line-height:1.3}
        .uq2-ai-meta-box{background:rgba(167,139,250,.05);border:1px solid rgba(167,139,250,.15);border-radius:var(--radius-lg);padding:11px;display:flex;flex-direction:column;gap:5px;font-size:11.5px;line-height:1.5}
        .uq2-ai-meta-key{display:inline-block;min-width:88px;font-family:'IBM Plex Mono',monospace;font-size:10px;color:var(--text-tertiary)}
        .uq2-pri-row{display:flex;align-items:center;gap:7px;flex-wrap:wrap}
        .uq2-pri-label{font-size:11px;color:var(--text-tertiary)}
        .uq2-pri-chip{padding:3px 9px;border-radius:var(--radius-sm);border:1px solid var(--border-subtle);background:var(--bg-elevated);font-size:10.5px;font-weight:600;color:var(--text-secondary);cursor:pointer;transition:all 140ms;font-family:inherit}
        .uq2-pri-chip:hover{background:var(--bg-hover)}
        .uq2-pri-chip.active{background:rgba(94,234,212,.1);border-color:rgba(94,234,212,.35);color:var(--accent-cyan)}
        .uq2-badge{font-size:9.5px;font-weight:700;padding:2px 7px;border-radius:20px;font-family:'IBM Plex Mono',monospace}
        .uq2-badge-neutral{background:rgba(255,255,255,.06);color:var(--text-tertiary);border:1px solid rgba(255,255,255,.08)}
        .uq2-badge-info{background:rgba(96,165,250,.12);color:#60A5FA;border:1px solid rgba(96,165,250,.2)}
        .uq2-hash-row{margin-top:8px;padding:5px 9px;background:rgba(94,234,212,.05);border:1px solid rgba(94,234,212,.18);border-radius:5px;font-size:10.5px;display:flex;align-items:center;gap:7px}
        .uq2-hash-label{color:var(--text-tertiary)}
        .uq2-hash-val{font-family:'IBM Plex Mono',monospace;color:var(--accent-cyan);letter-spacing:.04em}
      `}</style>

      {toast && (
        <div className="uq2-toast-wrap">
          <div className={`uq2-toast ${toast.kind === "err" ? "err" : "ok"}`}>
            <span className="uq2-toast-icon">{toast.kind === "err" ? "✕" : "✓"}</span>
            <span className="uq2-toast-msg">{toast.msg}</span>
            <button type="button" className="uq2-toast-x" onClick={() => setToast(null)} aria-label="Закрыть">✕</button>
          </div>
        </div>
      )}

      <div className="uq2-wrapper">
        {/* Header */}
        <div className="uq2-header">
          <div className="uq2-title-row">
            <span className="uq2-title">Уникализатор</span>
            <span className="uq2-version">v0.4</span>
          </div>
          <div className="uq2-mode-toggle">
            <button type="button" className={`uq2-mode-btn${flowMode === "guide" ? " active" : ""}`} onClick={() => setFlowMode("guide")}>Мастер</button>
            <button type="button" className={`uq2-mode-btn${flowMode === "free" ? " active" : ""}`} onClick={() => setFlowMode("free")}>Свободно</button>
          </div>
        </div>

        {/* Stepper */}
        <div className="uq2-stepper">
          {([
            { num: 1, label: "Видео",   done: hasVideo },
            { num: 2, label: "Стиль",   done: hasStyle },
            { num: 3, label: "Эффекты", done: hasEffects },
            { num: 4, label: "Слои",    done: hasLayers },
            { num: 5, label: "Запуск",  done: allStepsReady },
          ] as const).map((s, i) => (
            <div key={s.num} style={{ display: "contents" }}>
              {i > 0 && (
                <div className="uq2-step-conn">
                  <div className={`uq2-step-line${s.done || activeStep > s.num ? " done" : ""}`} />
                </div>
              )}
              <div
                className={`uq2-step${s.done ? " done" : ""}${activeStep === s.num ? " active" : ""}${!stepNavOpen(s.num) ? " locked" : ""}`}
                onClick={() => goStep(s.num)}
                role="button" tabIndex={0}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") goStep(s.num); }}
              >
                <div className="uq2-step-dot">{s.num}</div>
                <div className="uq2-step-label">{s.label}</div>
              </div>
            </div>
          ))}
        </div>

        {/* Download offer */}
        {downloadOfferIds.length > 0 && (
          <div className="uq2-dl-box">
            <div className="uq2-dl-title">
              <Download size={14} strokeWidth={2} aria-hidden />
              Готово к скачиванию
            </div>
            <p className="uq2-dl-desc">Скачивание запускается автоматически. Кнопки — если браузер заблокировал загрузку.</p>
            <div>
              {downloadOfferIds.map((id) => (
                <div key={id} className="uq2-dl-row">
                  <span className="uq2-dl-id">Задача #{id}</span>
                  <button type="button" className="uq2-cyan-btn" disabled={downloadingTaskId !== null} onClick={() => void handleDownloadTask(id)}>
                    <Download size={13} strokeWidth={2} aria-hidden />
                    {downloadingTaskId === id ? "Скачивание…" : "Скачать MP4"}
                  </button>
                </div>
              ))}
            </div>
            <button type="button" className="uq2-ghost-btn" onClick={() => setDownloadOfferIds([])}>Скрыть</button>
          </div>
        )}

        {/* Main layout */}
        <div className="uq2-layout">
          <div className="uq2-main">

            {/* Step 1 */}
            {activeStep === 1 && (
              <div className="uq2-card">
                <div className="uq2-card-head">
                  <div className="uq2-card-title"><span className="uq2-card-num">01</span>Исходное видео</div>
                </div>
                <div className="uq2-card-body">
                  <div
                    className={`uq2-dropzone${videoDragOver ? " drag" : ""}`}
                    role="button" tabIndex={0}
                    onDragEnter={(e) => { e.preventDefault(); e.stopPropagation(); setVideoDragOver(true); }}
                    onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); setVideoDragOver(true); }}
                    onDragLeave={(e) => { e.preventDefault(); e.stopPropagation(); setVideoDragOver(false); }}
                    onDrop={(e) => { e.preventDefault(); e.stopPropagation(); setVideoDragOver(false); const f = e.dataTransfer.files?.[0]; if (f) setVideoFile(f); }}
                    onClick={() => document.getElementById("uq2-video-file")?.click()}
                    onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") document.getElementById("uq2-video-file")?.click(); }}
                  >
                    <CloudUpload className="uq2-dz-icon" size={48} strokeWidth={1.25} aria-hidden />
                    <div className="uq2-dz-title">Перетащи видео сюда</div>
                    <div className="uq2-dz-sub">mp4 · mov · webm · mkv</div>
                  </div>
                  <input id="uq2-video-file" type="file" accept="video/*,.mp4,.mov,.webm,.mkv,.avi" style={{ display: "none" }} onChange={(e) => setVideoFile(e.target.files?.[0] ?? null)} />
                  {hasVideo && (
                    <div className="uq2-filelist">
                      <div className="uq2-filerow">
                        <Film className="uq2-filerow-icon" size={18} strokeWidth={1.75} aria-hidden />
                        <div className="uq2-filerow-meta">
                          <div className="uq2-filerow-name">{shortPath(videoPath, 62)}</div>
                          <div className="uq2-filerow-sz">{videoFile ? formatBytes(videoFile.size) : "файл на сервере"}</div>
                        </div>
                        <button type="button" className="uq2-filerow-rm" onClick={clearVideo} aria-label="Убрать">×</button>
                      </div>
                    </div>
                  )}
                  <div className="uq2-toolbar">
                    <button type="button" className="uq2-cyan-btn" onClick={() => document.getElementById("uq2-video-file")?.click()}>
                      <CloudUpload size={13} strokeWidth={2} aria-hidden /> Выбрать
                    </button>
                    <button type="button" className="uq2-ghost-btn" disabled={!hasVideo} onClick={clearVideo}>Очистить</button>
                    {uploadMut.isPending && <span className="uq2-inline-note">Загрузка…</span>}
                  </div>
                  <div>
                    <div className="uq2-field-label" style={{ marginBottom: 5 }}>Путь на сервере</div>
                    <input className="form-input mono" style={{ fontSize: 11.5 }} value={videoPath} onChange={(e) => setVideoPath(e.target.value)} />
                  </div>
                  <div className="uq2-toolbar">
                    <button type="button" className="uq2-next-btn" disabled={!hasVideo} onClick={() => goStep(2)}>Далее →</button>
                  </div>
                </div>
              </div>
            )}

            {/* Step 2 */}
            {activeStep === 2 && (
              <div className="uq2-card">
                <div className="uq2-card-head">
                  <div className="uq2-card-title"><span className="uq2-card-num">02</span>Пресет и стиль</div>
                  <button type="button" className="uq2-amber-btn" onClick={applyUbtPreset}>
                    <Zap size={11} strokeWidth={2.2} aria-hidden /> UBT пресет
                  </button>
                </div>
                <div className="uq2-card-body">
                  <div>
                    <div className="uq2-section-label" style={{ marginBottom: 8 }}>Пресет обработки</div>
                    <div className="uq2-preset-grid">
                      {([
                        { value: "standard", label: "Стандарт", desc: "CRF 26", color: "linear-gradient(90deg,#4A6FA5,#6B8FC7)" },
                        { value: "soft",     label: "Мягко",    desc: "CRF 22", color: "linear-gradient(90deg,#8B6FA5,#AB8FC7)" },
                        { value: "deep",     label: "Глубокий", desc: "CRF 23", color: "linear-gradient(90deg,#A5344A,#C75060)" },
                        { value: "ultra",    label: "Ультра",   desc: "CRF 20", color: "linear-gradient(90deg,#C77830,#E89840)" },
                      ] as const).map((p) => (
                        <div key={p.value} className={`uq2-preset-card${(settings.preset || "deep") === p.value ? " sel" : ""}`}
                          onClick={() => setSettings((s) => ({ ...s, preset: p.value }))}
                          role="button" tabIndex={0}
                          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setSettings((s) => ({ ...s, preset: p.value })); }}
                        >
                          <div className="uq2-preset-swatch" style={{ background: p.color }} />
                          <div className="uq2-preset-name">{p.label}</div>
                          <div className="uq2-preset-desc">{p.desc}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div>
                    <div className="uq2-section-label" style={{ marginBottom: 8 }}>Шаблон монтажа</div>
                    <div className="uq2-tmpl-row">
                      {([
                        { value: "default",  label: "Стандарт",  badge: "норм" },
                        { value: "reaction", label: "Реакция",   badge: "split" },
                        { value: "news",     label: "Новости",   badge: "нижн. бар" },
                        { value: "story",    label: "Story",     badge: "9:16 zoom" },
                        { value: "ugc",      label: "UGC",       badge: "★ арбитраж" },
                      ] as const).map((t) => (
                        <div key={t.value} className={`uq2-tmpl-chip${(settings.template || "default") === t.value ? " sel" : ""}`}
                          onClick={() => setSettings((s) => ({ ...s, template: t.value }))}
                          role="button" tabIndex={0}
                          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setSettings((s) => ({ ...s, template: t.value })); }}
                        >
                          <div className="uq2-tmpl-name">{t.label}</div>
                          <div className="uq2-tmpl-badge">{t.badge}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div>
                    <div className="uq2-section-label" style={{ marginBottom: 8 }}>Разброс уникализации</div>
                    <div className="uq2-intensity">
                      {intensityOptions.map((p) => {
                        const sel = (settings.uniqualize_intensity || "med") === p.value;
                        return (
                          <div key={p.value}
                            className={`uq2-int-item${sel ? ` sel-${p.value}` : ""}`}
                            onClick={() => setSettings((s) => ({ ...s, uniqualize_intensity: p.value }))}
                            role="button" tabIndex={0}
                            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setSettings((s) => ({ ...s, uniqualize_intensity: p.value })); }}
                          >
                            <div className="uq2-int-label">{p.label}</div>
                            <div className="uq2-int-key">{p.value.toUpperCase()}</div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                    <div>
                      <div className="uq2-field-label" style={{ marginBottom: 5 }}>Ниша для AI</div>
                      <input className="form-input" style={{ fontSize: 12 }} placeholder="YouTube Shorts" value={settings.niche ?? ""} onChange={(e) => setSettings((s) => ({ ...s, niche: e.target.value }))} />
                    </div>
                    <div>
                      <div className="uq2-field-label" style={{ marginBottom: 5 }}>Отпечаток устройства</div>
                      {deviceModelOptions.length > 0 ? (
                        <select className="form-select" style={{ fontSize: 12 }} value={deviceModelSelectValue}
                          onChange={(e) => {
                            const v = e.target.value;
                            if (v === DEVICE_MODEL_CUSTOM) { setSettings((s) => ({ ...s, device_model: (s.device_model || "").trim() })); return; }
                            setSettings((s) => ({ ...s, device_model: v }));
                          }}>
                          {deviceModelOptions.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
                          <option value={DEVICE_MODEL_CUSTOM}>Вручную…</option>
                        </select>
                      ) : (
                        <input className="form-input" style={{ fontSize: 11.5 }} placeholder="Samsung SM-S918N" value={settings.device_model ?? ""} onChange={(e) => setSettings((s) => ({ ...s, device_model: e.target.value }))} />
                      )}
                    </div>
                  </div>
                  <div className="uq2-toolbar">
                    <button type="button" className="uq2-save-btn" disabled={saveSettingsMut.isPending || settingsQ.isLoading} onClick={() => saveSettingsMut.mutate()}>
                      <Save size={13} strokeWidth={1.75} aria-hidden /> Сохранить
                    </button>
                    <button type="button" className="uq2-next-btn" disabled={!hasStyle} onClick={() => goStep(3)}>Далее →</button>
                  </div>
                </div>
              </div>
            )}

            {/* Step 3 */}
            {activeStep === 3 && (
              <div className="uq2-card">
                <div className="uq2-card-head">
                  <div className="uq2-card-title"><span className="uq2-card-num">03</span>Эффекты</div>
                  <button type="button" className="uq2-amber-btn"
                    onClick={() => {
                      setSettings((s) => ({
                        ...s,
                        effects: { mirror: true, noise: true, crop_reframe: true, gamma_jitter: true, speed: false, audio_tone: true },
                        effect_levels: { crop_reframe: "med", gamma_jitter: "med", audio_tone: "med" },
                      }));
                      setToast({ msg: "Рекомендуемые эффекты выбраны", kind: "ok" });
                    }}>Авто-выбор для арбитража</button>
                </div>
                <div className="uq2-card-body">
                  <div className="uq2-fx-grid">
                    {Object.entries(availableEffects).map(([k, label]) => {
                      const on = Boolean(effects[k]);
                      const hasLevel = LEVEL_CONTROL_EFFECTS.has(k);
                      const lvl = settings.effect_levels?.[k] || "med";
                      return (
                        <div key={k} className={`uq2-fx-card${on ? " on" : ""}`}
                          onClick={() => setSettings((s) => ({ ...s, effects: toggleEffect(s.effects, k) }))}
                          role="button" tabIndex={0}
                          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setSettings((s) => ({ ...s, effects: toggleEffect(s.effects, k) })); }}
                        >
                          <div className="uq2-fx-top">
                            <span className="uq2-fx-name">{String(label)}</span>
                            <label className="uq2-toggle" onClick={(e) => e.stopPropagation()}>
                              <input type="checkbox" checked={on} onChange={() => setSettings((s) => ({ ...s, effects: toggleEffect(s.effects, k) }))} />
                              <span className="uq2-toggle-slider" />
                            </label>
                          </div>
                          {hasLevel && on && (
                            <div className="uq2-level-strip" onClick={(e) => e.stopPropagation()}>
                              {Object.keys(availableEffectLevels).map((lv) => (
                                <button key={lv} type="button"
                                  className={`uq2-lvl-btn${lvl === lv ? ` sel-${lv}` : ""}`}
                                  onClick={() => setSettings((s) => ({ ...s, effect_levels: setEffectLevel(s.effect_levels, k, lv) }))}
                                >{lv.toUpperCase()}</button>
                              ))}
                            </div>
                          )}
                          {hasLevel && on && <div className="uq2-fx-sub">{EFFECT_LEVEL_HINTS[k]?.[lvl] || ""}</div>}
                        </div>
                      );
                    })}
                  </div>
                  <div className="uq2-toolbar">
                    <button type="button" className="uq2-save-btn" disabled={saveSettingsMut.isPending} onClick={() => saveSettingsMut.mutate()}>
                      <Save size={13} strokeWidth={1.75} aria-hidden /> Сохранить
                    </button>
                    <button type="button" className="uq2-next-btn" onClick={() => { setEffectsReviewed(true); goStep(4); }}>Далее →</button>
                  </div>
                </div>
              </div>
            )}

            {/* Step 4 */}
            {activeStep === 4 && (
              <div className="uq2-card">
                <div className="uq2-card-head">
                  <div className="uq2-card-title"><span className="uq2-card-num">04</span>Слои</div>
                </div>
                <div className="uq2-card-body">
                  {/* Overlay accordion */}
                  <div className="uq2-accord">
                    <button type="button" className="uq2-accord-head" onClick={() => setLayerPanelOpen((o) => ({ ...o, overlay: !o.overlay }))}>
                      <span className="uq2-accord-title">Оверлей</span>
                      <span className={`uq2-accord-badge${overlayIsUserUpload ? " ok" : " muted"}`}>{overlayIsUserUpload ? "Задан" : "По умолчанию"}</span>
                      <ChevronDown className={`uq2-accord-chev${layerPanelOpen.overlay ? " open" : ""}`} size={16} strokeWidth={2} aria-hidden />
                    </button>
                    {layerPanelOpen.overlay && (
                      <div className="uq2-accord-body">
                        <input id="uq2-overlay-file" type="file" accept="image/*,video/*,.mp4,.mov,.webm,.png,.jpg,.jpeg,.webp" style={{ display: "none" }} onChange={(e) => setOverlayFile(e.target.files?.[0] ?? null)} />
                        <div className="uq2-file-row">
                          <input readOnly className="form-input mono" style={{ flex: 1, fontSize: 11 }} title={String(settings.overlay_media_path || "")} value={overlayIsUserUpload ? shortPath(String(settings.overlay_media_path || ""), 44) : "Встроенный слой"} />
                          <button type="button" className="uq2-cyan-btn" onClick={() => document.getElementById("uq2-overlay-file")?.click()}>Выбрать</button>
                          <button type="button" className="uq2-ghost-btn" disabled={!overlayIsUserUpload} onClick={() => { setOverlayFile(null); persistLayerPatch({ overlay_media_path: "" }, "Слой сброшен"); }}>Сброс</button>
                        </div>
                        {overlayFile && <span className="uq2-inline-note">{uploadMut.isPending ? "Загрузка…" : overlayFile.name}</span>}
                        <div className="uq2-layer-grid">
                          <div>
                            <div className="uq2-field-label" style={{ marginBottom: 5 }}>Режим</div>
                            <select className="form-select" style={{ fontSize: 12 }} value={settings.overlay_mode || "on_top"} onChange={(e) => setSettings((s) => ({ ...s, overlay_mode: e.target.value }))}>
                              {OVERLAY_MODE_OPTS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
                            </select>
                          </div>
                          <div>
                            <div className="uq2-field-label" style={{ marginBottom: 5 }}>Смешивание</div>
                            <select className="form-select" style={{ fontSize: 12 }} value={settings.overlay_blend_mode || "normal"} onChange={(e) => setSettings((s) => ({ ...s, overlay_blend_mode: e.target.value }))}>
                              {blendOptions.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
                            </select>
                          </div>
                          <div>
                            <div className="uq2-field-label" style={{ marginBottom: 5 }}>Позиция</div>
                            <select className="form-select" style={{ fontSize: 12 }} value={settings.overlay_position || "top_left"} onChange={(e) => setSettings((s) => ({ ...s, overlay_position: e.target.value }))}>
                              {OVERLAY_POSITION_OPTS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
                            </select>
                          </div>
                          <div>
                            <div className="uq2-field-label" style={{ marginBottom: 5 }}>Непрозрачность: {Math.round(Number(settings.overlay_opacity ?? 1) * 100)}%</div>
                            <input type="range" min={0} max={100} style={{ width: "100%", accentColor: "var(--accent-cyan)" }} value={Math.round(Number(settings.overlay_opacity ?? 1) * 100)} onChange={(e) => setSettings((s) => ({ ...s, overlay_opacity: Number(e.target.value) / 100 }))} />
                          </div>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Text accordion */}
                  <div className="uq2-accord">
                    <button type="button" className="uq2-accord-head" onClick={() => setLayerPanelOpen((o) => ({ ...o, text: !o.text }))}>
                      <span className="uq2-accord-title">Текст и субтитры</span>
                      <span className={`uq2-accord-badge${(settings.subtitle || "").trim() || settings.subtitle_srt_path ? " ok" : " warn"}`}>
                        {(settings.subtitle || "").trim() || settings.subtitle_srt_path ? "Задан" : "Не задан"}
                      </span>
                      <ChevronDown className={`uq2-accord-chev${layerPanelOpen.text ? " open" : ""}`} size={16} strokeWidth={2} aria-hidden />
                    </button>
                    {layerPanelOpen.text && (
                      <div className="uq2-accord-body">
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                          <div className="uq2-field-label">Текст CTA</div>
                          <button type="button" className="uq2-ai-btn" disabled={aiPreviewMut.isPending} onClick={() => void fillSubtitleFromAi()}>
                            <WandSparkles size={10} strokeWidth={1.75} aria-hidden />
                            {aiPreviewMut.isPending ? "AI…" : "Из AI"}
                          </button>
                        </div>
                        <textarea className="uq2-textarea" rows={3} placeholder="CTA текст" value={settings.subtitle || ""}
                          onChange={(e) => { setSubtitleTouched(true); setSettings((s) => ({ ...s, subtitle: e.target.value })); }} />
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
                          <div>
                            <div className="uq2-field-label" style={{ marginBottom: 5 }}>Стиль</div>
                            <select className="form-select" style={{ fontSize: 11.5 }} value={settings.subtitle_style === "readable" ? "readable" : "default"} onChange={(e) => setSettings((s) => ({ ...s, subtitle_style: e.target.value }))}>
                              <option value="default">Стандарт</option>
                              <option value="readable">Крупнее</option>
                            </select>
                          </div>
                          <div>
                            <div className="uq2-field-label" style={{ marginBottom: 5 }}>Размер px</div>
                            <input className="form-input" type="number" min={12} max={96} placeholder="Авто" style={{ fontSize: 11.5 }}
                              value={settings.subtitle_font_size && settings.subtitle_font_size > 0 ? settings.subtitle_font_size : ""}
                              onChange={(e) => {
                                const raw = e.target.value.trim();
                                if (!raw) { setSettings((s) => ({ ...s, subtitle_font_size: 0 })); return; }
                                setSettings((s) => ({ ...s, subtitle_font_size: Math.max(12, Math.min(96, parseInt(raw, 10) || 0)) }));
                              }} />
                          </div>
                          <div>
                            <div className="uq2-field-label" style={{ marginBottom: 5 }}>Шрифт</div>
                            <select className="form-select" style={{ fontSize: 11.5 }} value={settings.subtitle_font ?? ""} onChange={(e) => setSettings((s) => ({ ...s, subtitle_font: e.target.value }))}>
                              {SUBTITLE_FONT_OPTIONS.map((o) => <option key={o.value || "__auto__"} value={o.value}>{o.label}</option>)}
                            </select>
                          </div>
                        </div>
                        <div className="uq2-sub-preview"
                          style={{
                            fontFamily: subtitlePreviewFontCss(settings.subtitle_font),
                            fontSize: (() => { const n = Number(settings.subtitle_font_size); if (n > 0) return Math.min(36, Math.max(14, n)); return settings.subtitle_style === "readable" ? 20 : 17; })(),
                            fontWeight: 700, color: "#fff",
                          }}>
                          {(settings.subtitle || "").trim() || "Пример · Preview · 안녕하세요"}
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <div className="uq2-field-label">SRT</div>
                          <a href="/subtitles" style={{ fontSize: 10.5, color: "var(--accent-cyan)", textDecoration: "none" }}>↗ Генератор .srt</a>
                        </div>
                        <input id="uq2-srt-file" type="file" accept=".srt" style={{ display: "none" }} onChange={(e) => setSrtFile(e.target.files?.[0] ?? null)} />
                        <div className="uq2-file-row">
                          <button type="button" className="uq2-cyan-btn" onClick={() => document.getElementById("uq2-srt-file")?.click()}>Выбрать .srt</button>
                          <button type="button" className="uq2-ghost-btn" disabled={!settings.subtitle_srt_path} onClick={() => { setSrtFile(null); persistLayerPatch({ subtitle_srt_path: "" }, "SRT сброшен"); }}>Сбросить</button>
                          {settings.subtitle_srt_path && <span className="uq2-inline-note" style={{ fontFamily: "monospace", fontSize: 10 }}>{shortPath(String(settings.subtitle_srt_path), 44)}</span>}
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Geo accordion */}
                  <div className="uq2-accord">
                    <button type="button" className="uq2-accord-head" onClick={() => setLayerPanelOpen((o) => ({ ...o, geo: !o.geo }))}>
                      <span className="uq2-accord-title">Гео-инъекция</span>
                      <span className={`uq2-accord-badge${settings.geo_enabled === false ? " muted" : " ok"}`}>
                        {settings.geo_enabled === false ? "Выкл." : geoKeyToDisplayLine(settings.geo_profile || "busan")}
                      </span>
                      <ChevronDown className={`uq2-accord-chev${layerPanelOpen.geo ? " open" : ""}`} size={16} strokeWidth={2} aria-hidden />
                    </button>
                    {layerPanelOpen.geo && (
                      <div className="uq2-accord-body">
                        <label className="uq2-check-row" style={{ marginBottom: 4 }}>
                          <input type="checkbox" checked={settings.geo_enabled !== false} onChange={(e) => setSettings((s) => ({ ...s, geo_enabled: e.target.checked }))} />
                          <span className="uq2-check-text">Вшивать гео в метаданные</span>
                        </label>
                        <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 8, alignItems: "end" }}>
                          <div>
                            <div className="uq2-field-label" style={{ marginBottom: 5 }}>Геолокация</div>
                            <select className="form-select" style={{ fontSize: 12 }} disabled={settings.geo_enabled === false} value={geoSelectValue}
                              onChange={(e) => {
                                const v = e.target.value;
                                if (v === "__custom__") { setSettings((s) => ({ ...s, geo_profile: "" })); setGeoCustomDraft(""); return; }
                                setSettings((s) => ({ ...s, geo_profile: v }));
                              }}>
                              {geoOptions.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
                              <option value="__custom__">Свои координаты…</option>
                            </select>
                            {geoSelectValue === "__custom__" && (
                              <input className="form-input" style={{ marginTop: 6, fontSize: 12 }} disabled={settings.geo_enabled === false} placeholder="35.1796, 129.0756" value={geoCustomDraft}
                                onChange={(e) => setGeoCustomDraft(e.target.value)}
                                onBlur={() => setSettings((s) => ({ ...s, geo_profile: parseGeoDisplayToProfile(geoCustomDraft) }))} />
                            )}
                          </div>
                          <div>
                            <div className="uq2-field-label" style={{ marginBottom: 5 }}>Jitter</div>
                            <input className="form-input" type="number" min={0.01} max={0.5} step={0.01} style={{ width: 78, fontSize: 12 }} value={settings.geo_jitter ?? 0.05} disabled={settings.geo_enabled === false} onChange={(e) => setSettings((s) => ({ ...s, geo_jitter: Number(e.target.value) }))} />
                          </div>
                        </div>
                      </div>
                    )}
                  </div>

                  <div className="uq2-toolbar" style={{ marginTop: 4 }}>
                    <button type="button" className="uq2-save-btn" disabled={saveSettingsMut.isPending || settingsQ.isLoading} onClick={() => { commitCustomGeoProfile(); saveSettingsMut.mutate(); }}>
                      <Save size={13} strokeWidth={1.75} aria-hidden /> Сохранить
                    </button>
                    <button type="button" className="uq2-next-btn" onClick={() => { commitCustomGeoProfile(); setLayersReviewed(true); goStep(5); }}>К запуску →</button>
                  </div>
                </div>
              </div>
            )}

            {/* Step 5 */}
            {activeStep === 5 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                <div className="uq2-card">
                  <div className="uq2-card-head">
                    <div className="uq2-card-title"><span className="uq2-card-num">05</span>Назначение</div>
                  </div>
                  <div className="uq2-card-body">
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
                      <button type="button" className={`uq2-dest-btn${renderOnly ? " active" : ""}`} onClick={() => setRenderOnly(true)}>
                        <div className="uq2-dest-name">Скачать</div><div className="uq2-dest-sub">Только рендер</div>
                      </button>
                      <button type="button" className={`uq2-dest-btn${!renderOnly ? " active" : ""}`} onClick={() => setRenderOnly(false)}>
                        <div className="uq2-dest-name">Антидетект</div><div className="uq2-dest-sub">Рендер + залив</div>
                      </button>
                    </div>
                    {!renderOnly && (
                      <>
                        <div>
                          <div className="uq2-field-label" style={{ marginBottom: 5 }}>Профиль AdsPower</div>
                          <select className="form-select" style={{ fontSize: 12 }} value={targetProfile} onChange={(e) => setTargetProfile(e.target.value)}>
                            <option value="">— Выберите профиль —</option>
                            {profiles.map((id) => <option key={id} value={id}>{id}</option>)}
                          </select>
                        </div>
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                          <div>
                            <div className="uq2-field-label" style={{ marginBottom: 5 }}>Хэштеги</div>
                            <input className="form-input" style={{ fontSize: 12 }} placeholder="#shorts #viral"
                              value={((settings.tags || []) as string[]).map((t) => `#${t}`).join(" ")}
                              onChange={(e) => { const parsed = e.target.value.split(/[\s,]+/).map((t) => t.trim().replace(/^#+/, "")).filter(Boolean); setSettings((s) => ({ ...s, tags: parsed })); }}
                              onBlur={() => saveSettingsMut.mutate()} />
                          </div>
                          <div>
                            <div className="uq2-field-label" style={{ marginBottom: 5 }}>Обложка</div>
                            <label className="uq2-cyan-btn" style={{ cursor: "pointer", display: "inline-flex" }}>
                              {settings.thumbnail_path ? String(settings.thumbnail_path).split(/[/\\]/).pop() : "Загрузить PNG"}
                              <input type="file" accept="image/png,image/jpeg,image/webp" style={{ display: "none" }}
                                onChange={async (e) => {
                                  const f = e.target.files?.[0]; if (!f) return;
                                  const fd = new FormData(); fd.append("file", f); fd.append("purpose", "overlay");
                                  try {
                                    const r = await apiFetch<ApiJson>("/api/upload", { method: "POST", tenantId, body: fd });
                                    const p = String(r.path || r.overlay_media_path || "");
                                    setSettings((s) => ({ ...s, thumbnail_path: p }));
                                    saveSettingsMut.mutate();
                                  } catch (err) { console.error(err); }
                                }} />
                            </label>
                          </div>
                        </div>
                      </>
                    )}
                  </div>
                </div>

                <div className="uq2-card">
                  <div className="uq2-card-head">
                    <div className="uq2-card-title">Одиночный рендер</div>
                    <span className="uq2-badge uq2-badge-neutral">1 видео</span>
                  </div>
                  <div className="uq2-card-body">
                    <button type="button" className="uq2-render-btn" disabled={!canRun || !canGoToRender || runMut.isPending} onClick={() => runMut.mutate()}>
                      <Play size={18} strokeWidth={2.5} aria-hidden />
                      {runMut.isPending ? "Ставим в очередь…" : "Запустить рендер"}
                    </button>
                    <div style={{ display: "flex", alignItems: "center", gap: 4, justifyContent: "center" }}>
                      <span className="uq2-kbd">Ctrl</span>
                      <span style={{ fontSize: 10, color: "var(--text-tertiary)" }}>+</span>
                      <span className="uq2-kbd">Enter</span>
                    </div>
                  </div>
                </div>

                <div className="uq2-card" style={{ border: "1px solid rgba(129,140,248,.2)", background: "rgba(129,140,248,.02)" }}>
                  <div className="uq2-card-head" style={{ borderBottomColor: "rgba(129,140,248,.15)" }}>
                    <div className="uq2-card-title" style={{ color: "#818CF8" }}>Пакетный рендер</div>
                    <span className="uq2-badge uq2-badge-info">{variantsCount} видео</span>
                  </div>
                  <div className="uq2-card-body">
                    <div>
                      <div className="uq2-section-label" style={{ marginBottom: 8 }}>Количество роликов</div>
                      <div className="uq2-count-row">
                        <button type="button" className="uq2-count-btn" onClick={() => setVariantsCount((n) => Math.max(1, n - 1))}>−</button>
                        <input className="uq2-count-input" type="number" min={1} max={50} value={variantsCount} onChange={(e) => setVariantsCount(Math.max(1, Math.min(50, Number(e.target.value || 1))))} />
                        <button type="button" className="uq2-count-btn" onClick={() => setVariantsCount((n) => Math.min(50, n + 1))}>+</button>
                        <div className="uq2-qcounts">
                          {[5, 10, 20, 30, 50].map((n) => (
                            <button key={n} type="button" className={`uq2-qc${variantsCount === n ? " active" : ""}`} onClick={() => setVariantsCount(n)}>{n}</button>
                          ))}
                        </div>
                      </div>
                    </div>
                    <div className="uq2-check-group">
                      <label className="uq2-check-row">
                        <input type="checkbox" checked={randomizeEffects} onChange={(e) => setRandomizeEffects(e.target.checked)} />
                        <span className="uq2-check-text">Рандомные эффекты для каждого ролика<span className="uq2-check-sub">mirror, noise, gamma, crop — разные у каждого</span></span>
                      </label>
                      <label className="uq2-check-row">
                        <input type="checkbox" checked={rotateTemplates} onChange={(e) => setRotateTemplates(e.target.checked)} />
                        <span className="uq2-check-text">Чередовать шаблоны монтажа<span className="uq2-check-sub">default → reaction → news → story → ugc → …</span></span>
                      </label>
                      <label className="uq2-check-row">
                        <input type="checkbox" checked={randomizeDeviceGeo} onChange={(e) => setRandomizeDeviceGeo(e.target.checked)} />
                        <span className="uq2-check-text">Рандомные device / geo<span className="uq2-check-sub">случайный отпечаток устройства и геолокация</span></span>
                      </label>
                    </div>
                    <div className="uq2-pri-row">
                      <span className="uq2-pri-label">Приоритет:</span>
                      {[{ v: -1, label: "▼ Низкий" }, { v: 0, label: "— Норма" }, { v: 1, label: "▲ Высокий" }].map(({ v, label }) => (
                        <button key={v} type="button" className={`uq2-pri-chip${variantsPriority === v ? " active" : ""}`} onClick={() => setVariantsPriority(v)}>{label}</button>
                      ))}
                    </div>
                    <button type="button" className="uq2-batch-btn" disabled={!canRun || !canGoToRender || variantsMut.isPending} onClick={() => variantsMut.mutate()}>
                      <Layers size={18} strokeWidth={2} aria-hidden />
                      {variantsMut.isPending ? "Создаём задачи…" : `Создать ${variantsCount} роликов`}
                    </button>
                    <button type="button" className="uq2-preview-btn" disabled={!videoPath.trim() || previewMut.isPending} onClick={() => previewMut.mutate()}>
                      <Play size={13} strokeWidth={2} aria-hidden />
                      {previewMut.isPending ? "Рендер превью…" : "Dry-run (10 сек превью)"}
                    </button>
                    <details>
                      <summary style={{ fontSize: 11, color: "var(--text-tertiary)", cursor: "pointer", userSelect: "none" }}>
                        Свой CTA для каждого ролика (необязательно)
                      </summary>
                      <div style={{ marginTop: 8 }}>
                        <textarea className="uq2-textarea" rows={4} placeholder={`Ровно ${variantsCount} строк`}
                          value={variantsSubtitlesText} onChange={(e) => setVariantsSubtitlesText(e.target.value)} />
                        <div style={{ fontSize: 10.5, color: "var(--text-tertiary)", marginTop: 3 }}>
                          {variantsSubtitlesText.split(/\r?\n/).filter(Boolean).length} / {variantsCount} строк
                        </div>
                      </div>
                    </details>
                  </div>
                </div>

                <div className="uq2-card">
                  <div className="uq2-card-head">
                    <div className="uq2-card-title">AI-метаданные</div>
                  </div>
                  <div className="uq2-card-body">
                    <div className="uq2-toolbar">
                      <button type="button" className="uq2-ai-btn" disabled={aiPreviewMut.isPending} onClick={() => aiPreviewMut.mutate()}>
                        <WandSparkles size={12} strokeWidth={1.75} aria-hidden />
                        {aiPreviewMut.isPending ? "Генерация…" : "Сгенерировать"}
                      </button>
                      {aiMeta && <button type="button" className="uq2-ghost-btn" onClick={() => void fillSubtitleFromAi()}>Подставить в CTA</button>}
                    </div>
                    {aiMeta && (
                      <div className="uq2-ai-meta-box">
                        <div><span className="uq2-ai-meta-key">title:</span>{String(aiMeta.title ?? "-")}</div>
                        <div><span className="uq2-ai-meta-key">description:</span>{String(aiMeta.description ?? "-")}</div>
                        {aiMeta.overlay_text != null && String(aiMeta.overlay_text).trim() && (
                          <div><span className="uq2-ai-meta-key">overlay_text:</span>{String(aiMeta.overlay_text)}</div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

          </div>

          {/* Sidebar */}
          <div className="uq2-sidebar">
            <div className="uq2-video-preview">
              {videoPreviewSrc ? (
                <video key={videoPreviewSrc} src={videoPreviewSrc} controls playsInline preload="metadata" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
              ) : (
                <div className="uq2-preview-empty">
                  <div className="uq2-preview-play-ic"><Play size={18} strokeWidth={2} aria-hidden /></div>
                  <div className="uq2-preview-hint">Выберите видео</div>
                </div>
              )}
            </div>

            <div className="uq2-config-card">
              <div className="uq2-config-title">Конфигурация</div>
              <div className="uq2-config-row"><span className="uq2-cfg-k">Пресет</span><span className={`uq2-cfg-v${settings.preset ? " hi" : ""}`}>{labelFor(presetOptions, settings.preset)}</span></div>
              <div className="uq2-config-row"><span className="uq2-cfg-k">Шаблон</span><span className="uq2-cfg-v">{labelFor(templateOptions, settings.template)}</span></div>
              <div className="uq2-config-row"><span className="uq2-cfg-k">Эффекты</span><span className={`uq2-cfg-v${enabledEffectsCount > 0 ? " hi" : ""}`}>{enabledEffectsCount > 0 ? `${enabledEffectsCount} активно` : "—"}</span></div>
              <div className="uq2-config-row"><span className="uq2-cfg-k">Оверлей</span><span className={`uq2-cfg-v${overlayIsUserUpload ? " hi" : ""}`}>{overlayIsUserUpload ? "Задан" : "Встроенный"}</span></div>
              <div className="uq2-config-row"><span className="uq2-cfg-k">Гео</span><span className="uq2-cfg-v">{geoLine}</span></div>
              <div className="uq2-config-row"><span className="uq2-cfg-k">Файлов</span><span className={`uq2-cfg-v${hasVideo ? " hi" : ""}`}>{hasVideo ? filesWordRu(variantsCount) : "Нет"}</span></div>
              <div className="uq2-prot">
                <div className="uq2-prot-label">Защита от детекции</div>
                <div className="uq2-prot-row">
                  <div className="uq2-prot-bar">
                    <div className={`uq2-prot-fill ${protectionScore >= 70 ? "good" : protectionScore >= 50 ? "med" : "low"}`} style={{ width: `${protectionScore}%` }} />
                  </div>
                  <span className="uq2-prot-pct" style={{ color: protectionScore >= 70 ? "#4ADE80" : protectionScore >= 50 ? "#FBBF24" : "#F23F5D" }}>{protectionScore}%</span>
                </div>
                <div className="uq2-prot-hint">
                  {protectionScore >= 70 ? "Высокий уровень уникализации" : protectionScore >= 50 ? "Средний — увеличь intensity" : "Низкий — включи эффекты"}
                </div>
              </div>
            </div>

            <div className="uq2-sidebar-launch">
              <div className="uq2-sidebar-dest">
                <button type="button" className={`uq2-dest-btn${renderOnly ? " active" : ""}`} onClick={() => setRenderOnly(true)} style={{ padding: "7px 10px" }}>
                  <div className="uq2-dest-name" style={{ fontSize: 11.5 }}>Скачать</div>
                  <div className="uq2-dest-sub" style={{ fontSize: 9.5 }}>Только рендер</div>
                </button>
                <button type="button" className={`uq2-dest-btn${!renderOnly ? " active" : ""}`} disabled={profiles.length === 0} onClick={() => setRenderOnly(false)} style={{ padding: "7px 10px" }}>
                  <div className="uq2-dest-name" style={{ fontSize: 11.5 }}>Антидетект</div>
                  <div className="uq2-dest-sub" style={{ fontSize: 9.5 }}>Рендер + залив</div>
                </button>
              </div>
              {!renderOnly && (
                <select className="form-select" style={{ fontSize: 12 }} value={targetProfile} onChange={(e) => setTargetProfile(e.target.value)}>
                  <option value="">— Профиль AdsPower —</option>
                  {profiles.map((id) => <option key={id} value={id}>{id}</option>)}
                </select>
              )}
              <label style={{ display: "flex", alignItems: "center", gap: 7, cursor: "pointer", fontSize: 11.5, color: "var(--text-secondary)", padding: "2px 0" }}>
                <input type="checkbox" checked={checkDuplicates} onChange={(e) => setCheckDuplicates(e.target.checked)} style={{ accentColor: "var(--accent-cyan)", width: 13, height: 13 }} />
                Проверять дубли
              </label>
              <button type="button" className="uq2-render-btn" disabled={!canRun || !canGoToRender} onClick={() => runMut.mutate()}>
                <Play size={17} strokeWidth={2.5} aria-hidden />
                Запустить рендер
              </button>
              <div className="uq2-sidebar-foot">
                <span className="uq2-foot-text">{hasVideo ? variantsCount : 0} видео · {enabledEffectsCount} fx</span>
                <div className="uq2-kbd-row">
                  <span className="uq2-kbd">Ctrl</span>
                  <span style={{ fontSize: 9, color: "var(--text-tertiary)" }}>+</span>
                  <span className="uq2-kbd">Enter</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {progressVisible && (
        <div className="uq2-prog-overlay">
          <div className="uq2-prog-modal">
            <div className="uq2-prog-title">{String(progressQ.data?.title || "Обработка")}</div>
            <div className="uq2-prog-sub">{String(progressQ.data?.detail || "")}</div>
            <div className="uq2-prog-bar-bg">
              <div className="uq2-prog-bar-fill" style={{ width: `${Math.max(0, Math.min(100, progressPercent))}%` }} />
            </div>
            <div className="uq2-prog-stats">
              <div><div className="uq2-prog-stat-lbl">Прогресс</div><div className="uq2-prog-stat-val">{progressPercent.toFixed(0)}%</div></div>
              <div><div className="uq2-prog-stat-lbl">FPS</div><div className="uq2-prog-stat-val">{Number(progressQ.data?.fps || 0).toFixed(0)}</div></div>
              <div><div className="uq2-prog-stat-lbl">Осталось</div><div className="uq2-prog-stat-val">{(() => { const eta = Number(progressQ.data?.eta_sec || 0); if (!eta || eta < 1) return "—"; const m = Math.floor(eta / 60); const s = Math.floor(eta % 60); return `${m}м ${s}с`; })()}</div></div>
              <div><div className="uq2-prog-stat-lbl">Очередь</div><div className="uq2-prog-stat-val">{Number(progressQ.data?.queue_done || 0)}/{Number(progressQ.data?.queue_total || 0)}</div></div>
            </div>
            {Boolean(progressQ.data?.hash) && (
              <div className="uq2-hash-row">
                <span className="uq2-hash-label">Hash:</span>
                <span className="uq2-hash-val">{String(progressQ.data?.hash ?? "")}</span>
              </div>
            )}
            <div className="uq2-prog-actions">
              <button type="button" className="btn" disabled={cancelMut.isPending || stopPipelineMut.isPending || restartQueueMut.isPending}
                onClick={() => { if (progressTaskId > 0) { cancelMut.mutate(progressTaskId); } else { stopPipelineMut.mutate(); } }}>
                {(cancelMut.isPending || stopPipelineMut.isPending || restartQueueMut.isPending) ? "Отмена..." : (progressTaskId > 0 ? "Отменить текущую" : "Остановить очередь")}
              </button>
              <button type="button" className="btn btn-cyan" disabled={cancelMut.isPending || stopPipelineMut.isPending || restartQueueMut.isPending} onClick={() => restartQueueMut.mutate()}>
                {restartQueueMut.isPending ? "Перезапуск..." : "Перезапустить очередь"}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
"""

content = top + new_jsx
src.write_text(content, encoding="utf-8")
print(f"Done. Written {len(content.splitlines())} lines.")
