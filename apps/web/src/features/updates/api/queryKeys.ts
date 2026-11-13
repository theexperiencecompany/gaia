import type { UpdateFilter } from "@shared/api/generated";

export const updatesKeys = {
  all: ["updates"] as const,
  feed: (filter: UpdateFilter) => ["updates", "feed", filter] as const,
  unseen: (since: string) => ["updates", "unseen", since] as const,
};
