"""
Fingerprint Spoofer — per-session рандомизация браузерного фингерпринта.

Инжектирует JS-скрипт через Playwright add_init_script() / context.add_init_script()
ДО загрузки любой страницы, переопределяя:

  • Canvas API      — шум на уровне пикселей (±1–3 на канал)
  • WebGL           — случайный renderer / vendor из реального пула
  • AudioContext    — субпиксельный шум на getChannelData / getFloatFrequencyData
  • navigator       — hardwareConcurrency, deviceMemory, languages, platform
  • screen          — colorDepth, pixelDepth (minor variance)
  • Date / timezone — смещение timezone (имитация другого региона)

Использование:
    from core.fingerprint_spoofer import apply_fingerprint_spoof
    await apply_fingerprint_spoof(page)          # на page
    await apply_fingerprint_spoof(context=ctx)   # на весь контекст (рекомендуется)

Важно: вызывать ДО первого goto(), иначе скрипт не применится к уже открытым страницам.
"""
from __future__ import annotations

import random
from typing import Any

# ── Пулы реальных значений ─────────────────────────────────────────────────────

_WEBGL_RENDERERS: list[str] = [
    "ANGLE (Intel, Intel(R) UHD Graphics 620 Direct3D11 vs_5_0 ps_5_0, D3D11)",
    "ANGLE (Intel, Intel(R) HD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)",
    "ANGLE (NVIDIA, NVIDIA GeForce GTX 1650 Direct3D11 vs_5_0 ps_5_0, D3D11)",
    "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)",
    "ANGLE (AMD, AMD Radeon RX 580 Direct3D11 vs_5_0 ps_5_0, D3D11)",
    "ANGLE (Intel, Intel(R) Iris Xe Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)",
    "ANGLE (Intel, Intel(R) UHD Graphics 770 Direct3D11 vs_5_0 ps_5_0, D3D11)",
    "ANGLE (NVIDIA, NVIDIA GeForce GTX 1060 6GB Direct3D11 vs_5_0 ps_5_0, D3D11)",
    "ANGLE (Intel, Intel(R) HD Graphics 520 Direct3D11 vs_5_0 ps_5_0, D3D11)",
    "ANGLE (AMD, AMD Radeon RX 5700 XT Direct3D11 vs_5_0 ps_5_0, D3D11)",
]

_WEBGL_VENDORS: list[str] = [
    "Google Inc. (Intel)",
    "Google Inc. (NVIDIA)",
    "Google Inc. (AMD)",
]

_PLATFORMS: list[str] = ["Win32", "Win32", "Win32", "MacIntel", "Linux x86_64"]

_LANGUAGES_POOLS: list[list[str]] = [
    ["en-US", "en"],
    ["en-US", "en", "ko"],
    ["en-GB", "en"],
    ["ko-KR", "ko", "en-US", "en"],
    ["en-US", "en", "ja"],
    ["en-US", "en", "zh-CN"],
]

_HARDWARE_CONCURRENCY: list[int] = [2, 4, 4, 4, 6, 8, 8, 8, 12, 16]
_DEVICE_MEMORY: list[int] = [2, 4, 4, 8, 8, 8, 16]

_TIMEZONE_OFFSETS: list[int] = [
    -480, -420, -360, -300, -240, -180,   # Americas
      0,   60,  120,  180,  240,  300,    # Europe / Middle East
    330,  360,  420,  480,  540,  600,    # Asia / Pacific (KST=540)
]


def _build_spoof_script(seed: int) -> str:
    """
    Генерирует JS-строку с фиксированным seed-рандомом,
    чтобы параметры были стабильны внутри одной сессии.
    """
    rng = random.Random(seed)

    renderer    = rng.choice(_WEBGL_RENDERERS)
    vendor      = rng.choice(_WEBGL_VENDORS)
    platform    = rng.choice(_PLATFORMS)
    languages   = rng.choice(_LANGUAGES_POOLS)
    hw_conc     = rng.choice(_HARDWARE_CONCURRENCY)
    dev_mem     = rng.choice(_DEVICE_MEMORY)
    tz_offset   = rng.choice(_TIMEZONE_OFFSETS)
    # Смещение пикселей Canvas: уникальное для сессии значение 1–3
    canvas_r    = rng.randint(1, 3)
    canvas_g    = rng.randint(0, 2)
    canvas_b    = rng.randint(1, 3)
    # Субпиксельный сдвиг аудио
    audio_noise = round(rng.uniform(0.000001, 0.00005), 8)

    langs_json  = str(languages).replace("'", '"')

    return f"""
(function() {{
  const SEED = {seed};

  // ── Canvas fingerprint noise ──────────────────────────────────────────────
  const _origToDataURL    = HTMLCanvasElement.prototype.toDataURL;
  const _origToBlob       = HTMLCanvasElement.prototype.toBlob;
  const _origGetImageData = CanvasRenderingContext2D.prototype.getImageData;

  function _noiseCanvas(ctx) {{
    try {{
      const imgd = _origGetImageData.call(ctx, 0, 0, ctx.canvas.width, ctx.canvas.height);
      const d = imgd.data;
      for (let i = 0; i < d.length; i += 4) {{
        d[i]   = Math.min(255, d[i]   + (SEED % {canvas_r + 1}));
        d[i+1] = Math.min(255, d[i+1] + (SEED % {canvas_g + 1}));
        d[i+2] = Math.min(255, d[i+2] + (SEED % {canvas_b + 1}));
      }}
      ctx.putImageData(imgd, 0, 0);
    }} catch(e) {{}}
  }}

  HTMLCanvasElement.prototype.toDataURL = function(...args) {{
    const ctx = this.getContext('2d');
    if (ctx) _noiseCanvas(ctx);
    return _origToDataURL.apply(this, args);
  }};

  HTMLCanvasElement.prototype.toBlob = function(cb, ...args) {{
    const ctx = this.getContext('2d');
    if (ctx) _noiseCanvas(ctx);
    return _origToBlob.call(this, cb, ...args);
  }};

  CanvasRenderingContext2D.prototype.getImageData = function(...args) {{
    const imgd = _origGetImageData.apply(this, args);
    const d = imgd.data;
    for (let i = 0; i < d.length; i += 4) {{
      d[i]   = Math.min(255, d[i]   + (SEED % {canvas_r + 1}));
      d[i+1] = Math.min(255, d[i+1] + (SEED % {canvas_g + 1}));
      d[i+2] = Math.min(255, d[i+2] + (SEED % {canvas_b + 1}));
    }}
    return imgd;
  }};

  // ── WebGL renderer / vendor ───────────────────────────────────────────────
  const _origGetParam = WebGLRenderingContext.prototype.getParameter;
  const _GL_RENDERER  = 0x1F01;
  const _GL_VENDOR    = 0x1F00;

  WebGLRenderingContext.prototype.getParameter = function(param) {{
    if (param === _GL_RENDERER) return "{renderer}";
    if (param === _GL_VENDOR)   return "{vendor}";
    return _origGetParam.call(this, param);
  }};

  // WebGL2
  if (typeof WebGL2RenderingContext !== 'undefined') {{
    const _origGetParam2 = WebGL2RenderingContext.prototype.getParameter;
    WebGL2RenderingContext.prototype.getParameter = function(param) {{
      if (param === _GL_RENDERER) return "{renderer}";
      if (param === _GL_VENDOR)   return "{vendor}";
      return _origGetParam2.call(this, param);
    }};
  }}

  // ── AudioContext noise ────────────────────────────────────────────────────
  const _AudioBuffer_proto = (typeof AudioBuffer !== 'undefined')
    ? AudioBuffer.prototype : null;
  if (_AudioBuffer_proto) {{
    const _origGetChannelData = _AudioBuffer_proto.getChannelData;
    _AudioBuffer_proto.getChannelData = function(channel) {{
      const arr = _origGetChannelData.call(this, channel);
      for (let i = 0; i < arr.length; i++) {{
        arr[i] = arr[i] + {audio_noise} * (i % 2 === 0 ? 1 : -1);
      }}
      return arr;
    }};
  }}

  // ── navigator overrides ───────────────────────────────────────────────────
  Object.defineProperty(navigator, 'platform', {{
    get: () => "{platform}", configurable: true
  }});
  Object.defineProperty(navigator, 'hardwareConcurrency', {{
    get: () => {hw_conc}, configurable: true
  }});
  if ('deviceMemory' in navigator) {{
    Object.defineProperty(navigator, 'deviceMemory', {{
      get: () => {dev_mem}, configurable: true
    }});
  }}
  Object.defineProperty(navigator, 'languages', {{
    get: () => {langs_json}, configurable: true
  }});
  Object.defineProperty(navigator, 'language', {{
    get: () => "{languages[0]}", configurable: true
  }});

  // ── Timezone offset (не блокируем, просто смещаем getTimezoneOffset) ─────
  const _TZ_OFFSET = {tz_offset};
  const _origGetTZO = Date.prototype.getTimezoneOffset;
  Date.prototype.getTimezoneOffset = function() {{ return -_TZ_OFFSET; }};

  // ── Убрать webdriver флаг (дополнительный слой) ──────────────────────────
  try {{
    Object.defineProperty(navigator, 'webdriver', {{
      get: () => undefined, configurable: true
    }});
  }} catch(e) {{}}

}})();
"""


async def apply_fingerprint_spoof(
    page: Any = None,
    context: Any = None,
    seed: int | None = None,
) -> dict[str, Any]:
    """
    Применяет fingerprint-спуф к странице или контексту.

    Параметры
    ----------
    page    : playwright Page — применяется только к этой странице
    context : playwright BrowserContext — применяется ко всем будущим страницам
    seed    : int — фиксированное зерно рандома (None → случайное)

    Возвращает
    ----------
    {"status": "ok"|"error", "seed": int, "message": str}
    """
    if seed is None:
        seed = random.randint(1, 2**31 - 1)

    script = _build_spoof_script(seed)

    try:
        if context is not None:
            await context.add_init_script(script)
        elif page is not None:
            await page.add_init_script(script)
        else:
            return {"status": "error", "message": "Нужно передать page или context"}
        return {"status": "ok", "seed": seed}
    except Exception as exc:
        return {"status": "error", "seed": seed, "message": str(exc)}
