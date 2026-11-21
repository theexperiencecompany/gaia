import { Divider } from "@heroui/divider";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** A heading over a hairline, then its rows: the page's only structure. */
export default function TaskSection({
  id,
  title,
  count,
  description,
  urgent = false,
  action,
  children,
}: {
  id: string;
  title: string;
  count?: number;
  /** One line under the heading, for a section that needs introducing. */
  description?: string;
  /** The one section that asks for attention: its count becomes an amber badge. */
  urgent?: boolean;
  /** Quiet control at the far end of the heading line. */
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section aria-labelledby={`section-${id}`}>
      <header className="px-2">
        <div className="flex h-7 items-center gap-2">
          <h2
            id={`section-${id}`}
            className="text-[17px] font-semibold tracking-[-0.015em] text-zinc-50"
          >
            {title}
          </h2>
          {count !== undefined && (
            <span
              className={cn(
                "tabular-nums",
                urgent
                  ? "rounded-full bg-amber-400/15 px-1.5 py-px text-xs font-semibold text-amber-400"
                  : "text-[15px] text-zinc-600",
              )}
            >
              {count}
            </span>
          )}
          {action && <div className="ml-auto">{action}</div>}
        </div>
        {description && (
          <p className="mt-0.5 text-[13px] text-zinc-400">{description}</p>
        )}
      </header>
      <Divider className="mb-1 mt-2.5 bg-zinc-800" />
      {children}
    </section>
  );
}
