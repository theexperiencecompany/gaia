import type { Metadata } from "next";
import SalesClient from "./SalesClient";

export const metadata: Metadata = {
  title: "GAIA for Sales — You're Paid to Close Deals, Not Update Your CRM",
  description:
    "GAIA monitors your pipeline around the clock, spots deals going cold, and drafts follow-ups before you remember to check. Your CRM stays current without you touching it.",
  alternates: {
    canonical: "/for/sales-professionals",
  },
};

export default function SalesProfessionalsPage() {
  return <SalesClient />;
}
