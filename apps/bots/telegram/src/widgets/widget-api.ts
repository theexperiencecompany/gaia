/**
 * The Bot API 10.4 widget methods and update this bot uses, typed from the
 * Bot API reference (sendWidget, answerWidgetQuery, editMessageWidgetData,
 * WidgetQuery).
 *
 * grammY has no 10.4 typings yet (1.46.0 targets Bot API 10.3), so these calls
 * go through `api.raw`, whose Proxy forwards any method name to the Bot API.
 * This module is the one place that reaches past grammY's types; delete it for
 * grammY's own methods once it ships 10.4.
 *
 * @module
 */
import type { Api, Context, RawApi } from "grammy";
import type { Message } from "grammy/types";

/** The update field a widget tap arrives in (in Telegram's default `allowed_updates`). */
const WIDGET_QUERY_UPDATE = "widget_query";

export interface SendWidgetParams {
  chat_id: number | string;
  /** 1-32768 bytes; at most 4096 after zlib level 9. */
  html: string;
  /** 0-1024 bytes, specific to this message. */
  chat_data?: string;
  caption?: string;
  parse_mode?: "HTML" | "MarkdownV2";
  allow_queries?: boolean;
}

export interface AnswerWidgetQueryParams {
  widget_query_id: string;
  /** 0-1024 bytes, delivered only to the widget that asked. */
  data?: string;
}

export interface EditMessageWidgetDataParams {
  chat_id: number | string;
  message_id: number;
  /** 0-1024 bytes; an empty string clears it, omitted leaves it as it is. */
  chat_data?: string;
}

/** A widget tap (WidgetQuery), as this bot reads it. */
export interface WidgetQuery {
  id: string;
  from: { id: number };
  /** Absent for a widget in an inline message, which this bot never sends. */
  chat?: { id: number; type: string };
  message_id?: number;
  /** The widget's request data, 1-64 bytes. */
  data: string;
}

interface WidgetRawApi {
  sendWidget(params: SendWidgetParams): Promise<Message>;
  answerWidgetQuery(params: AnswerWidgetQueryParams): Promise<true>;
  editMessageWidgetData(
    params: EditMessageWidgetDataParams,
  ): Promise<Message | true>;
}

/** The widget methods on a grammY API object. */
export function widgetApi(api: Api<RawApi>): WidgetRawApi {
  // `api.raw` forwards any method name; grammY just has no 10.4 typings for these.
  return api.raw as unknown as WidgetRawApi;
}

/** The widget tap an update carries, or `null` when it carries none. */
export function widgetQueryOf(ctx: Context): WidgetQuery | null {
  const update: object = ctx.update;
  if (!(WIDGET_QUERY_UPDATE in update)) return null;
  const query = (update as { [WIDGET_QUERY_UPDATE]: unknown })[
    WIDGET_QUERY_UPDATE
  ];
  return isWidgetQuery(query) ? query : null;
}

function isWidgetQuery(value: unknown): value is WidgetQuery {
  if (typeof value !== "object" || value === null) return false;
  const query = value as Record<string, unknown>;
  const from = query.from as Record<string, unknown> | undefined;
  return (
    typeof query.id === "string" &&
    typeof query.data === "string" &&
    typeof from?.id === "number"
  );
}
