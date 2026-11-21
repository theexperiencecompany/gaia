import type { ComponentType, ReactNode } from "react";

/** Where a task needs you, above its properties: an amber line naming what, then the detail and the way out. */
export function AskShell({
  label,
  Icon,
  children,
}: {
  label: string;
  Icon: ComponentType<{ className?: string }>;
  children: ReactNode;
}) {
  return (
    <section className="space-y-3 rounded-2xl bg-zinc-800 p-4">
      <p className="flex items-center gap-1.5 text-xs font-medium text-amber-400">
        <Icon className="size-3.5" />
        {label}
      </p>
      {children}
    </section>
  );
}
