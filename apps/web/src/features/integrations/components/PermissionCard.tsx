import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface PermissionCardProps {
  title: string;
  description: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}

/**
 * The settings surface, borrowed: a titled card whose heading and one-line
 * explanation sit outside it, so the card holds only the controls. Both halves
 * of the modal use it, which is what makes them read as two decisions rather
 * than one long form.
 */
export const PermissionCard = ({
  title,
  description,
  action,
  children,
  className,
}: PermissionCardProps) => (
  <section>
    <div className="mb-1 flex items-center justify-between gap-3">
      <h3 className="text-sm font-medium text-zinc-200">{title}</h3>
      {action}
    </div>
    <p className="mb-2 text-xs text-zinc-500">{description}</p>
    <div className={cn("rounded-2xl bg-zinc-800/40 p-2", className)}>
      {children}
    </div>
  </section>
);
