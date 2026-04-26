import { PackageOpen } from "lucide-react";

interface EmptyStateProps {
  title?: string;
  body?: string;
  icon?: React.ReactNode;
}

export function EmptyState({
  title = "Нет данных",
  body,
  icon,
}: EmptyStateProps) {
  return (
    <div className="empty-state">
      <div className="empty-state-icon">
        {icon ?? <PackageOpen size={36} />}
      </div>
      <div className="empty-state-title">{title}</div>
      {body && <div className="empty-state-body">{body}</div>}
    </div>
  );
}
