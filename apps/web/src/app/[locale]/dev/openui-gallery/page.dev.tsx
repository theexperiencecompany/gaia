"use client";

import dynamic from "next/dynamic";

// Heavy primitive showcase — lazy-loaded so the page chunk stays small
// and SSR is skipped. URL access is gated by `[locale]/dev/layout.tsx`,
// so the prod build never serves this page even though the chunk exists.
const DemoBody = dynamic(() => import("./DemoBody"), { ssr: false });

export default function OpenUIGalleryPage() {
  return <DemoBody />;
}
