import type { Metadata } from "next";

import { generatePageMetadata } from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Payment Successful",
  description:
    "Your GAIA payment was processed. Verify your subscription status and continue to your personal AI assistant.",
  path: "/payment/success",
  noIndex: true,
});

export default function PaymentSuccessLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
