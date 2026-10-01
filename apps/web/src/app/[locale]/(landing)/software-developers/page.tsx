import type { Metadata } from "next";
import SoftwareDevClient from "./SoftwareDevClient";

export const metadata: Metadata = {
  title: "For Software Developers — Ship Code, Not Status Updates",
  description:
    "GAIA monitors GitHub, Linear, and Slack in the background — triages what needs you, handles the rest, and delivers your standup before your first commit.",
  alternates: {
    canonical: "/for/software-developers",
  },
};

export default function SoftwareDevelopersPage() {
  return <SoftwareDevClient />;
}
