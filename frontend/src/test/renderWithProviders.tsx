import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TenantProvider } from "@/tenant/TenantContext";
import { AuthProvider } from "@/auth/AuthContext";
import { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { render } from "@testing-library/react";

export function renderWithProviders(ui: ReactNode, initialRoute = "/") {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  });
  return render(
    <MemoryRouter initialEntries={[initialRoute]}>
      <QueryClientProvider client={qc}>
        <TenantProvider>
          <AuthProvider>{ui}</AuthProvider>
        </TenantProvider>
      </QueryClientProvider>
    </MemoryRouter>
  );
}
