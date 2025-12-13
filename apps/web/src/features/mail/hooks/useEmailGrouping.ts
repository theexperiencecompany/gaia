import { useMemo } from "react";

import type { EmailData } from "@/types/features/mailTypes";

// Interface for our grouped items (either a section header or an email)
export interface ListItem {
  type: "header" | "email";
  data: string | EmailData;
}

/**
 * Hook for grouping emails by time periods (Today, Yesterday, Last 7 Days, etc.)
 */
export const useEmailGrouping = (emails: EmailData[]) => {
  const groupedItems = useMemo(() => {
    if (!emails.length) return [];

    const today = new Date();
    today.setHours(0, 0, 0, 0);

    const yesterday = new Date(today);
    yesterday.setDate(yesterday.getDate() - 1);

    const lastWeekStart = new Date(today);
    lastWeekStart.setDate(lastWeekStart.getDate() - 7);

    const lastMonthStart = new Date(today);
    lastMonthStart.setDate(lastMonthStart.getDate() - 30);

    // Create sections
    const todayEmails: EmailData[] = [];
    const yesterdayEmails: EmailData[] = [];
    const lastWeekEmails: EmailData[] = [];
    const lastMonthEmails: EmailData[] = [];
    const olderEmails: EmailData[] = [];

    // Sort and place emails in appropriate sections
    emails.forEach((email) => {
      const emailDate = new Date(email.time);

      if (emailDate >= today) {
        todayEmails.push(email);
      } else if (emailDate >= yesterday) {
        yesterdayEmails.push(email);
      } else if (emailDate >= lastWeekStart) {
        lastWeekEmails.push(email);
      } else if (emailDate >= lastMonthStart) {
        lastMonthEmails.push(email);
      } else {
        olderEmails.push(email);
      }
    });

    // Combine all sections with headers into a flat list
    const items: ListItem[] = [];

    if (todayEmails.length > 0) {
      items.push({ type: "header", data: "Today" });
      todayEmails.forEach((email) =>
        items.push({ type: "email", data: email }),
      );
    }

    if (yesterdayEmails.length > 0) {
      items.push({ type: "header", data: "Yesterday" });
      yesterdayEmails.forEach((email) =>
        items.push({ type: "email", data: email }),
      );
    }

    if (lastWeekEmails.length > 0) {
      items.push({ type: "header", data: "Last 7 Days" });
      lastWeekEmails.forEach((email) =>
        items.push({ type: "email", data: email }),
      );
    }

    if (lastMonthEmails.length > 0) {
      items.push({ type: "header", data: "Last 30 Days" });
      lastMonthEmails.forEach((email) =>
        items.push({ type: "email", data: email }),
      );
    }

    if (olderEmails.length > 0) {
      items.push({ type: "header", data: "Older" });
      olderEmails.forEach((email) =>
        items.push({ type: "email", data: email }),
      );
    }

    return items;
  }, [emails]);

  return groupedItems;
};
