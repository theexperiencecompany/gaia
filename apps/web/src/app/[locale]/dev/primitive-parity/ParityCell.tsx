import type { ReactNode } from "react";

/** One fixture combination: its id above it, and the primitive inside the node the parity harness reads. */
export function ParityCell({
  id,
  wide = false,
  children,
}: {
  id: string;
  wide?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="font-mono text-[10px] text-zinc-500">{id}</span>
      <div data-parity={id} className={wide ? "w-72" : "w-fit"}>
        {children}
      </div>
    </div>
  );
}

/** A titled row of fixture cells. */
export function ParitySection({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-sm font-medium text-zinc-400">{title}</h2>
      <div className="flex flex-wrap items-start gap-6">{children}</div>
    </section>
  );
}
