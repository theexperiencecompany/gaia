import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { generatePageMetadata } from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Desktop App",
  description:
    "Download the GAIA desktop app for Windows, macOS, and Linux. Get a native AI assistant experience with offline support and system integration.",
  path: "/desktop",
  keywords: [
    "GAIA desktop app",
    "download GAIA",
    "desktop AI assistant",
    "Windows app",
    "macOS app",
    "Linux app",
  ],
});

export default function DesktopPage() {
  redirect("/download");
}
