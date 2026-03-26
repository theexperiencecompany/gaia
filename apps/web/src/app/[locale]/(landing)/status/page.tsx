import type { Metadata } from "next";
import { permanentRedirect } from "next/navigation";

import { generatePageMetadata } from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Status",
  description:
    "Check the real-time status of GAIA services, API uptime, and system health. Monitor service availability and get instant updates on any incidents or maintenance.",
  path: "/status",
  keywords: [
    "GAIA status",
    "service status",
    "API uptime",
    "system health",
    "service availability",
    "incident reports",
    "system monitoring",
    "uptime status",
    "Is GAIA down?",
  ],
});

export default function StatusPage() {
  permanentRedirect("https://status.heygaia.io");
}
