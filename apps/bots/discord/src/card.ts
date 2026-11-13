/**
 * Renders a shared {@link Card} as a Discord embed with buttons: one row per
 * object the card can act on, then its links.
 *
 * @module
 */
import {
  type Card,
  type CardAccent,
  type CardInvokeAction,
  type CardInvokeStyle,
  codeMarkdown,
  encodeCardActionData,
  encodeCardReplyData,
  invokeActionRows,
  linkActions,
  listMarkdown,
  quoteMarkdown,
  replyActions,
} from "@gaia/shared/bots";
import {
  ActionRowBuilder,
  type BaseMessageOptions,
  ButtonBuilder,
  ButtonStyle,
  EmbedBuilder,
} from "discord.js";

const ACCENT_COLOR: Record<CardAccent, number> = {
  brand: 0x7c3aed,
  warning: 0xf59e0b,
};

/** Discord allows at most five buttons in one action row. */
const BUTTONS_PER_ROW = 5;
/** Discord allows at most five action rows on one message. */
const MAX_ACTION_ROWS = 5;
/** Discord rejects a button label longer than this. */
const BUTTON_LABEL_MAX = 80;

/** Approve / Send / Done read as go-ahead green, as on Telegram. */
const INVOKE_BUTTON_STYLE: Record<CardInvokeStyle, ButtonStyle> = {
  primary: ButtonStyle.Success,
  danger: ButtonStyle.Danger,
};

export type DiscordCard = Required<
  Pick<BaseMessageOptions, "embeds" | "components">
>;

function buildEmbed(card: Card): EmbedBuilder {
  const embed = new EmbedBuilder();
  if (card.title) embed.setTitle(card.title);
  const description = card.blocks
    .flatMap((block) => {
      if (block.kind === "text") return [block.markdown];
      if (block.kind === "quote") return [quoteMarkdown(block)];
      if (block.kind === "list") return [listMarkdown(block)];
      if (block.kind === "code") return [codeMarkdown(block)];
      return [];
    })
    .join("\n\n");
  if (description) embed.setDescription(description);
  for (const block of card.blocks) {
    if (block.kind !== "fields") continue;
    embed.addFields(
      block.fields.map((field) => ({
        name: field.label,
        value: field.value,
        inline: field.inline ?? false,
      })),
    );
  }
  // An embed carries one image: the card's first.
  const image = card.blocks.find((block) => block.kind === "image");
  if (image) embed.setImage(image.url);
  if (card.accent) embed.setColor(ACCENT_COLOR[card.accent]);
  if (card.footer) embed.setFooter({ text: card.footer });
  if (card.timestamp) embed.setTimestamp();
  if (card.thumbnailUrl) embed.setThumbnail(card.thumbnailUrl);
  if (card.author) {
    embed.setAuthor({ name: card.author.name, iconURL: card.author.iconUrl });
  }
  return embed;
}

function buildInvokeRow(
  row: CardInvokeAction[],
): ActionRowBuilder<ButtonBuilder> {
  return new ActionRowBuilder<ButtonBuilder>().addComponents(
    row.slice(0, BUTTONS_PER_ROW).map((action) =>
      new ButtonBuilder()
        .setStyle(
          action.style
            ? INVOKE_BUTTON_STYLE[action.style]
            : ButtonStyle.Secondary,
        )
        .setLabel(action.label.slice(0, BUTTON_LABEL_MAX))
        .setCustomId(encodeCardActionData(action.actionId)),
    ),
  );
}

function buildReplyRow(card: Card): ActionRowBuilder<ButtonBuilder>[] {
  const replies = replyActions(card);
  if (replies.length === 0) return [];
  return [
    new ActionRowBuilder<ButtonBuilder>().addComponents(
      replies
        .slice(0, BUTTONS_PER_ROW)
        .map((action) =>
          new ButtonBuilder()
            .setStyle(ButtonStyle.Secondary)
            .setLabel(action.label.slice(0, BUTTON_LABEL_MAX))
            .setCustomId(encodeCardReplyData(action.prompt)),
        ),
    ),
  ];
}

function buildLinkRows(card: Card): ActionRowBuilder<ButtonBuilder>[] {
  const links = linkActions(card);
  const rows: ActionRowBuilder<ButtonBuilder>[] = [];
  for (let i = 0; i < links.length; i += BUTTONS_PER_ROW) {
    rows.push(
      new ActionRowBuilder<ButtonBuilder>().addComponents(
        links
          .slice(i, i + BUTTONS_PER_ROW)
          .map((link) =>
            new ButtonBuilder()
              .setStyle(ButtonStyle.Link)
              .setLabel(link.label.slice(0, BUTTON_LABEL_MAX))
              .setURL(link.url),
          ),
      ),
    );
  }
  return rows;
}

export function renderDiscordCard(card: Card): DiscordCard {
  const rows = [
    ...invokeActionRows(card).map(buildInvokeRow),
    ...buildReplyRow(card),
    ...buildLinkRows(card),
  ];
  return {
    embeds: [buildEmbed(card)],
    // Builders keep within this; a card past it loses its last rows rather
    // than Discord refusing the whole message.
    components: rows.slice(0, MAX_ACTION_ROWS),
  };
}
