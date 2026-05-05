import type { Metadata } from "next";
import NavbarDemoClient from "./NavbarDemoClient";

export const metadata: Metadata = {
  title: "Navbar Brainstorm — GAIA",
  robots: { index: false, follow: false },
};

export default function Page() {
  return <NavbarDemoClient />;
}
