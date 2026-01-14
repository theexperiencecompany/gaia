import type { ReactNode } from "react";

interface MetaInfoCardProps {
  icon: ReactNode;
  label: string;
  value: string | ReactNode;
}

export default function MetaInfoCard({
  icon,
  label,
  value,
}: MetaInfoCardProps) {
  return (
    <div className="flex items-center gap-2.5 rounded-2xl bg-surface-100 px-4 py-2">
      {icon}
      <div className="flex flex-col">
        <span className="text-xs text-foreground-500">{label}</span>
        <span className="text-sm font-medium text-foreground">{value}</span>
      </div>
    </div>
  );
}
