import type { Metadata } from "next";

import { generatePageMetadata } from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Desktop Login",
  description:
    "Sign in to the GAIA desktop app. Authenticate in your browser and return to the app automatically.",
  path: "/desktop-login",
  noIndex: true,
});

export default function DesktopLoginLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
