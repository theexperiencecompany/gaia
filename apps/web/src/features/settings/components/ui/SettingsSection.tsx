import type { ReactNode } from "react";

interface SettingsSectionProps {
  title?: string;
  description?: string;
  children: ReactNode;
  className?: string;
}

export function SettingsSection({
  title,
  description,
  children,
  className = "",
}: SettingsSectionProps) {
  return (
    <div>
      {title && (
        <p className="mb-2 text-xs font-medium uppercase tracking-wider text-zinc-500">
          {title}
        </p>
      )}
      {description && (
        <p className="mb-3 text-sm text-zinc-500">{description}</p>
      )}
      <div
        className={`divide-y divide-zinc-800 overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900 ${className}`}
      >
        {children}
      </div>
    </div>
  );
}
