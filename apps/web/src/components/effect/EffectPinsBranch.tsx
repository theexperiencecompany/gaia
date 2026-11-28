"use client";

import dynamic from "next/dynamic";

const EffectPinsPage = dynamic(
  () =>
    import("./pages/EffectPinsPage").then((module) => module.EffectPinsPage),
  { ssr: false, loading: () => null },
);

export function EffectPinsBranch({ apiBaseUrl }: { apiBaseUrl: string }) {
  return <EffectPinsPage apiBaseUrl={apiBaseUrl} />;
}
