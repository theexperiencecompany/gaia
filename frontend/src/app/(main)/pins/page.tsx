import type { Metadata } from "next";

import Pins from "@/features/pins/components/PinsPage";

export const metadata: Metadata = {
  title: "Pinned Messages",
};

export default function Page() {
  return <Pins />;
}
