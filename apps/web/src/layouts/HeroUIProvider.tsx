"use client";

import { useRouter } from "next/navigation";
import { RouterProvider } from "react-aria-components";

declare module "react-aria-components" {
  interface RouterConfig {
    routerOptions: NonNullable<
      Parameters<ReturnType<typeof useRouter>["push"]>[1]
    >;
  }
}

/** Route HeroUI's href props (Link, Menu.Item, Tabs.Tab) through the Next.js router instead of a full page load. */
export function HeroUIProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();

  return <RouterProvider navigate={router.push}>{children}</RouterProvider>;
}
