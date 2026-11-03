"use client";

import dynamic from "next/dynamic";

// Client-only: the notes load from localStorage, which the server render cannot see.
const PaywallLab = dynamic(
  () => import("./PaywallLab").then((mod) => mod.PaywallLab),
  { ssr: false },
);

export default function PaywallLabPage() {
  return <PaywallLab />;
}
