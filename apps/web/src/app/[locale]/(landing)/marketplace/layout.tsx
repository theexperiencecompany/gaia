import type { ReactNode } from "react";

// A safety net for every marketplace page: the API clears them the moment an
// integration or a workflow changes (lib/publicPages.ts), and this daily rebuild
// covers a lost call. A literal, because Next refuses an imported value here.
export const revalidate = 86400;

export default function MarketplaceLayout({
  children,
}: {
  children: ReactNode;
}) {
  return children;
}
