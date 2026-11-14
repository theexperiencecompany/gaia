/**
 * A browser run on a chat platform, rendered from its work item's cards: each new
 * step as a photo with its caption, a pending hand-off with its take-over link, a
 * note shown on the session card, and the recap link once the run ends.
 *
 * Shown only in a private chat: the link drives the user's own browser and a step
 * photo can show a signed-in page, so a group sees only the replies.
 */

import type { ToolDataEntry } from "../../api/generated";
import type {
  BrowserHandoffSnapshot,
  BrowserStepSnapshot,
  BrowserTaskSnapshot,
} from "../../conversation/browser-cards.types";
import type { FollowSurface } from "./follower.types";

const BROWSER_CARD_TOOL = "browser_task_data";
const CARD_KINDS: ReadonlySet<string> = new Set([
  "session",
  "step",
  "handoff",
  "result",
]);
const BLANK_TAB_PREFIX = "about:";
const NEW_TAB_URL = "chrome://newtab/";

const BROWSER_CREDENTIALS_SAVED_NOTE =
  "Once you're signed in, I'll save this site's session, encrypted, so I can skip the login next time. You can remove saved sites anytime in your Browser settings.";
const BROWSER_HANDOFF_REPLY_PROMPT =
  "Reply here when you're done, or tell me to stop.";

const isSnapshot = (data: unknown): data is BrowserTaskSnapshot =>
  typeof data === "object" &&
  data !== null &&
  "kind" in data &&
  typeof data.kind === "string" &&
  CARD_KINDS.has(data.kind);

/** The browser cards among a work item's cards, in the order the run emitted them. */
export function browserCards(
  cards: readonly ToolDataEntry[],
): BrowserTaskSnapshot[] {
  return cards.flatMap((card) =>
    card.tool_name === BROWSER_CARD_TOOL && isSnapshot(card.data)
      ? [card.data]
      : [],
  );
}

const isBlankTab = (url: string | null | undefined): boolean =>
  !url || url.startsWith(BLANK_TAB_PREFIX) || url === NEW_TAB_URL;

const stepCaption = (shown: number, goal: string): string => {
  const label = goal.trim().replace(/\.$/, "");
  return label ? `Step ${shown} · ${label}` : `Step ${shown}`;
};

/** One run's progress on the platform: what it already showed, so a card arrives once. */
export class BrowserProgress {
  /** How many of the run's cards were rendered or were history when the follow opened. */
  private seen = 0;
  /** Steps shown, which number the captions: the run's own index counts blank tabs and repeats. */
  private stepsShown = 0;
  /** The page and frame of the last step shown; the same again shows nothing. */
  private lastFrame: string | null = null;

  constructor(
    private readonly surface: FollowSurface,
    /** Sends lines the way the follower sends a notice: rendered for the platform. */
    private readonly notify: (bubbles: string[]) => Promise<void>,
  ) {}

  /** Take every card the run has now as already delivered. */
  skip(cards: readonly BrowserTaskSnapshot[]): void {
    this.seen = cards.length;
  }

  /** Render the cards past the ones already shown. */
  async render(cards: readonly BrowserTaskSnapshot[]): Promise<void> {
    const fresh = cards.slice(this.seen);
    this.seen = cards.length;
    if (!this.surface.privateChat) return;
    for (const card of fresh) await this.renderCard(card);
  }

  private async renderCard(card: BrowserTaskSnapshot): Promise<void> {
    switch (card.kind) {
      case "session":
        if (card.detail) await this.notify([card.detail]);
        return;
      case "step":
        await this.step(card);
        return;
      case "handoff":
        await this.handoff(card);
        return;
      case "result":
        if (card.replay_url)
          await this.notify([
            `📽 Here's a recap of the run: ${card.replay_url}`,
          ]);
        return;
      default: {
        const unhandled: never = card;
        return unhandled;
      }
    }
  }

  private async step(step: BrowserStepSnapshot): Promise<void> {
    // The pre-navigation blank tab has no photo worth sending, but its goal still says where the run is headed.
    if (isBlankTab(step.url)) {
      if (step.goal.trim()) {
        this.stepsShown += 1;
        await this.notify([stepCaption(this.stepsShown, step.goal)]);
      }
      return;
    }
    const frame = step.frame_digest ? `${step.url} ${step.frame_digest}` : null;
    if (frame !== null && frame === this.lastFrame) return;
    this.lastFrame = frame;
    this.stepsShown += 1;
    const caption = stepCaption(this.stepsShown, step.goal);
    if (step.screenshot) await this.surface.sendPhoto(step.screenshot, caption);
    else await this.notify([caption]);
  }

  private async handoff(handoff: BrowserHandoffSnapshot): Promise<void> {
    // Only the ask needs a message: its resolution is acknowledged in the chat itself.
    if (handoff.status !== "pending") return;
    // The user may change the page in the live view: the next step is shown whatever it looks like.
    this.lastFrame = null;
    const ask = handoff.saves_login
      ? `${handoff.reason}\n${BROWSER_CREDENTIALS_SAVED_NOTE}`
      : handoff.reason;
    const link = handoff.live_view_url
      ? [`Open the live browser: ${handoff.live_view_url}`]
      : [];
    await this.notify([ask, ...link, BROWSER_HANDOFF_REPLY_PROMPT]);
  }
}
