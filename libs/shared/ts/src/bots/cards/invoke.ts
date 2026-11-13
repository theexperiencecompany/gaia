/**
 * How a card's buttons travel through each platform and come back.
 *
 * A tapped invoke button carries only the opaque action id the API attached to
 * the card data. Telegram `callback_data` and Discord `custom_id` hold it behind
 * {@link CARD_ACTION_DATA_PREFIX}; Slack puts it in the button `value` of an
 * element whose `action_id` is {@link slackCardActionId}.
 *
 * @module
 */
import type {
  Card,
  CardInvokeAction,
  CardLinkAction,
  CardReplyAction,
  CardReplyPrompt,
} from "./types";

/**
 * The opaque action ids the API attaches, on bot deliveries only, to an object a
 * card button can act on, keyed by verb. A bot sends the id back to
 * `POST /bot/card-action`; the operation it stands for stays server-side. A verb
 * is absent when its id could not be minted, so each one is optional.
 */
type BotActionIds<Verb extends string> = Partial<Record<Verb, string>>;

/**
 * An object a bot card button can act on. After a tap lands, the API replaces
 * the spent object's `bot_actions` with `bot_tapped`, the id of the tapped
 * action, so a bot can find the card that tap came from; it is never a button.
 */
export interface BotActionable<Verb extends string> {
  bot_actions?: BotActionIds<Verb>;
  bot_tapped?: string;
}

/** Marks a Telegram `callback_data` / Discord `custom_id` as a card action. */
export const CARD_ACTION_DATA_PREFIX = "gc:";

/** Marks a Telegram `callback_data` / Discord `custom_id` as a reply prompt. */
const CARD_REPLY_DATA_PREFIX = "gr:";

/** What each reply button asks; the answer is read like any chat message. */
export const CARD_REPLY_PROMPTS: Record<CardReplyPrompt, string> = {
  revise_approval: "What should I change? Reply here and I'll redo it.",
};

export function encodeCardReplyData(prompt: CardReplyPrompt): string {
  return `${CARD_REPLY_DATA_PREFIX}${prompt}`;
}

/** The prompt behind a tapped reply button's data, or `null` when it is not one. */
export function decodeCardReplyData(data: string): CardReplyPrompt | null {
  if (!data.startsWith(CARD_REPLY_DATA_PREFIX)) return null;
  const prompt = data.slice(CARD_REPLY_DATA_PREFIX.length);
  return Object.hasOwn(CARD_REPLY_PROMPTS, prompt)
    ? (prompt as CardReplyPrompt)
    : null;
}

/**
 * Every card button's Slack `action_id` is this plus its position in its
 * actions block: Slack wants `action_id` unique within a block, and one handler
 * matching {@link SLACK_CARD_ACTION_PATTERN} receives them all.
 */
const SLACK_CARD_ACTION_ID = "gaia_card";
const SLACK_CARD_ACTION_SEPARATOR = ":";

export const SLACK_CARD_ACTION_PATTERN = new RegExp(
  `^${SLACK_CARD_ACTION_ID}${SLACK_CARD_ACTION_SEPARATOR}\\d+$`,
);

export function slackCardActionId(position: number): string {
  return `${SLACK_CARD_ACTION_ID}${SLACK_CARD_ACTION_SEPARATOR}${position}`;
}

export function encodeCardActionData(actionId: string): string {
  return `${CARD_ACTION_DATA_PREFIX}${actionId}`;
}

/** The action id behind a tapped button's data, or `null` when it is not a card action. */
export function decodeCardActionData(data: string): string | null {
  if (!data.startsWith(CARD_ACTION_DATA_PREFIX)) return null;
  const actionId = data.slice(CARD_ACTION_DATA_PREFIX.length);
  return actionId || null;
}

/**
 * The action ids an object on a card holds: its live buttons, plus the one a
 * landed tap spent on it.
 */
export function heldActionIds(object: BotActionable<string>): string[] {
  const live = Object.values(object.bot_actions ?? {}).filter(
    (actionId): actionId is string => Boolean(actionId),
  );
  return object.bot_tapped ? [...live, object.bot_tapped] : live;
}

export function replyActions(card: Card): CardReplyAction[] {
  return card.actions.filter(
    (action): action is CardReplyAction => action.kind === "reply",
  );
}

export function linkActions(card: Card): CardLinkAction[] {
  return card.actions.filter(
    (action): action is CardLinkAction => action.kind === "link",
  );
}

/**
 * The card's invoke actions, one row per object they act on, in card order:
 * the layout every native renderer uses.
 */
export function invokeActionRows(card: Card): CardInvokeAction[][] {
  const rows = new Map<string, CardInvokeAction[]>();
  for (const action of card.actions) {
    if (action.kind !== "invoke") continue;
    const row = rows.get(action.objectKey);
    if (row) row.push(action);
    else rows.set(action.objectKey, [action]);
  }
  return [...rows.values()];
}
