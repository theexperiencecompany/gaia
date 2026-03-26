import type { Metadata } from "next";
import AgencyClient from "./AgencyClient";

export const metadata: Metadata = {
  title: "GAIA for Agency Owners — Run 10 Clients Without Losing Your Mind",
  description:
    "GAIA monitors your client portfolio, writes status reports, and keeps your pipeline moving — while you focus on the work that actually grows your agency.",
  alternates: {
    canonical: "/for/agency-owners",
  },
};

export default function AgencyOwnersPage() {
  return <AgencyClient />;
}
