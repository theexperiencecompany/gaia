import type { GaiaClient } from "@gaia/shared";
import type { App } from "@slack/bolt";
import { registerMentionEvent } from "./mention";

export function registerEvents(app: App, gaia: GaiaClient) {
  registerMentionEvent(app, gaia);
}
