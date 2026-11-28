"use client";

import dynamic from "next/dynamic";

const EffectNotificationsPage = dynamic(
  () =>
    import("./pages/EffectNotificationsPage").then(
      (module) => module.EffectNotificationsPage,
    ),
  { ssr: false, loading: () => null },
);

export function EffectNotificationsBranch({
  apiBaseUrl,
  embedded,
  tab,
}: {
  apiBaseUrl: string;
  embedded?: boolean;
  tab?: "unread" | "all";
}) {
  return (
    <EffectNotificationsPage
      apiBaseUrl={apiBaseUrl}
      embedded={embedded}
      tab={tab}
    />
  );
}
