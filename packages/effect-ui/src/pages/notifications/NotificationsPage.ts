import { Command, Component, Query, UiSchema } from "@effect/ui";
import { Html } from "@effect/ui/html";
import type { H } from "@effect/ui/html/Html";
import { Effect, Schema } from "effect";
import { AsyncResult } from "effect/reactivity";
import { Api, ApiError } from "../../services/Api";

/**
 * The Notifications list, ported 1:1 from the default Unread view of
 * apps/web/src/app/[locale]/(main)/notifications/page.tsx,
 * NotificationsList.tsx and EnhancedNotificationCard.tsx. Classes and DOM shape
 * are copied from the rendered React page.
 *
 * Not ported: the page header (tabs, mark-all-as-read), the connect banner,
 * the notification action buttons, the WebSocket stream and the email-preview
 * modal. The body is rendered as plain paragraphs because the React card runs
 * a full markdown pipeline.
 */

/** The canonical first page the web store fetches: the API's own ceiling. */
export const NOTIFICATION_PAGE_SIZE = 100;

const INAPP_CHANNEL = "inapp";

export const NotificationView = Schema.Struct({
  id: Schema.String,
  status: Schema.Literals([
    "pending",
    "delivered",
    "failed",
    "read",
    "archived",
  ]),
  created_at: Schema.String,
  content: Schema.Struct({
    title: Schema.String,
    body: Schema.String,
  }),
  channels: Schema.optional(
    Schema.Array(Schema.Struct({ channel_type: Schema.String })),
  ),
});

export type NotificationView = typeof NotificationView.Type;

export const PaginatedNotifications = Schema.Struct({
  notifications: Schema.Array(NotificationView),
});

export type PaginatedNotifications = typeof PaginatedNotifications.Type;

export const NotificationsMessage = UiSchema.TaggedEnum({
  RequestedMarkAsRead: { id: Schema.String },
  SucceededMarkNotificationRead: {},
  FailedMarkNotificationRead: { message: Schema.String },
});

type NotificationsH = H<typeof NotificationsMessage.Type>;

export class ListNotifications extends Query.Service<ListNotifications>()(
  "Notifications/ListNotifications",
  {
    success: Schema.Array(NotificationView),
    error: ApiError,
    staleTime: "30 seconds",
  },
) {
  static readonly layer = this.toLayer(
    Effect.gen(function* () {
      const api = yield* Api;
      return () =>
        api
          .request(
            `/notifications?limit=${NOTIFICATION_PAGE_SIZE}`,
            { method: "GET" },
            PaginatedNotifications,
          )
          .pipe(Effect.map((response) => response.notifications));
    }),
  );
}

export class MarkNotificationRead extends Command.Service<MarkNotificationRead>()(
  "Notifications/MarkNotificationRead",
  {
    args: { id: Schema.String },
    success: NotificationsMessage,
    invalidates: () => [ListNotifications],
  },
) {
  static readonly layer = this.toLayer(
    Effect.gen(function* () {
      const api = yield* Api;
      return ({ id }) =>
        api
          .request(
            `/notifications/${encodeURIComponent(id)}/read`,
            { method: "POST" },
            Schema.Struct({ success: Schema.Boolean }),
          )
          .pipe(
            Effect.match({
              onSuccess: () =>
                NotificationsMessage.SucceededMarkNotificationRead(),
              onFailure: (error) =>
                NotificationsMessage.FailedMarkNotificationRead({
                  message: error.message,
                }),
            }),
          );
    }),
  );
}

const NOTIFICATION_ICON_PATH =
  "M15.75 20C15.0345 21.3387 13.624 22.25 12 22.25C10.376 22.25 8.96548 21.3387 8.25 20H15.75ZM12 1.75C16.2802 1.75 19.75 5.21979 19.75 9.5V12.2559C19.75 12.8526 19.9872 13.4247 20.4092 13.8467L21.0127 14.4502C21.4849 14.9225 21.75 15.5635 21.75 16.2314C21.7498 17.6223 20.6223 18.7498 19.2314 18.75H4.76855C3.37767 18.7498 2.25017 17.6223 2.25 16.2314C2.25 15.5635 2.51512 14.9225 2.9873 14.4502L3.59082 13.8467L3.74023 13.6816C4.06829 13.2813 4.24999 12.778 4.25 12.2559V9.5C4.25 5.21979 7.71979 1.75 12 1.75Z";
const CHECK_BADGE_PATH =
  "M12 1.25C11.4388 1.25 10.9816 1.48611 10.5656 1.80358C10.1759 2.10089 9.74606 2.53075 9.24319 3.03367L9.20782 3.06904C8.69316 3.5837 8.24449 3.78626 7.55208 3.78626C7.4653 3.78626 7.35579 3.78318 7.23212 3.7797C6.91509 3.77078 6.50497 3.75924 6.14615 3.79027C5.62128 3.83566 4.96532 3.97929 4.46745 4.48134C3.9734 4.97955 3.83327 5.63282 3.78923 6.15439C3.75922 6.50995 3.77075 6.91701 3.77966 7.23178L3.77966 7.23181C3.78317 7.35581 3.78628 7.46549 3.78628 7.55206C3.78628 8.24448 3.58371 8.69315 3.06902 9.20784L3.03367 9.24319C2.53075 9.74606 2.10089 10.1759 1.80358 10.5655C1.48612 10.9816 1.25001 11.4388 1.25 12C1.25001 12.5611 1.48613 13.0183 1.80358 13.4344C2.10095 13.8242 2.53091 14.2541 3.03395 14.7571L3.06906 14.7922C3.40272 15.1258 3.56011 15.3422 3.64932 15.5464C3.73619 15.7453 3.78628 15.9971 3.78628 16.4479C3.78628 16.5347 3.7832 16.6442 3.77972 16.7679C3.7708 17.0849 3.75926 17.495 3.79029 17.8539C3.83569 18.3787 3.97933 19.0347 4.48139 19.5326C4.97961 20.0266 5.63287 20.1667 6.15443 20.2107C6.50997 20.2408 6.91703 20.2292 7.23179 20.2203C7.35581 20.2168 7.4655 20.2137 7.55206 20.2137C7.99328 20.2137 8.24126 20.2581 8.43645 20.3386C8.63147 20.4191 8.84006 20.5632 9.15424 20.8774C9.22129 20.9444 9.30963 21.0391 9.41153 21.1483L9.41176 21.1486L9.41179 21.1486L9.4118 21.1486C9.64176 21.3951 9.94071 21.7155 10.22 21.9596C10.6437 22.33 11.2516 22.75 12 22.75C12.7485 22.75 13.3563 22.33 13.7801 21.9596C14.0593 21.7155 14.3583 21.3951 14.5882 21.1486C14.6902 21.0392 14.7787 20.9445 14.8458 20.8773C15.1599 20.5632 15.3685 20.4191 15.5635 20.3386C15.7587 20.2581 16.0067 20.2137 16.4479 20.2137C16.5345 20.2137 16.6442 20.2168 16.7682 20.2203C17.083 20.2292 17.49 20.2408 17.8456 20.2107C18.3671 20.1667 19.0204 20.0266 19.5186 19.5326C20.0207 19.0347 20.1643 18.3787 20.2097 17.8539C20.2407 17.495 20.2292 17.0849 20.2203 16.7679L20.2203 16.7676C20.2168 16.644 20.2137 16.5346 20.2137 16.4479C20.2137 15.9971 20.2638 15.7453 20.3507 15.5464C20.4399 15.3422 20.5973 15.1258 20.9309 14.7922L20.9661 14.7571C21.4691 14.2541 21.8991 13.8242 22.1964 13.4344C22.5139 13.0183 22.75 12.5611 22.75 12C22.75 11.4388 22.5139 10.9816 22.1964 10.5655C21.8991 10.1759 21.4693 9.74607 20.9664 9.24322L20.931 9.20784C20.5973 8.87416 20.4399 8.65779 20.3507 8.45354C20.2638 8.25468 20.2137 8.00288 20.2137 7.55206C20.2137 7.46534 20.2168 7.35593 20.2203 7.23236L20.2203 7.2321C20.2292 6.91507 20.2407 6.50496 20.2097 6.14615C20.1643 5.62129 20.0207 4.96533 19.5187 4.46747C19.0205 3.97339 18.3672 3.83325 17.8456 3.78921C17.49 3.75919 17.083 3.77072 16.7682 3.77964C16.6442 3.78315 16.5345 3.78626 16.4479 3.78626C15.7553 3.78626 15.3067 3.58361 14.7922 3.06904L14.7568 3.03368C14.2539 2.53075 13.8241 2.10089 13.4344 1.80358C13.0184 1.48611 12.5612 1.25 12 1.25ZM15.462 10.3871C15.9519 10.132 16.1421 9.5281 15.887 9.03827C15.6319 8.54844 15.028 8.35817 14.5382 8.61329C13.1102 9.35702 11.9452 10.7808 11.1754 11.9034C10.9585 12.2198 10.7656 12.5232 10.5998 12.7973C10.4866 12.7015 10.3774 12.6154 10.2766 12.5395C10.0613 12.3774 9.8677 12.2496 9.7263 12.1614L9.47903 12.0152L9.47742 12.0143C8.9921 11.7507 8.38498 11.9304 8.12138 12.4158C7.85783 12.901 8.03775 13.5081 8.52281 13.7718C8.66656 13.8627 8.97796 14.0631 9.07359 14.1372C9.40717 14.3884 9.74708 14.7037 9.95328 15.0321C10.147 15.3405 10.4931 15.5192 10.8567 15.4986C11.2202 15.478 11.544 15.2611 11.7016 14.9329C11.7528 14.8299 11.8826 14.5752 11.9929 14.3805C12.188 14.0296 12.4716 13.5496 12.8248 13.0345C13.555 11.9696 14.49 10.8934 15.462 10.3871Z";

const NotificationGlyph = (h: NotificationsH) =>
  h.svg
    .attr("xmlns", "http://www.w3.org/2000/svg")
    .attr("width", "24")
    .attr("height", "24")
    .attr("viewBox", "0 0 24 24")
    .attr("fill", "currentColor")
    .attr("stroke", "none")
    .attr("stroke-width", "0")
    .attr("stroke-linecap", "round")
    .attr("stroke-linejoin", "round")
    .children(
      h.path.attr("d", NOTIFICATION_ICON_PATH).attr("fill", "currentColor"),
    );

const MarkReadGlyph = (h: NotificationsH) =>
  h.svg
    .attr("xmlns", "http://www.w3.org/2000/svg")
    .attr("width", "24")
    .attr("height", "24")
    .attr("viewBox", "0 0 24 24")
    .attr("fill", "currentColor")
    .attr("stroke", "none")
    .attr("stroke-width", "0")
    .attr("stroke-linecap", "round")
    .attr("stroke-linejoin", "round")
    .class("h-4 w-4 text-zinc-500")
    .children(h.path.attr("d", CHECK_BADGE_PATH).attr("fill", "currentColor"));

// HeroUI Button size="sm" variant="light" isIconOnly, computed from the theme.
const MARK_READ_BUTTON_CLASS =
  "z-0 group relative inline-flex items-center justify-center box-border appearance-none select-none whitespace-nowrap font-normal subpixel-antialiased overflow-hidden tap-highlight-transparent transform-gpu data-[pressed=true]:scale-[0.97] cursor-pointer outline-solid outline-transparent data-[focus-visible=true]:z-10 data-[focus-visible=true]:outline-2 data-[focus-visible=true]:outline-focus data-[focus-visible=true]:outline-offset-2 text-tiny gap-2 rounded-small px-0 !gap-0 transition-transform-colors-opacity motion-reduce:transition-none bg-transparent text-default-foreground data-[hover=true]:bg-default/40 min-w-8 w-8 h-8";

// HeroUI Spinner size="lg" color="primary", computed from the theme.
const Spinner = (h: NotificationsH) =>
  h.div
    .attr("aria-label", "Loading")
    .class("relative inline-flex flex-col gap-2 items-center justify-center")
    .children(
      h.div
        .class("relative flex w-10 h-10")
        .children(
          h.i.class(
            "absolute w-full h-full rounded-full border-3 border-b-primary animate-spinner-ease-spin border-solid border-t-transparent border-l-transparent border-r-transparent",
          ),
          h.i.class(
            "absolute w-full h-full rounded-full border-3 border-b-primary opacity-75 animate-spinner-linear-spin border-dotted border-t-transparent border-l-transparent border-r-transparent",
          ),
        ),
    );

const getTimeGroup = (
  createdAt: string,
  now: number,
): "Today" | "Yesterday" | "Earlier" => {
  const timestamp = createdAt.endsWith("Z") ? createdAt : `${createdAt}Z`;
  const diffInHours = (now - new Date(timestamp).getTime()) / (1000 * 60 * 60);

  if (diffInHours < 24) return "Today";
  if (diffInHours < 48) return "Yesterday";
  return "Earlier";
};

const groupByTime = (
  notifications: readonly NotificationView[],
): readonly {
  readonly name: string;
  readonly items: readonly NotificationView[];
}[] => {
  const now = Date.now();
  const groups = new Map<string, NotificationView[]>();

  for (const notification of notifications) {
    const name = getTimeGroup(notification.created_at, now);
    const bucket = groups.get(name);
    if (bucket) bucket.push(notification);
    else groups.set(name, [notification]);
  }

  return Array.from(groups, ([name, items]) => ({ name, items }));
};

const nth = (date: number): string => {
  if (date > 3 && date < 21) return "th";
  switch (date % 10) {
    case 1:
      return "st";
    case 2:
      return "nd";
    case 3:
      return "rd";
    default:
      return "th";
  }
};

const locale = () =>
  typeof navigator === "undefined" ? "en-US" : navigator.language;

const formatRecentRelative = (
  diffInMs: number,
  formattedTime: string,
): string => {
  const seconds = Math.floor(diffInMs / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);

  let relativeTime = "";

  if (days > 0) {
    const remainingHours = hours % 24;
    relativeTime = days === 1 ? "1 day" : `${days} days`;
    if (remainingHours > 0) {
      relativeTime +=
        remainingHours === 1 ? " 1 hour" : ` ${remainingHours} hours`;
    }
  } else if (hours > 0) {
    const remainingMinutes = minutes % 60;
    relativeTime = hours === 1 ? "1 hour" : `${hours} hours`;
    if (remainingMinutes > 0) {
      relativeTime +=
        remainingMinutes === 1 ? " 1 min" : ` ${remainingMinutes} mins`;
    }
  } else if (minutes > 0) {
    relativeTime = minutes === 1 ? "1 min" : `${minutes} mins`;
  } else {
    relativeTime = "just now";
  }

  return relativeTime === "just now"
    ? `${relativeTime} (${formattedTime})`
    : `${relativeTime} ago (${formattedTime})`;
};

const formatOlderDate = (date: Date, formattedTime: string): string => {
  const month = date.toLocaleString(locale(), { month: "short" });
  const year = date.toLocaleString(locale(), { year: "2-digit" });
  const day = date.getDate();

  return `${day}${nth(day)} ${month} '${year} (${formattedTime})`;
};

const formatNotificationDate = (isoDateString: string): string => {
  const date = new Date(isoDateString);
  const now = new Date();
  const diffInMs = now.getTime() - date.getTime();

  const formattedTime = date
    .toLocaleString(locale(), {
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    })
    .toUpperCase();

  if (diffInMs < 7 * 24 * 60 * 60 * 1000) {
    return formatRecentRelative(diffInMs, formattedTime);
  }

  return formatOlderDate(date, formattedTime);
};

const MarkdownBody = (h: NotificationsH, body: string, isUnread: boolean) =>
  h.div
    .class(
      `prose fadein-style max-w-none dark:prose-invert text-white text-[13px] ${
        isUnread ? "text-zinc-400" : "text-zinc-600"
      }`,
    )
    .children(
      body
        .split(/\n{2,}/)
        .filter((paragraph) => paragraph.trim() !== "")
        .map((paragraph) =>
          h.p
            .class("mb-4 last:mb-0")
            .children(
              paragraph
                .split("\n")
                .flatMap((line, index) =>
                  index === 0 ? [line] : [h.br, line],
                ),
            ),
        ),
    );

const NotificationCard = (
  h: NotificationsH,
  notification: NotificationView,
) => {
  const isUnread = notification.status === "delivered";
  const showMarkAsRead =
    notification.status !== "read" && notification.status !== "archived";

  return h.div
    .key(notification.id)
    .class(
      `group relative w-full rounded-2xl transition-all ${
        isUnread ? "bg-zinc-800/70" : "bg-zinc-800/30"
      }`,
    )
    .children(
      h.div.class("px-4 py-3.5").children(
        h.div.class("flex items-start justify-between gap-3").children(
          h.div
            .class("min-w-0 flex-1 space-y-1")
            .children(
              h.div
                .class("flex items-center gap-2")
                .children(
                  h.h3
                    .class(
                      `${
                        isUnread ? "text-white" : "text-zinc-500"
                      } text-[15px] leading-tight font-semibold`,
                    )
                    .children(notification.content.title),
                  isUnread
                    ? h.div.class(
                        "h-1.5 w-1.5 flex-shrink-0 rounded-full bg-primary",
                      )
                    : null,
                ),
              MarkdownBody(h, notification.content.body, isUnread),
            ),
          showMarkAsRead
            ? h.button
                .attr("type", "button")
                .attr("aria-label", "Mark as read")
                .class(MARK_READ_BUTTON_CLASS)
                .on(
                  "click",
                  NotificationsMessage.RequestedMarkAsRead({
                    id: notification.id,
                  }),
                )
                .children(MarkReadGlyph(h))
            : null,
        ),
        h.div
          .class("mt-3 flex items-end justify-between")
          .children(
            h.span
              .class("inline-block text-[11px] text-zinc-600")
              .children(formatNotificationDate(notification.created_at)),
          ),
      ),
    );
};

const EmptyState = (h: NotificationsH, message: string, description: string) =>
  h.div
    .class(
      "mx-auto mt-10 flex h-full w-full max-w-4xl items-center justify-center",
    )
    .children(
      h.div
        .class("flex flex-col items-center space-y-4 text-center")
        .children(
          h.div
            .class(
              "flex h-16 w-16 items-center justify-center rounded-full bg-zinc-900/50 ring-1 ring-zinc-800",
            )
            .children(
              h.span
                .class("text-3xl text-zinc-600")
                .children(NotificationGlyph(h)),
            ),
          h.div
            .class("space-y-1")
            .children(
              h.h3
                .class("text-base font-semibold text-white")
                .children(message),
              h.p.class("text-sm text-zinc-500").children(description),
            ),
        ),
    );

const NotificationsPageDef = Html.component({
  name: "NotificationsPage",
  props: Schema.Struct({
    embedded: Schema.optional(Schema.Boolean),
    tab: Schema.optional(Schema.Literals(["unread", "all"])),
  }),
  model: Schema.Struct({}),
  message: NotificationsMessage,
  queries: {
    notifications: { query: ListNotifications, args: () => ({}) },
  },
});

export const NotificationsPageNoDeps = NotificationsPageDef.make({
  init: () => ({}),

  update: {
    RequestedMarkAsRead: ($, { id }) =>
      $.run(MarkNotificationRead.make({ id })),
    SucceededMarkNotificationRead: ($) => $.model,
    FailedMarkNotificationRead: ($) => $.model,
  },

  view: (h) => {
    const embedded = h.props.embedded === true;
    const tab = h.props.tab ?? "unread";

    const body = AsyncResult.match(h.queries.notifications, {
            onInitial: () =>
              h.div
                .class(
                  "mx-auto flex h-full w-full max-w-4xl items-center justify-center",
                )
                .children(
                  h.div
                    .class("flex flex-col items-center space-y-3")
                    .children(
                      Spinner(h),
                      h.p
                        .class("text-sm text-zinc-500")
                        .children("Loading notifications..."),
                    ),
                ),
            onFailure: () =>
              EmptyState(
                h,
                "No unread notifications",
                "All caught up! You're up to date with everything.",
              ),
            onSuccess: ({ value }) => {
              const unread = value
                .filter(
                  (notification) =>
                    notification.status === "delivered" &&
                    notification.channels?.some(
                      (channel) => channel.channel_type === INAPP_CHANNEL,
                    ) === true,
                )
                .slice(0, NOTIFICATION_PAGE_SIZE);

              const visible = tab === "all" ? value : unread;

              if (visible.length === 0) {
                return EmptyState(
                  h,
                  tab === "all" ? "No notifications yet" : "No unread notifications",
                  tab === "all"
                    ? "Notifications will appear here when you receive them."
                    : "All caught up! You're up to date with everything.",
                );
              }

              const groups = groupByTime(visible);

              return h.div
                .class("mx-auto w-full max-w-4xl space-y-8 px-6 py-6")
                .children(
                  groups.map((group) =>
                    h.div
                      .key(group.name)
                      .class("space-y-3")
                      .children(
                        h.h3
                          .class(
                            "px-0.5 text-xs font-semibold tracking-wider text-zinc-500 uppercase",
                          )
                          .children(group.name),
                        h.div
                          .class("space-y-2.5")
                          .children(
                            group.items.map((notification) =>
                              NotificationCard(h, notification),
                            ),
                          ),
                      ),
                  ),
                );
            },
          });

    if (embedded) return body;

    return h.div
      .class("flex h-full w-full flex-col overflow-hidden bg-primary-bg")
      .children(
        // The connect banner is not ported; its wrapper keeps the page's
        // vertical rhythm (pt-6 before the scrolled list).
        h.div.class("shrink-0 px-6 pt-6"),
        h.div.class("min-h-0 flex-1 overflow-y-auto px-6 pb-6").children(body),
      );
  },
});

export const NotificationsPage = NotificationsPageNoDeps.pipe(
  Component.provide([ListNotifications.layer, MarkNotificationRead.layer]),
);
