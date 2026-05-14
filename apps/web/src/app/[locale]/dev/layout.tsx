import { notFound } from "next/navigation";
import type { ReactNode } from "react";
import { HeroUIProvider } from "@/layouts/HeroUIProvider";

/**
 * Dev-only routes live under [locale]/dev/. The check is on
 * `process.env.NODE_ENV` which Next.js inlines at build time — production
 * bundles drop the children entirely and render a 404 instead.
 */
export default function DevLayout({ children }: { children: ReactNode }) {
  if (process.env.NODE_ENV !== "development") {
    notFound();
  }
  return <HeroUIProvider>{children}</HeroUIProvider>;
}
