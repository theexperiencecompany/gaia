/**
 * The derivations `useIntegrations` hands every non-integrations-page surface.
 *
 * `getIntegrationStatus` used to return only `{integrationId, connected}`,
 * so an already-connected integration showed a first-time "Connect" CTA; it
 * now carries `status` (via `integrationConnectionState`) for "Reconnect",
 * and `expiredAt` for "Disconnected <n> ago". Fidelity: no renderer — these
 * drive the pure derivations directly; hook wiring and actual rendering aren't exercised.
 */
import type { MyIntegrationItem } from "@shared/types";
import {
  CONNECT_ACTION_LABEL,
  integrationConnectionState,
} from "@shared/utils";
import { describe, expect, it } from "vitest";
import {
  byConnectionStateThenName,
  findIntegrationStatus,
  toIntegration,
} from "@/features/integrations/utils/catalog";

function item(overrides: Partial<MyIntegrationItem> = {}): MyIntegrationItem {
  return {
    id: "gmail",
    name: "Gmail",
    description: "Email",
    category: "productivity",
    source: "platform",
    managedBy: "composio",
    status: "not_connected",
    requiresAuth: true,
    isFeatured: false,
    displayPriority: 0,
    available: true,
    toolCount: 3,
    cloneCount: 0,
    ...overrides,
  };
}

const statusOf = (items: MyIntegrationItem[], id: string) =>
  findIntegrationStatus(items, id);

describe("findIntegrationStatus", () => {
  it("carries the backend status, not just the connected boolean", () => {
    const record = statusOf([item({ status: "expired" })], "gmail");

    expect(record).toEqual({
      integrationId: "gmail",
      connected: false,
      status: "expired",
    });
  });

  it("lets a caller label a dead connection Reconnect instead of Connect", () => {
    const items = [
      item({ status: "expired" }),
      item({ id: "slack", name: "Slack" }),
    ];
    const label = (id: string) =>
      CONNECT_ACTION_LABEL[
        integrationConnectionState(statusOf(items, id)?.status)
      ];

    expect(label("gmail")).toBe("Reconnect");
    expect(label("slack")).toBe("Connect");
  });

  it("labels an added-but-never-authenticated integration Retry", () => {
    const items = [item({ status: "created" })];

    expect(
      CONNECT_ACTION_LABEL[
        integrationConnectionState(statusOf(items, "gmail")?.status)
      ],
    ).toBe("Retry");
  });

  it("matches the integration id case-insensitively", () => {
    const items = [item({ id: "GoogleCalendar", status: "connected" })];

    const record = statusOf(items, "googlecalendar");

    expect(record?.status).toBe("connected");
    expect(record?.connected).toBe(true);
  });

  it("returns undefined for an integration missing from the catalog", () => {
    expect(statusOf([item({})], "notion")).toBeUndefined();
  });
});

describe("toIntegration", () => {
  it("carries expiredAt through so the row can say when the grant died", () => {
    const mapped = toIntegration(
      item({ status: "expired", expiredAt: "2026-08-15T09:00:00Z" }),
    );

    expect(mapped.expiredAt).toBe("2026-08-15T09:00:00Z");
  });

  it("normalizes a null expiredAt to undefined", () => {
    const mapped = toIntegration(
      item({ status: "connected", expiredAt: null }),
    );

    expect(mapped.expiredAt).toBeUndefined();
  });
});

describe("byConnectionStateThenName", () => {
  it("puts what needs attention first, then connected, then the rest", () => {
    const sorted = [
      item({ id: "slack", name: "Slack", status: "not_connected" }),
      item({ id: "notion", name: "Notion", status: "connected" }),
      item({ id: "gmail", name: "Gmail", status: "expired" }),
      item({ id: "linear", name: "Linear", status: "created" }),
    ]
      .map(toIntegration)
      .toSorted(byConnectionStateThenName)
      .map((i) => i.id);

    expect(sorted).toEqual(["gmail", "linear", "notion", "slack"]);
  });

  it("falls back to name order within one state", () => {
    const sorted = [
      item({ id: "zulip", name: "Zulip", status: "connected" }),
      item({ id: "asana", name: "Asana", status: "connected" }),
    ]
      .map(toIntegration)
      .toSorted(byConnectionStateThenName)
      .map((i) => i.name);

    expect(sorted).toEqual(["Asana", "Zulip"]);
  });
});
