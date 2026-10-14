import type { ReactNode } from "react";

interface SettingsSectionProps {
  title?: string;
  titleAccessory?: ReactNode;
  description?: string;
  children: ReactNode;
  className?: string;
}

export function SettingsSection({
  title,
  titleAccessory,
  description,
  children,
  className = "",
}: SettingsSectionProps) {
  return (
    <div>
      {title && (
        <div className="mb-2 flex items-center gap-2">
          <p className="text-sm font-medium text-zinc-300">{title}</p>
          {titleAccessory}
        </div>
      )}
      {description && (
        <p className="mb-3 text-sm text-zinc-500">{description}</p>
      )}
      <div
        className={`divide-y divide-zinc-800/60 overflow-hidden rounded-2xl bg-zinc-900/60 ${className}`}
      >
        {children}
      </div>
    </div>
  );
}
