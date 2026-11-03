import type { ComponentType } from "react";
import { OfferLetter } from "./concepts/OfferLetter";
import { OnePrice } from "./concepts/OnePrice";
import { ThePromise } from "./concepts/ThePromise";
import { WatchMeWork } from "./concepts/WatchMeWork";
import type { PaywallConceptProps } from "./labData";

export type ConceptId = "watch" | "offer" | "simple" | "promise";

export interface PaywallConcept {
  id: ConceptId;
  name: string;
  Component: ComponentType<PaywallConceptProps>;
  bet: string;
  whyItConverts: string;
  risk: string;
  buildCost: string;
}

export const PAYWALL_CONCEPTS: PaywallConcept[] = [
  {
    id: "watch",
    name: "Watch me work",
    Component: WatchMeWork,
    bet: "People don't pay for a promise of help; they pay after seeing it. GAIA runs one job in front of them (their drafted starting job, or a sample for their top need) before the price appears.",
    whyItConverts:
      "The 76% who never open checkout have only read claims so far. Four seconds of visible work is the first proof in the whole flow, and the price lands right after it.",
    risk: "Sample data is not their data, so it can read as a canned animation. Adds a beat before the price, and skeptics may wait it out and still leave.",
    buildCost:
      "Sample version: about a day. A run on their real inbox needs a read-only connect before payment plus a preview job on the backend: one to two weeks, and an OAuth step before the paywall.",
  },
  {
    id: "offer",
    name: "The offer letter",
    Component: OfferLetter,
    bet: "Lean all the way into hiring. The paywall is a one-page offer letter written from their answers, and paying is signing it.",
    whyItConverts:
      "Turns the price into a salary comparison without saying so, and makes the duties concrete in their own words. The signing moment is a ritual, not a form.",
    risk: "Can read as a gimmick to someone who wanted a straight price. 'Offer letter' hints at a commitment, which may add anxiety at the exact moment it should drop.",
    buildCost:
      "About a day: copy plus the needs-to-duties map, on the existing checkout. Duties for 'Something else' answers need an LLM line or a generic fallback.",
  },
  {
    id: "simple",
    name: "One price",
    Component: OnePrice,
    bet: "The paywall is losing people to friction, not doubt. Remove the monthly/yearly choice entirely and answer the three questions replays show people leaving to find.",
    whyItConverts:
      "Replays show minutes of toggling and FAQ reading, and yearly converts 0/14. One number and one button leave nothing to deliberate; the answers kill the 'is it free?' detour.",
    risk: "Adds no new reason to pay. If the 76% are unconvinced rather than confused, this changes nothing. Gives up yearly cash up front for now.",
    buildCost:
      "Half a day. Plus a decision on where yearly moves (post-payment receipt or settings), about a day more.",
  },
  {
    id: "promise",
    name: "The promise",
    Component: ThePromise,
    bet: "Trust is the blocker. Replace the pitch with a checkable week-one promise built from their needs, and a full refund if GAIA misses. Still a hard paywall: they pay first.",
    whyItConverts:
      "Moves the risk from them to us without a free trial. The promises are specific enough to believe, and 'text me refund' is the lowest-effort exit anyone offers.",
    risk: "6 of 15 payers asked to cancel within 6 days; this turns those into refunds. Promises we can't verify invite disputes, and it needs real refund handling.",
    buildCost:
      "UI about a day. For real: refund policy and terms, a Dodo refund path, support handling for 'refund' messages, and tracking which promises were kept. About a week.",
  },
];
