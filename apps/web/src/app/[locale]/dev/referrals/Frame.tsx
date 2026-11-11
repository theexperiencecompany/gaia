import type { ReactNode } from "react";

/** One labelled specimen in the gallery. */
export function Frame({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <figure className="flex flex-col gap-3">
      <figcaption className="text-xs text-zinc-500">{label}</figcaption>
      {children}
    </figure>
  );
}
