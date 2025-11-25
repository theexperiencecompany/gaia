import type { ReactNode } from "react";

interface LabeledFieldProps {
  label: string;
  children: ReactNode;
  className?: string;
}

export function LabeledField({
  label,
  children,
  className = "",
}: LabeledFieldProps) {
  return (
    <div className={`space-y-1 ${className}`}>
      <div className="text-xs font-medium text-zinc-400">{label}</div>
      {children}
    </div>
  );
}
