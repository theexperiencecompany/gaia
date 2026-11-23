import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface SettingsSectionHeaderProps {
  title?: string;
  titleAccessory?: ReactNode;
  description?: string;
}

/** A section's title with its description tucked right under it, for sections that draw their own body. */
export function SettingsSectionHeader({
  title,
  titleAccessory,
  description,
}: SettingsSectionHeaderProps) {
  if (!title && !description) return null;
  return (
    <header
      className={cn("flex flex-col gap-0.5", description ? "mb-3" : "mb-2")}
    >
      {title && (
        <div className="flex items-center gap-2">
          <p className="text-sm font-medium text-zinc-300">{title}</p>
          {titleAccessory}
        </div>
      )}
      {description && (
        <p className="text-sm text-pretty text-zinc-500">{description}</p>
      )}
    </header>
  );
}

interface SettingsSectionProps extends SettingsSectionHeaderProps {
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
    <section aria-label={title}>
      <SettingsSectionHeader
        title={title}
        titleAccessory={titleAccessory}
        description={description}
      />
      <div
        className={`divide-y divide-zinc-800/60 overflow-hidden rounded-2xl bg-zinc-900/60 ${className}`}
      >
        {children}
      </div>
    </section>
  );
}
