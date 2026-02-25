import type { ReactNode } from "react";

interface SettingsFieldProps {
  label: string;
  description?: string;
  children: ReactNode;
  labelSuffix?: ReactNode;
}

export function SettingsField({
  label,
  description,
  children,
  labelSuffix,
}: SettingsFieldProps) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-zinc-500">{label}</p>
        {labelSuffix}
      </div>
      {children}
      {description && <p className="text-xs text-zinc-600">{description}</p>}
    </div>
  );
}
