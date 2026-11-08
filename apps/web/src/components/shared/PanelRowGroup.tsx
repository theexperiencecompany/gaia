import type { ReactNode } from "react";

/** The surface a run of PanelRows sits on, so related rows read as one group. */
export function PanelRowGroup({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-col rounded-2xl bg-zinc-800 p-1">{children}</div>
  );
}
