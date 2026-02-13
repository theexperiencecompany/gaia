"use client";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

import type { MailTab } from "@/types/features/mailTypes";

const VALID_TABS: MailTab[] = [
  "inbox",
  "sent",
  "spam",
  "starred",
  "trash",
  "drafts",
];

export function useMailTabs() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const rawTab = searchParams.get("tab");
  const activeTab: MailTab =
    rawTab && VALID_TABS.includes(rawTab as MailTab)
      ? (rawTab as MailTab)
      : "inbox";

  const setActiveTab = useCallback(
    (tab: MailTab) => {
      const params = new URLSearchParams(searchParams.toString());
      if (tab === "inbox") {
        params.delete("tab");
      } else {
        params.set("tab", tab);
      }
      const query = params.toString();
      router.push(query ? `${pathname}?${query}` : pathname);
    },
    [searchParams, router, pathname],
  );

  return { activeTab, setActiveTab };
}
