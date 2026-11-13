/**
 * The platform-neutral card a bot sends: what `/help`, `/settings` and every
 * web tool card become on a messaging platform.
 *
 * Builders produce it from data; each adapter renders it in its platform's
 * native format (Telegram inline keyboard, Slack Block Kit, Discord embed), and
 * {@link renderCardText} is both the text-only rendering and the record of
 * what the user was shown.
 *
 * @module
 */

/** Semantic colour of a card; each native renderer maps it to its palette. */
export type CardAccent = "brand" | "warning";

/** The colour a {@link CardStatus} badge is drawn in. */
export type CardStatusTone = "info" | "warning" | "success" | "danger";

/**
 * Where the card's object stands ("Needs approval", "Sent"), drawn as a badge
 * by renderers that have one (the Telegram widget). The title and the actions
 * already say it everywhere else, so other renderers leave it out.
 */
export interface CardStatus {
  label: string;
  tone: CardStatusTone;
}

/** A run of CommonMark prose. */
export interface CardTextBlock {
  kind: "text";
  markdown: string;
}

/** One labelled value, e.g. "Connected apps" → the list of apps. */
export interface CardField {
  label: string;
  /** CommonMark. */
  value: string;
  /** Lay out beside neighbouring inline fields where the platform can. */
  inline?: boolean;
}

/** Labelled values, rendered as a group. */
export interface CardFieldsBlock {
  kind: "fields";
  fields: CardField[];
}

/**
 * Quoted content: a long value worth showing but not worth the card's height
 * (an email body, a note the user wrote). Collapsible where the platform can.
 */
export interface CardQuoteBlock {
  kind: "quote";
  /** CommonMark. */
  markdown: string;
  /** Shown folded to a few lines, expandable, where the platform supports it. */
  collapsible?: boolean;
  /** Who or what the quote is from, e.g. "Your note". */
  cite?: string;
}

/** One row of a {@link CardListBlock}: a result, an email, an event, a contact. */
export interface CardListItem {
  title: string;
  /** Opens the item (the result, the post); the title becomes the link. */
  url?: string;
  /** A muted second line: source, sender, time. */
  meta?: string;
  /** A short snippet under the meta line, plain text. */
  body?: string;
}

/** Things the tool found or listed, each with its own line of context. */
export interface CardListBlock {
  kind: "list";
  items: CardListItem[];
  /** How many more items the source had than the card lists. */
  hiddenCount: number;
}

/** Code or a command, shown monospaced and copyable. */
export interface CardCodeBlock {
  kind: "code";
  code: string;
  /** Language hint for highlighting, e.g. "python", "bash". */
  language?: string;
}

/** An image hosted at an https URL (a screenshot, a chart). */
export interface CardImageBlock {
  kind: "image";
  url: string;
  alt: string;
}

export type CardBlock =
  | CardTextBlock
  | CardFieldsBlock
  | CardQuoteBlock
  | CardListBlock
  | CardCodeBlock
  | CardImageBlock;

/** A button that opens a URL in the user's browser. */
export interface CardLinkAction {
  kind: "link";
  label: string;
  url: string;
}

/** How a native renderer emphasises an invoke button. */
export type CardInvokeStyle = "primary" | "danger";

/**
 * A button that asks the API to perform an operation on the user's behalf
 * (approve, send a draft). `actionId` is the opaque id the API
 * attached to the card data; the operation itself lives server-side.
 *
 * A text-only platform cannot show it, so a builder that adds one also says in
 * the card's text what to reply instead.
 */
export interface CardInvokeAction {
  kind: "invoke";
  label: string;
  actionId: string;
  /**
   * The object the action works on (an approval, one draft). Actions
   * sharing it are laid out as one button row.
   */
  objectKey: string;
  style?: CardInvokeStyle;
}

/** The questions a {@link CardReplyAction} can ask; the bot owns their wording. */
export type CardReplyPrompt = "revise_approval";

/**
 * A button that asks the user to answer in chat (Telegram force-reply, a prompt
 * message elsewhere). Nothing runs on the tap: the answer is an ordinary chat
 * message, which the agent and the approval resolver already understand.
 */
export interface CardReplyAction {
  kind: "reply";
  label: string;
  prompt: CardReplyPrompt;
}

export type CardAction = CardLinkAction | CardInvokeAction | CardReplyAction;

export interface Card {
  title?: string;
  /** Shown above the title. */
  author?: { name: string; iconUrl?: string };
  thumbnailUrl?: string;
  accent?: CardAccent;
  status?: CardStatus;
  blocks: CardBlock[];
  actions: CardAction[];
  footer?: string;
  /**
   * What to do where the card's buttons cannot be tapped (WhatsApp, iMessage):
   * only {@link renderCardText} shows it, so a card with buttons stays clean.
   */
  textHint?: string;
  /** Stamp the card with the time it was sent, where the platform supports it. */
  timestamp?: boolean;
  /**
   * Every card action id the objects on this card hold. A tap's updated payload
   * can build several cards (one per email draft); this is how the tapped one
   * is found among them.
   */
  actionIds?: string[];
}

/** Sends one card to wherever the caller is replying. */
export type CardSender = (card: Card) => Promise<void>;
