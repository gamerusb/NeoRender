import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { readTenantId, writeTenantId } from "@/api";

type Ctx = {
  tenantId: string;
  setTenantId: (t: string) => void;
};

const TenantContext = createContext<Ctx | null>(null);

export function TenantProvider({ children }: { children: ReactNode }) {
  const [tenantId, setT] = useState(readTenantId);
  const setTenantId = useCallback((t: string) => {
    writeTenantId(t);
    setT(readTenantId());
  }, []);
  const v = useMemo(() => ({ tenantId, setTenantId }), [tenantId, setTenantId]);
  return <TenantContext.Provider value={v}>{children}</TenantContext.Provider>;
}

export function useTenant() {
  const c = useContext(TenantContext);
  if (!c) throw new Error("useTenant outside TenantProvider");
  return c;
}
