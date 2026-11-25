import type { ReactNode } from "react";

// A safety net for every use-case page: the API clears them the moment a
// workflow is published or unpublished (lib/publicPages.ts), and this daily
// rebuild covers a lost call. A literal, because Next refuses an imported value here.
export const revalidate = 86400;

export default function UseCasesLayout({ children }: { children: ReactNode }) {
  return children;
}
