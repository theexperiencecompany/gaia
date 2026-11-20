/**
 * Gives a real adapter what boot() would, without booting: a GAIA client (real
 * or scripted) and a delivery-failure reporter. The followers read the events
 * stream through that client.
 */
import { vi } from "vitest";
import type { BaseBotAdapter } from "../../../../../libs/shared/ts/src/bots";

export function injectGaia(
  adapter: BaseBotAdapter,
  gaia: object,
  reportDeliveryFailure: (...args: never[]) => void = vi.fn(),
): void {
  const seams = adapter as unknown as {
    gaia: object;
    reportDeliveryFailure: (...args: never[]) => void;
  };
  seams.gaia = gaia;
  seams.reportDeliveryFailure = reportDeliveryFailure;
}
