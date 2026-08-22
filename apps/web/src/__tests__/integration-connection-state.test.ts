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
  connectionPromptState,
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

/**
 * The chat card branch. `IntegrationConnectionPrompt` / `IntegrationConnectionCard`
 * are React components and this vitest project runs on `node` with no DOM
 * renderer, so the rendering itself is not covered here — only the derivation
 * that decides whether the card says Connect or Reconnect.
 */
describe("connectionPromptState", () => {
  it("reads an expired payload as a reconnect, whatever the live list says", () => {
    // The dead-account path expires the connection in the same turn it streams
    // the card, so the list still reports the pre-expiry status.
    expect(connectionPromptState(true, "connected")).toBe("expired");
    expect(connectionPromptState(true, "not_connected")).toBe("expired");
    expect(CONNECT_ACTION_LABEL[connectionPromptState(true, "connected")]).toBe(
      "Reconnect",
    );
  });

  it("falls back to the live status when the payload is not expired", () => {
    expect(connectionPromptState(false, "not_connected")).toBe("disconnected");
    expect(connectionPromptState(false, "expired")).toBe("expired");
    expect(connectionPromptState(false, "connected")).toBe("connected");
  });

  it("treats a message streamed before the flag existed as a first-time connect", () => {
    expect(connectionPromptState(undefined, "not_connected")).toBe(
      "disconnected",
    );
    expect(
      CONNECT_ACTION_LABEL[connectionPromptState(undefined, "not_connected")],
    ).toBe("Connect");
  });
});
