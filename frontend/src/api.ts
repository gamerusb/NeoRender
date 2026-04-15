/** Префикс API: UI на /ui/ → API на /api/ от корня сайта. */
export function apiPrefix(): string {
  const path = window.location.pathname || "/";
  const m = path.match(/^(.+)\/ui(?:\/|$)/i);
  return m ? m[1] : "";
}

export function apiUrl(rel: string): string {
  const p = rel.startsWith("/") ? rel : `/${rel}`;
  return `${apiPrefix()}${p}`;
}

const TENANT_KEY = "neoTenantId";

export function readTenantId(): string {
  try {
    return localStorage.getItem(TENANT_KEY)?.trim() || "default";
  } catch {
    return "default";
  }
}

export function writeTenantId(tenant: string): void {
  const t = tenant.trim().toLowerCase() || "default";
  localStorage.setItem(TENANT_KEY, t);
}

export type ApiJson = Record<string, unknown>;

export async function apiFetch<T = ApiJson>(
  path: string,
  init?: RequestInit & { tenantId?: string },
): Promise<T> {
  if (window.location.protocol === "file:") {
    throw new Error(
      "Откройте интерфейс через сервер, например http://127.0.0.1:8765/ui/",
    );
  }
  const url = path.startsWith("http") ? path : apiUrl(path);
  const headers = new Headers(init?.headers);
  headers.set("X-Tenant-ID", init?.tenantId ?? readTenantId());
  if (!headers.has("Content-Type") && init?.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const { tenantId: _t, ...rest } = init ?? {};
  const res = await fetch(url, { ...rest, headers });
  const raw = await res.text();
  let data: ApiJson = {};
  if (raw.trim()) {
    try {
      data = JSON.parse(raw) as ApiJson;
    } catch {
      throw new Error(`Ответ не JSON (${res.status})`);
    }
  }
  if (!res.ok || data.status === "error") {
    const msg =
      (typeof data.message === "string" && data.message) ||
      `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return data as T;
}

/** Скачать готовый mp4 задачи (нужен заголовок X-Tenant-ID — не открывать простым <a href>). */
export async function downloadTaskMp4(taskId: number, tenantId: string): Promise<void> {
  const url = apiUrl(`/api/tasks/${taskId}/download`);
  const res = await fetch(url, { headers: { "X-Tenant-ID": tenantId } });
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const j = (await res.json()) as { message?: string; status?: string };
      if (typeof j.message === "string" && j.message) msg = j.message;
    } catch {
      /* ignore */
    }
    throw new Error(msg);
  }
  const blob = await res.blob();
  const cd = res.headers.get("Content-Disposition");
  let filename = `neorender-task-${taskId}.mp4`;
  if (cd) {
    const m = /filename\*?=(?:UTF-8''|")?([^";\n]+)"?/i.exec(cd);
    if (m?.[1]) {
      try {
        filename = decodeURIComponent(m[1].replaceAll('"', "").trim());
      } catch {
        filename = m[1].replaceAll('"', "").trim();
      }
    }
  }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(a.href);
}
