import type { Metadata } from "next";

import { generatePageMetadata } from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Payment",
  description:
    "The result of your GAIA payment: confirm your subscription and continue, or try the checkout again.",
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
