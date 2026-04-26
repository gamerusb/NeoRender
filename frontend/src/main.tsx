import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router-dom";
import { App } from "./App";
import { TenantProvider } from "@/tenant/TenantContext";
import { AuthProvider } from "@/auth/AuthContext";
import "./app-shell.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 4_000, retry: 1, refetchOnWindowFocus: false },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <TenantProvider>
        <AuthProvider>
          <HashRouter>
            <App />
          </HashRouter>
        </AuthProvider>
      </TenantProvider>
    </QueryClientProvider>
  </StrictMode>,
);
