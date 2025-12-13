import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { generatePageMetadata } from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Join Our WhatsApp Community",
  description:
    "Join the GAIA WhatsApp community for instant updates, tips, and discussions. Get quick support, share feedback, and connect with other GAIA users on WhatsApp.",
  path: "/whatsapp",
  keywords: [
    "GAIA WhatsApp",
    "WhatsApp community",
    "WhatsApp group",
    "instant support",
    "WhatsApp updates",
    "join WhatsApp",
    "GAIA community",
    "mobile community",
  ],
});

export default function WhatsAppPage() {
  redirect("https://whatsapp.heygaia.io");
}
