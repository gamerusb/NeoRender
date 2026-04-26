import { QueuePage } from "@/pages/QueuePage";
import { renderWithProviders } from "@/test/renderWithProviders";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const apiFetchMock = vi.fn(async (path: string, _init?: RequestInit & { tenantId?: string }) => {
  if (path.startsWith("/api/tasks?")) {
    return {
      status: "ok",
      tasks: [
        { id: 1, status: "pending", original_video: "/tmp/a.mp4", target_profile: "p1" },
        { id: 2, status: "rendering", original_video: "/tmp/b.mp4", target_profile: "p2" },
        { id: 3, status: "success", original_video: "/tmp/c.mp4", target_profile: "p3" },
      ],
    };
  }
  return { status: "ok" };
});

vi.mock("@/api", async () => {
  const actual = await vi.importActual<typeof import("@/api")>("@/api");
  return {
    ...actual,
    apiFetch: (path: string, init?: RequestInit & { tenantId?: string }) => apiFetchMock(path, init),
  };
});

describe("QueuePage", () => {
  it("renders counters and tab filtering", async () => {
    renderWithProviders(<QueuePage />);

    await waitFor(() => expect(screen.getByText("Очередь задач")).toBeInTheDocument());
    expect(screen.getByText("Активных")).toBeInTheDocument();
    expect(screen.getByText("Завершено")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Ожидают/i }));
    expect(screen.getByText("a.mp4")).toBeInTheDocument();
  });

  it("calls pipeline start/stop actions", async () => {
    renderWithProviders(<QueuePage />);
    await waitFor(() => expect(screen.getByRole("button", { name: /Запустить/i })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /Запустить/i }));
    fireEvent.click(screen.getByRole("button", { name: /Пауза/i }));

    await waitFor(() =>
      expect(apiFetchMock.mock.calls.some((c) => String(c[0]) === "/api/pipeline/start")).toBe(true)
    );
    await waitFor(() =>
      expect(apiFetchMock.mock.calls.some((c) => String(c[0]) === "/api/pipeline/stop")).toBe(true)
    );
  });
});
