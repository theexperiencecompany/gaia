"use client";

import dynamic from "next/dynamic";

const EffectSettingsAccountPage = dynamic(
  () =>
    import("./pages/EffectSettingsAccountPage").then(
      (module) => module.EffectSettingsAccountPage,
    ),
  { ssr: false, loading: () => null },
);

export function EffectSettingsAccountBranch({
  apiBaseUrl,
}: {
  apiBaseUrl: string;
}) {
  return <EffectSettingsAccountPage apiBaseUrl={apiBaseUrl} />;
}
