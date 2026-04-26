import { AuthProvider, useAuth } from "@/auth/AuthContext";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

function AuthHarness() {
  const auth = useAuth();
  return (
    <div>
      <div data-testid="authed">{String(auth.isAuthenticated)}</div>
      <button onClick={() => void auth.login("admin@neorender.pro", "admin123")}>login</button>
      <button onClick={() => auth.logout()}>logout</button>
    </div>
  );
}

describe("AuthContext", () => {
  it("logs in via mock mode and updates auth state", async () => {
    // shouldUseMock() => true when /api/auth/ping returns 404
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 404 })));

    render(
      <AuthProvider>
        <AuthHarness />
      </AuthProvider>
    );

    expect(screen.getByTestId("authed")).toHaveTextContent("false");
    await userEvent.click(screen.getByRole("button", { name: "login" }));

    await waitFor(() => expect(screen.getByTestId("authed")).toHaveTextContent("true"));
    expect(localStorage.getItem("neo_auth_token")).toContain("mock_token_");
  });
});
