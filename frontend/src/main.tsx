import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router-dom";
import { App } from "./App";
import { TenantProvider } from "@/tenant/TenantContext";
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
        <HashRouter>
          <App />
        </HashRouter>
      </TenantProvider>
    </QueryClientProvider>
  </StrictMode>,
);
