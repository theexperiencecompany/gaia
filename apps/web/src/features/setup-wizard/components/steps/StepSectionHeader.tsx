import type { ReactNode } from "react";

interface StepSectionHeaderProps {
  icon: ReactNode;
  title: string;
  /** One line on what this section is for. */
  description: string;
  accessory?: ReactNode;
}

/** A wizard card's heading: an icon, a title and the one line that tells it apart from its neighbours. */
export function StepSectionHeader({
  icon,
  title,
  description,
  accessory,
}: StepSectionHeaderProps) {
  return (
    <div className="mb-3 flex items-start gap-3">
      <span className="flex size-8 shrink-0 items-center justify-center rounded-xl bg-zinc-900 text-zinc-300">
        {icon}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-zinc-100">{title}</p>
        <p className="text-xs text-zinc-500">{description}</p>
      </div>
      {accessory}
    </div>
  );
}
