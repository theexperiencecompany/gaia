"use client";

import { useLocale } from "next-intl";
import { useMemo, useSyncExternalStore } from "react";

const subscribeNever = () => () => undefined;

/**
 * Label an ISO time for a shared view's reader: the date alone when server
 * rendered, plus the reader-local time once hydrated, since the reader's time
 * zone exists only in the browser.
 */
export function useReaderDateLabel(iso: string): string {
  const locale = useLocale();
  const [localFormat, serverFormat] = useMemo(
    () => [
      new Intl.DateTimeFormat(locale, {
        dateStyle: "medium",
        timeStyle: "short",
      }),
      new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeZone: "UTC" }),
    ],
    [locale],
  );
  return useSyncExternalStore(
    subscribeNever,
    () => localFormat.format(new Date(iso)),
    () => serverFormat.format(new Date(iso)),
  );
}
