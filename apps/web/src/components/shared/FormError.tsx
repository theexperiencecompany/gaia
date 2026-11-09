import { Alert01Icon } from "@icons";
import type { ReactNode } from "react";

/** A form's inline error, announced to screen readers. */
export function FormError({ children }: { children: ReactNode }) {
  return (
    <div
      role="alert"
      className="flex items-center gap-2 rounded-xl bg-red-400/10 px-3 py-2 text-sm text-red-400"
    >
      <Alert01Icon height={17} className="shrink-0" />
      {children}
    </div>
  );
}
