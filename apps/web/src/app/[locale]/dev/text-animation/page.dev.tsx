"use client";

import dynamic from "next/dynamic";

// Streaming text-animation playground. This .dev.tsx file is only routable in
// development (excluded from production builds via pageExtensions), so no chunk
// is emitted in prod.
const DemoBody = dynamic(() => import("./DemoBody"), { ssr: false });

export default function TextAnimationDemoPage() {
  return <DemoBody />;
}
