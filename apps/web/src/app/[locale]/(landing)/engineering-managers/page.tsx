import type { Metadata } from "next";
import EngineeringManagerClient from "./EngineeringManagerClient";

export const metadata: Metadata = {
  title:
    "GAIA for Engineering Managers — Lead Your Team Without Losing Technical Context",
  description:
    "GAIA monitors GitHub, Linear, and Slack so you don't have to. It preps your 1:1s, surfaces team blockers, and keeps you informed — without reading every thread.",
  alternates: {
    canonical: "/for/engineering-managers",
  },
};

export default function EngineeringManagersPage() {
  return <EngineeringManagerClient />;
}
