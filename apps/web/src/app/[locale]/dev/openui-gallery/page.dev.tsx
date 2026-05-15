"use client";

import dynamic from "next/dynamic";

// Heavy primitive showcase — lazy-loaded so the page chunk stays small
// and SSR is skipped. This .dev.tsx file is excluded from production builds
// via pageExtensions, so no chunk is emitted in prod.
const DemoBody = dynamic(() => import("./DemoBody"), { ssr: false });

export default function OpenUIGalleryPage() {
  return <DemoBody />;
}
