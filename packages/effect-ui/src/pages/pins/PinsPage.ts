import { Component, Mount, Query, UiSchema } from "@effect/ui";
import { Html } from "@effect/ui/html";
import type { H } from "@effect/ui/html/Html";
import { Effect, Schema } from "effect";
import { AsyncResult } from "effect/reactivity";
import { Api, ApiError } from "../../services/Api";

/**
 * The Pinned Messages page, ported 1:1 from
 * apps/web/src/features/pins/components/PinsPage.tsx and PinCard.tsx.
 * Classes and DOM shape are copied from the rendered React page. The
 * React-only pieces are rebuilt with their own markup: the HeroUI `Input`
 * (a native input with the same wrapper classes and the same clear button)
 * and the `PinIcon` / `CloseFilledIcon` SVGs, copied path for path.
 */

/** The subset of the API's MessageModelOutput the cards render. */
export const PinnedMessage = Schema.Struct({
  conversation_id: Schema.String,
  message: Schema.Struct({
    message_id: Schema.optional(Schema.NullOr(Schema.String)),
    date: Schema.optional(Schema.NullOr(Schema.String)),
    response: Schema.String,
  }),
});

export type PinnedMessage = typeof PinnedMessage.Type;

/** `PinnedMessagesResponse`: every pinned message across the user's conversations. */
export const PinnedMessagesResponse = Schema.Struct({
  results: Schema.Array(PinnedMessage),
});

export class ListPinnedMessages extends Query.Service<ListPinnedMessages>()(
  "Pins/ListPinnedMessages",
  {
    success: Schema.Array(PinnedMessage),
    error: ApiError,
    staleTime: "5 seconds",
  },
) {
  static readonly layer = this.toLayer(
    Effect.gen(function* () {
      const api = yield* Api;
      return () =>
        api
          .request(
            "/messages/pinned",
            { method: "GET" },
            PinnedMessagesResponse,
          )
          .pipe(Effect.map((response) => response.results));
    }),
  );
}

export const PinsMessage = UiSchema.TaggedEnum({
  UpdatedSearchQuery: { query: Schema.String },
  PressedClearButton: {},
});

type PinsH = H<typeof PinsMessage.Type>;

const Pins = Schema.Struct({ search: Schema.String });

type PinsModel = typeof Pins.Type;

/** HeroUI's `autoFocus` on the search field: focus it once it is in the page. */
export const FocusSearchInput = Mount.make(
  "FocusSearchInput",
  {},
  (node: HTMLInputElement) =>
    Effect.sync(() => node.focus()).pipe(Effect.as(Component.noop)),
);

const INPUT_WRAPPER =
  "relative w-full inline-flex tap-highlight-transparent flex-row items-center shadow-xs px-5 gap-3 bg-default-100 border-medium border-default-200 data-[hover=true]:border-default-400 focus-within:border-default-400 focus-within:ring-2 focus-within:ring-focus focus-within:ring-offset-2 focus-within:ring-offset-background focus-within:z-10 h-12 min-h-12 rounded-large rounded-full transition-colors motion-reduce:transition-none !duration-150 pr-1";

const INPUT =
  "w-full font-normal bg-transparent !outline-solid outline-transparent placeholder:text-foreground-500 focus-visible:outline-solid outline-transparent data-[has-start-content=true]:ps-1.5 data-[has-end-content=true]:pe-1.5 data-[type=color]:rounded-none file:cursor-pointer file:bg-transparent file:border-0 autofill:bg-transparent bg-clip-text dark:autofill:[-webkit-text-fill-color:hsl(var(--heroui-foreground))] [&::-ms-reveal]:hidden text-medium peer pe-6 input-search-cancel-button-none";

const CLEAR_BUTTON =
  "p-2 -m-2 z-10 absolute end-3 start-auto pointer-events-none appearance-none outline-solid outline-transparent select-none opacity-0 cursor-pointer active:!opacity-70 rounded-full data-[focus-visible=true]:z-10 data-[focus-visible=true]:outline-2 data-[focus-visible=true]:outline-focus data-[focus-visible=true]:outline-offset-2 text-large hover:!opacity-100 peer-data-[filled=true]:pointer-events-auto peer-data-[filled=true]:opacity-70 peer-data-[filled=true]:block peer-data-[filled=true]:scale-100 scale-90 ease-out duration-150 transition-[opacity,transform] motion-reduce:transition-none motion-reduce:scale-100";

// Copied from apps/web/src/utils/date/dateUtils.ts, which the React card calls.
const nth = (day: number): string => {
  if (day > 3 && day < 21) return "th";
  switch (day % 10) {
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

const uiLocale = (): string =>
  typeof navigator !== "undefined" && navigator.language !== ""
    ? navigator.language
    : "en-US";

/** Exact relative time for recent dates (within 7 days), e.g. "2 hours 5 mins ago". */
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

/** Full date format for older dates, e.g. "10th Jun '25 (3:04 PM)". */
const formatOlderDate = (date: Date, formattedTime: string): string => {
  const optionsMonth: Intl.DateTimeFormatOptions = { month: "short" };
  const optionsYear: Intl.DateTimeFormatOptions = { year: "2-digit" };

  const month = date.toLocaleString(uiLocale(), optionsMonth);
  const year = date.toLocaleString(uiLocale(), optionsYear);
  const day = date.getDate();

  return `${day}${nth(day)} ${month} '${year} (${formattedTime})`;
};

const parseDate = (isoDateString: string): string => {
  const date = new Date(isoDateString);
  const now = new Date();
  const diffInMs = now.getTime() - date.getTime();

  const optionsTime: Intl.DateTimeFormatOptions = {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  };
  const formattedTime = date
    .toLocaleString(uiLocale(), optionsTime)
    .toUpperCase();

  if (diffInMs < 7 * 24 * 60 * 60 * 1000) {
    return formatRecentRelative(diffInMs, formattedTime);
  }

  return formatOlderDate(date, formattedTime);
};

/** `PinIcon` from @theexperiencecompany/gaia-icons/solid-rounded. */
const pinIcon = (h: PinsH) =>
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
    .class("h-8 w-8 text-zinc-500")
    .children(
      h.path
        .attr("fill", "currentColor")
        .attr("fill-rule", "evenodd")
        .attr(
          "d",
          "M8.95711 15.0429C9.34763 15.4334 9.34763 16.0666 8.95711 16.4571L3.95711 21.4571C3.56658 21.8476 2.93342 21.8476 2.54289 21.4571C2.15237 21.0666 2.15237 20.4334 2.54289 20.0429L7.54289 15.0429C7.93342 14.6524 8.56658 14.6524 8.95711 15.0429Z",
        ),
      h.path
        .attr("fill", "currentColor")
        .attr(
          "d",
          "M17.7093 2.55346C19.4569 3.18528 20.8147 4.54305 21.4465 6.29064C21.5536 6.58633 21.6798 6.93507 21.7258 7.24165C21.7801 7.60384 21.744 7.94519 21.608 8.32365C21.3168 9.13408 20.6643 9.49626 19.9452 9.89542L18.5273 10.6861C18.0145 10.9721 17.676 11.1618 17.4348 11.3286C17.2 11.4909 17.1333 11.582 17.1056 11.6358C17.0909 11.6641 17.0453 11.8022 17.0573 12.2506C17.0686 12.6742 17.1236 13.2487 17.2024 14.0663C17.3296 15.3845 17.1109 16.6904 16.3502 17.9068C16.2218 18.1123 16.0604 18.3708 15.88 18.563C15.6669 18.7901 15.4215 18.9506 15.1053 19.0787C14.7835 19.2091 14.4907 19.2619 14.1748 19.2478C13.906 19.2358 13.5974 19.1656 13.3398 19.107C11.3641 18.6584 9.47833 17.5121 7.98305 16.0169C6.48778 14.5216 5.34151 12.6359 4.89294 10.6602C4.83436 10.4027 4.76418 10.0941 4.75221 9.82535C4.73813 9.50941 4.79103 9.21658 4.92151 8.89474C5.04969 8.5786 5.21026 8.3331 5.43747 8.12006C5.62978 7.93974 5.88832 7.7784 6.09379 7.65019C7.29324 6.90084 8.58854 6.66967 9.89679 6.78538C10.7321 6.85926 11.321 6.91095 11.754 6.91998C11.968 6.92445 12.2391 6.94301 12.3803 6.86947C12.4326 6.84219 12.5235 6.7753 12.6865 6.53889C12.8534 6.29676 13.0438 5.95698 13.3302 5.44342L14.1046 4.05478C14.5037 3.33567 14.8659 2.68318 15.6763 2.39201C16.0548 2.25603 16.3961 2.2199 16.7583 2.27422C17.0649 2.32019 17.4136 2.44643 17.7093 2.55346Z",
        ),
    );

/** `CloseFilledIcon` from @heroui/shared-icons, the Input's clear button. */
const closeFilledIcon = (h: PinsH) =>
  h.svg
    .attr("aria-hidden", "true")
    .attrs({ focusable: "false" } as Record<string, string>)
    .attr("height", "1em")
    .attr("role", "presentation")
    .attr("viewBox", "0 0 24 24")
    .attr("width", "1em")
    .children(
      h.path
        .attr("fill", "currentColor")
        .attr(
          "d",
          "M12 2a10 10 0 1010 10A10.016 10.016 0 0012 2zm3.36 12.3a.754.754 0 010 1.06.748.748 0 01-1.06 0l-2.3-2.3-2.3 2.3a.748.748 0 01-1.06 0 .754.754 0 010-1.06l2.3-2.3-2.3-2.3A.75.75 0 019.7 8.64l2.3 2.3 2.3-2.3a.75.75 0 011.06 1.06l-2.3 2.3z",
        ),
    );

const spinner = (h: PinsH) =>
  h.div
    .class("animate-spin")
    .children(
      h.img
        .attr("alt", "GAIA Logo")
        .attr("src", "/images/logos/logo.webp")
        .attr("width", "30")
        .attr("height", "30"),
    );

const PinCard = (h: PinsH, pin: PinnedMessage) => {
  const response = pin.message.response;
  const messageId = pin.message.message_id;

  return h.a
    .key(pin.conversation_id)
    .class(
      "relative flex h-full max-h-[195px] min-h-[150px] flex-col gap-2 overflow-hidden rounded-xl bg-zinc-800 p-3 transition-colors hover:bg-zinc-700",
    )
    .attr(
      "href",
      messageId === undefined || messageId === null
        ? `/c/${pin.conversation_id}`
        : `/c/${pin.conversation_id}?messageId=${encodeURIComponent(messageId)}`,
    )
    .children(
      h.div
        .class("max-h-[135px] overflow-hidden text-sm")
        .children(
          response.length > 350 ? `${response.slice(0, 350)}...` : response,
        ),
      h.div
        .class("mt-auto text-xs text-foreground-500")
        .children(pin.message.date ? parseDate(pin.message.date) : ""),
    );
};

const searchInput = (h: PinsH, model: PinsModel) => {
  const filled = model.search.length > 0;

  return h.div
    .attr("data-slot", "base")
    .class("group flex flex-col data-[hidden=true]:hidden w-full")
    .attr("data-filled", "true")
    .attr("data-filled-within", "true")
    .attr("data-focus-within", "false")
    .attr("data-focus-visible", "false")
    .attr("data-readonly", "false")
    .attr("data-focus", "false")
    .attr("data-hover", "false")
    .attr("data-required", "false")
    .attr("data-invalid", "false")
    .attr("data-disabled", "false")
    .attr("data-has-elements", "false")
    .attr("data-has-helper", "false")
    .attr("data-has-label", "false")
    .attr("data-has-value", filled ? "true" : "false")
    .attr("data-hidden", "false")
    .children(
      h.div
        .attr("data-slot", "input-wrapper")
        .attr("data-hover", "false")
        .attr("data-focus-visible", "false")
        .attr("data-focus", "false")
        .class(INPUT_WRAPPER)
        .style({ cursor: "text" })
        .children(
          h.div
            .attr("data-slot", "inner-wrapper")
            .class("inline-flex w-full items-center h-full box-border")
            .children(
              h.input
                .attr("data-slot", "input")
                .attr("data-filled", filled ? "true" : "false")
                .attr("data-filled-within", filled ? "true" : "false")
                .attr("data-has-start-content", "false")
                .attr("data-has-end-content", "false")
                .attr("type", "text")
                .attr("aria-label", "Enter a message to filter pins")
                .attr("placeholder", "Enter a message to filter pins")
                .class(INPUT)
                .value(model.search)
                .on("input", ({ value }) =>
                  PinsMessage.UpdatedSearchQuery({ query: value }),
                )
                .onMount(FocusSearchInput()),
              h.button
                .attr("type", "button")
                .attr("tabindex", "-1")
                .attr("aria-label", "clear input")
                .attr("data-slot", "clear-button")
                .attr("data-focus-visible", "false")
                .class(CLEAR_BUTTON)
                .on("click", PinsMessage.PressedClearButton())
                .children(closeFilledIcon(h)),
            ),
        ),
    );
};

const emptyState = (h: PinsH, model: PinsModel) => {
  const searching = model.search.trim().length > 0;

  return h.div
    .class("flex h-[90vh] flex-col items-center justify-center text-center")
    .children(
      h.div
        .class(
          "mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-zinc-800",
        )
        .children(pinIcon(h)),
      h.div.children(
        h.h3
          .class("text-lg font-medium text-white")
          .children(
            searching ? "No pins match your search" : "No pinned messages yet",
          ),
        h.p
          .class("mt-1 text-sm text-zinc-400")
          .children(
            searching
              ? "Try adjusting your search terms or clear the filter"
              : "PinIcon important messages during conversations to find them easily later",
          ),
      ),
    );
};

const results = (
  h: PinsH,
  model: PinsModel,
  pins: readonly PinnedMessage[],
) => {
  const query = model.search;
  const filtered =
    query.trim() === ""
      ? pins
      : pins.filter((pin) =>
          pin.message.response.toLowerCase().includes(query.toLowerCase()),
        );

  return h.div
    .class("flex flex-wrap justify-center gap-4 pb-8")
    .children(
      h.div
        .class("flex flex-wrap justify-center gap-4 pb-8 sm:px-[10vw]")
        .children(
          filtered.length > 0
            ? h.div
                .class(
                  "grid grid-cols-1 gap-4 pt-10 pb-24 sm:grid-cols-3 sm:pb-20",
                )
                .children(filtered.map((pin) => PinCard(h, pin)))
            : emptyState(h, model),
        ),
    );
};

const PinsPageDef = Html.component({
  name: "PinsPage",
  model: Pins,
  message: PinsMessage,
  queries: {
    pins: { query: ListPinnedMessages, args: () => ({}) },
  },
});

export const PinsPageNoDeps = PinsPageDef.make({
  init: () => ({ search: "" }),

  update: {
    UpdatedSearchQuery: ($, { query }) => $.evolve({ search: query }),
    PressedClearButton: ($) => $.evolve({ search: "" }),
  },

  view: (h, model) =>
    h.div.class("flex h-full flex-col justify-between").children(
      h.div.class("overflow-y-auto").children(
        AsyncResult.match(h.queries.pins, {
          onInitial: () =>
            h.div
              .class("flex h-[90vh] items-center justify-center")
              .children(spinner(h)),
          onFailure: () => results(h, model, []),
          onSuccess: ({ value }) => results(h, model, value),
        }),
      ),
      h.div
        .class(
          "absolute bottom-4 left-0 z-10 flex w-full flex-col items-center justify-center px-3 sm:bottom-5",
        )
        .children(
          h.div
            .class(
              "relative flex w-full max-w-(--breakpoint-sm) items-center gap-3",
            )
            .children(searchInput(h, model)),
        ),
      h.div.class(
        "bg-custom-gradient2 absolute bottom-0 left-0 z-1 h-[100px] w-full",
      ),
    ),
});

export const PinsPage = PinsPageNoDeps.pipe(
  Component.provide([ListPinnedMessages.layer]),
);
