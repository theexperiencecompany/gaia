"use client";

import dynamic from "next/dynamic";

// Four exploration directions for the referral share page. This .dev.tsx file
// is excluded from production builds via pageExtensions, so no chunk is emitted
// in prod. Lazy + ssr:false keeps the route isolated from app providers.
const ReferralDemoBody = dynamic(() => import("./ReferralDemoBody"), {
  ssr: false,
});

export default function ReferralsDevPage() {
  return <ReferralDemoBody />;
}
