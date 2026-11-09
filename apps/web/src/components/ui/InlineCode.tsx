import type { ReactNode } from "react";

export default function InlineCode({ children }: { children: ReactNode }) {
  return (
    <code className="rounded bg-zinc-800 px-2 py-1 text-sm text-primary">
      {children}
    </code>
  );
}
