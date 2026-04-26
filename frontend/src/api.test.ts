import { apiFetch, apiPrefix, apiUrl, readTenantId, writeTenantId } from "@/api";
import { afterEach, describe, expect, it, vi } from "vitest";

describe("api helpers", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    window.history.replaceState({}, "", "/");
  });

  it("builds prefix and url from /ui path", () => {
    window.history.replaceState({}, "", "/app/ui/dashboard");
    expect(apiPrefix()).toBe("/app");
    expect(apiUrl("/api/ping")).toBe("/app/api/ping");
  });

  it("reads and writes tenant id", () => {
    expect(readTenantId()).toBe("default");
    writeTenantId("  ACME  ");
    expect(readTenantId()).toBe("acme");
  });

  it("apiFetch sends tenant header and parses json", async () => {
    window.history.replaceState({}, "", "/ui/");
    localStorage.setItem("neoTenantId", "acme");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok", value: 42 }), { status: 200 })
    );
    vi.stubGlobal("fetch", fetchMock);

    const out = await apiFetch<{ status: string; value: number }>("/api/x", { method: "POST", body: "{}" });
    expect(out.value).toBe(42);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0];
    const headers = new Headers(init?.headers);
    expect(headers.get("X-Tenant-ID")).toBe("acme");
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("apiFetch throws on API error payload", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "error", message: "boom" }), { status: 200 })
    );
    vi.stubGlobal("fetch", fetchMock);
    await expect(apiFetch("/api/fail")).rejects.toThrow("boom");
  });
});
