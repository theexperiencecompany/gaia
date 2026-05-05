"use client";

import dynamic from "next/dynamic";
import { notFound } from "next/navigation";

// Resolve the heavy demo body only in development. `process.env.NODE_ENV` is
// inlined at build time, so the production bundle drops the import entirely
// (no chart / map / audio / primitive code reaches the client).
const DemoBody =
  process.env.NODE_ENV === "development"
    ? dynamic(() => import("./DemoBody"), { ssr: false })
    : null;

export default function OpenUIDemoPage() {
  if (!DemoBody) notFound();
  return <DemoBody />;
}
