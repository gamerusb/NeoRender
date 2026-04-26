import { Layout } from "@/layout/Layout";
import { renderWithProviders } from "@/test/renderWithProviders";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/api", async () => {
  const actual = await vi.importActual<typeof import("@/api")>("@/api");
  return {
    ...actual,
    apiFetch: vi.fn(async (path: string) => {
      if (String(path).includes("/api/analytics")) return { status: "ok", analytics: [] };
      if (String(path).includes("/api/tasks")) return { status: "ok", tasks: [] };
      return { status: "ok" };
    }),
  };
});

vi.mock("@/components/CommandPalette", () => ({
  CommandPalette: () => null,
}));

describe("Layout", () => {
  it("renders shell and allows tenant custom apply", async () => {
    renderWithProviders(
      <Routes>
        <Route element={<Layout />}>
          <Route path="/queue" element={<div>QueueContent</div>} />
        </Route>
      </Routes>,
      "/queue"
    );

    expect(screen.getAllByText("NeoRender").length).toBeGreaterThan(0);
    expect(screen.getByText("Очередь")).toBeInTheDocument();
    fireEvent.change(screen.getByDisplayValue("default"), { target: { value: "__custom__" } });
    fireEvent.change(screen.getByPlaceholderText("team_kr_01"), { target: { value: "acme_team" } });
    fireEvent.click(screen.getByRole("button", { name: "Применить" }));

    await waitFor(() => expect(localStorage.getItem("neoTenantId")).toBe("acme_team"));
  });
});
