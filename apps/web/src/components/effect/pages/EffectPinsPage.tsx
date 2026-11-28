"use client";

import { PinsPage } from "@heygaia/effect-ui/pages/pins/PinsPage";
import { EffectRoot } from "@/components/effect/EffectRoot";

const PINS_PROPS = {};

/** Client adapter: the page component is a function, so it must be imported
 * inside the client bundle rather than passed from a Server Component. */
export function EffectPinsPage({ apiBaseUrl }: { apiBaseUrl: string }) {
  return (
    <EffectRoot
      component={PinsPage}
      props={PINS_PROPS}
      apiBaseUrl={apiBaseUrl}
    />
  );
}
