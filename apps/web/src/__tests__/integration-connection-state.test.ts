/**
 * The render-layer mapping behind the integrations Reconnect affordance.
 *
 * `integrationConnectionState` is what stops a dead connection from rendering
 * as "Connected" (the bug) or as a first-time "Connect" (which hides that it
 * broke). It is shared by the web list/card and the mobile row, so it is
 * tested here — the only vitest project that collects `libs/shared/ts`.
 */
import {
  CONNECT_ACTION_LABEL,
  INTEGRATION_STATE_ORDER,
  integrationConnectionState,
} from "@shared/utils";
import { describe, expect, it } from "vitest";

describe("integrationConnectionState", () => {
  it("maps each backend status to the state the UI renders", () => {
    expect(integrationConnectionState("connected")).toBe("connected");
    expect(integrationConnectionState("created")).toBe("pending");
    expect(integrationConnectionState("expired")).toBe("expired");
    expect(integrationConnectionState("not_connected")).toBe("disconnected");
  });

  it("degrades an unknown or missing status to disconnected", () => {
    // A status the API grows after this build ships must never render blank,
    // and must never render as usable.
    expect(integrationConnectionState("some_future_status")).toBe(
      "disconnected",
    );
    expect(integrationConnectionState(undefined)).toBe("disconnected");
  });

  it("labels a dead connection Reconnect, never Connect", () => {
    expect(CONNECT_ACTION_LABEL[integrationConnectionState("expired")]).toBe(
      "Reconnect",
    );
    expect(
      CONNECT_ACTION_LABEL[integrationConnectionState("not_connected")],
    ).toBe("Connect");
  });

  it("sorts integrations needing attention above healthy ones", () => {
    const byState = (a: string, b: string) =>
      INTEGRATION_STATE_ORDER[integrationConnectionState(a)] -
      INTEGRATION_STATE_ORDER[integrationConnectionState(b)];

    expect(
      ["not_connected", "connected", "expired", "created"].toSorted(byState),
    ).toEqual(["expired", "created", "connected", "not_connected"]);
  });
});
