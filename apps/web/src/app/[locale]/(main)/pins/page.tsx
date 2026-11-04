import "./page.css";
import "./page.2.css";
import "./page.3.css";
import "./page.4.css";
import "./page.5.css";
import type { Metadata } from "next";

import Pins from "@/features/pins/components/PinsPage";

export const metadata: Metadata = {
  title: "Pinned Messages",
};

export default function Page() {
  return <Pins />;
}
