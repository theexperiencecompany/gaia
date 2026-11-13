import type { UpdateFilter } from "@shared/api/generated";
import { api } from "@/lib/api/typed";
import { UPDATES_PAGE_SIZE } from "../constants";

export const updatesApi = {
  list: (filter: UpdateFilter, before: string | null) =>
    api.get("/api/v1/updates", {
      query: {
        filter,
        before: before ?? undefined,
        limit: UPDATES_PAGE_SIZE,
      },
      errorMessage: "Failed to load updates",
    }),

  unseen: (since: string) =>
    api.get("/api/v1/updates/unseen", {
      query: { since },
      silent: true,
      background: true,
    }),
};
