"use client";

import { SettingsAccountPage } from "@heygaia/effect-ui/pages/settings/SettingsAccountPage";
import { EffectRoot } from "@/components/effect/EffectRoot";

const SETTINGS_PROPS = {};

/** Client adapter: the page component is a function, so it must be imported
 * inside the client bundle rather than passed from a Server Component. */
export function EffectSettingsAccountPage({
  apiBaseUrl,
}: {
  readonly apiBaseUrl: string;
}) {
  return (
    <EffectRoot
      component={SettingsAccountPage}
      props={SETTINGS_PROPS}
      apiBaseUrl={apiBaseUrl}
    />
  );
}
