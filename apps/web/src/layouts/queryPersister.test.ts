import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import { SUBSCRIPTION_STATUS_QUERY_KEY } from "@/features/pricing/api/queries";
import { shouldPersistQuery } from "./queryPersister";

const DAY_MS = 24 * 60 * 60 * 1000;

function persistsPlan(planType: "pro" | "free", updatedAt = Date.now()) {
  const client = new QueryClient();
  client.setQueryData(
    SUBSCRIPTION_STATUS_QUERY_KEY,
    { plan_type: planType },
    { updatedAt },
  );
  const query = client.getQueryCache().find({
    queryKey: SUBSCRIPTION_STATUS_QUERY_KEY,
  });
  if (!query) throw new Error("the plan query was not cached");
  return shouldPersistQuery(query);
}

describe("shouldPersistQuery", () => {
  it("replays a paid plan so the app paints without waiting for the plan read", () => {
    expect(persistsPlan("pro")).toBe(true);
  });

  it("never replays an unpaid plan", () => {
    expect(persistsPlan("free")).toBe(false);
  });

  it("drops a paid plan read more than a day ago", () => {
    expect(persistsPlan("pro", Date.now() - DAY_MS - 1)).toBe(false);
  });

  it("keeps an unlisted query in memory only", () => {
    const client = new QueryClient();
    client.setQueryData(["conversations"], []);
    const [query] = client.getQueryCache().getAll();
    expect(shouldPersistQuery(query)).toBe(false);
  });
});
