"use client";

import dynamic from "next/dynamic";

// Five takes on the bottom-right corner referral bar, shown side by side in a
// gallery of mock "app corner" cells. This .dev.tsx file is excluded from
// production builds via pageExtensions, so no chunk is emitted in prod. Lazy +
// ssr:false keeps the route isolated from app providers.
const CornerBarGallery = dynamic(() => import("./CornerBarGallery"), {
  ssr: false,
});

export default function ReferralBarDevPage() {
  return <CornerBarGallery />;
}
