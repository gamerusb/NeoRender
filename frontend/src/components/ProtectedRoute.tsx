import { Navigate, useLocation } from "react-router-dom";
import { useAuth, type UserRole } from "@/auth/AuthContext";

interface Props {
  children: React.ReactNode;
  /** Если указана — пропускаем только пользователей с этой ролью */
  requiredRole?: UserRole;
}

export function ProtectedRoute({ children, requiredRole }: Props) {
  const { isAuthenticated, user } = useAuth();
  const location = useLocation();

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  if (requiredRole && user?.role !== requiredRole) {
    return <Navigate to="/dashboard" replace />;
  }

  return <>{children}</>;
}
