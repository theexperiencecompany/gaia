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
      <label className="text-xs font-medium text-zinc-400">{label}</label>
      {children}
    </div>
  );
}
