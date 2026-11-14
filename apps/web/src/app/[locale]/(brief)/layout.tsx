import type { Metadata } from "next";
import type { ReactNode } from "react";

/**
 * A single brief on its own full page, outside the (main) sidebar shell: the email
 * image, the chat link and the Briefings list all open it here. Per-user content, so
 * it is never indexed.
 */
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Your brief",
  robots: { index: false, follow: false },
};

export default function BriefLayout({ children }: { children: ReactNode }) {
  return children;
}
