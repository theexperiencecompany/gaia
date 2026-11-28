"use client";

import { useMemo } from "react";
import { NotificationsPage } from "@heygaia/effect-ui/pages/notifications/NotificationsPage";
import { EffectRoot } from "@/components/effect/EffectRoot";

/** Client adapter: the page component is a function, so it must be imported
 * inside the client bundle rather than passed from a Server Component. */
export function EffectNotificationsPage({
  apiBaseUrl,
  embedded = false,
  tab = "unread",
}: {
  apiBaseUrl: string;
  embedded?: boolean;
  tab?: "unread" | "all";
}) {
  const props = useMemo(() => ({ embedded, tab }), [embedded, tab]);

  return (
    <EffectRoot
      component={NotificationsPage}
      props={props}
      apiBaseUrl={apiBaseUrl}
    />
  );
}
