import type { App } from "@slack/bolt";
import type { GaiaClient } from "@gaia/shared";
import { registerMentionEvent } from "./mention";

export function registerEvents(app: App, gaia: GaiaClient) {
  registerMentionEvent(app, gaia);
}
