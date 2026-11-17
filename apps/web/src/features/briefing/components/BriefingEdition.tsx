"use client";

import { ArrowUpRight01Icon } from "@icons";
import type {
  BriefingItem,
  BriefingPayload,
  BriefingSection,
  BriefPoolItem,
} from "@shared/api/generated";
import Image from "next/image";
import Link from "next/link";
import type { ReactNode } from "react";

import MarkdownRenderer from "@/features/chat/components/interface/MarkdownRenderer";
import { cn } from "@/lib/utils";
import { formatClockTime } from "@/utils/date/clock";

import {
  BRIEF_PAGE_COLUMN_CLASS,
  EDITION_RENDER_WIDTH_PX,
  EDITION_TYPICAL_HEIGHT_PX,
} from "../letterTokens";
import {
  BRIEF_ITEM_STATES,
  hiddenEvents,
  leftOutItems,
} from "../utils/editionLeftOut";

/** An item as this view reads it: its words, its state and where it opens. */
type EditionItem = Pick<BriefingItem, "text" | "kind"> &
  Partial<Pick<BriefingItem, "todo_id" | "link">>;

/**
 * The brief's fields this view reads, off the stored payload. GAIA's OpenUI
 * Briefing component carries only the headline and sections, so the rest is
 * optional: the calendar, GAIA's message, what the composition left out
 * (uncomposed), the blocks the edition drew and those it could not (undrawn).
 */
export type BriefingEditionPayload = Pick<BriefingPayload, "headline"> & {
  sections: (Pick<BriefingSection, "numeral" | "title"> & {
    items: EditionItem[];
  })[];
} & Partial<
    Pick<
      BriefingPayload,
      "calendar" | "message" | "uncomposed" | "blocks" | "undrawn"
    >
  >;

type UndrawnBlock = BriefingPayload["undrawn"][number];

export interface BriefingEditionProps {
  payload: BriefingEditionPayload;
  /** The day's rendered edition, when the brief was rendered. */
  imageUrl?: string | null;
}

/**
 * The owner's copy carries todo_id and opens the in-app todo; the public copy
 * a heygaia.link serves has no todo_id, only the link the brief shared.
 */
function itemHref(item: EditionItem): string | null {
  if (item.todo_id) return `/todos?todoId=${item.todo_id}`;
  return item.link ?? null;
}

function poolItemHref(item: BriefPoolItem): string | null {
  if (item.todo_id) return `/todos?todoId=${item.todo_id}`;
  return item.url;
}

/** A block the edition left to this page, said in one line: a lead or group is listed with the sections. */
function undrawnLine(block: UndrawnBlock): string | null {
  switch (block.kind) {
    case "chart":
      return `${block.title}: ${block.takeaway}`;
    case "quote":
      return `“${block.quote.text}” ${block.quote.author}, ${block.quote.app}`;
    case "progress":
      return `${block.goal.statement}: ${block.goal.done} of ${block.goal.done + block.goal.open} done`;
    case "note":
      return block.text;
    default:
      return null;
  }
}

function undrawnLines(payload: BriefingEditionPayload): string[] {
  return (payload.undrawn ?? [])
    .map(undrawnLine)
    .filter((line): line is string => line !== null);
}

function ItemRow({ text, href }: { text: string; href: string | null }) {
  if (!href) {
    return <p className="text-sm font-medium text-zinc-200">{text}</p>;
  }
  return (
    <Link
      href={href}
      className="block text-sm font-medium text-zinc-200 hover:text-zinc-50"
    >
      {text}
    </Link>
  );
}

function ItemGroup({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-2xl bg-zinc-900 p-3">
      <p className="mb-2 text-xs text-zinc-500">{title}</p>
      <div className="space-y-2">{children}</div>
    </section>
  );
}

interface BriefingTextProps {
  payload: BriefingEditionPayload;
  /** Only the letter the edition draws, for a page that lists what it left out below it. */
  letterOnly?: boolean;
}

/** A brief read as text: the headline, GAIA's message, its items, then what it could not draw or left out. */
export function BriefingText({
  payload,
  letterOnly = false,
}: BriefingTextProps) {
  const calendar = payload.calendar ?? [];
  const uncomposed = letterOnly ? [] : (payload.uncomposed ?? []);
  const undrawn = letterOnly ? [] : undrawnLines(payload);
  return (
    <article className="w-full rounded-2xl bg-zinc-800 p-4">
      <p className="mb-3 text-sm font-semibold text-zinc-100">
        {payload.headline}
      </p>
      {payload.message && (
        <MarkdownRenderer
          content={payload.message}
          className="mb-4 text-sm leading-relaxed text-zinc-300"
          hideCodeToolbar
        />
      )}
      <div className="space-y-2">
        {calendar.length > 0 && (
          <ItemGroup title="Today">
            {calendar.map((event) => (
              <p
                key={`${event.start ?? "all-day"}-${event.title}`}
                className="text-sm font-medium text-zinc-200"
              >
                <span className="mr-2 text-xs text-zinc-500 tabular-nums">
                  {event.start ? formatClockTime(event.start) : "All day"}
                </span>
                {event.title}
              </p>
            ))}
          </ItemGroup>
        )}
        {payload.sections.map((section) => (
          <ItemGroup key={section.title} title={section.title}>
            {section.items.map((item) => (
              <ItemRow
                key={item.todo_id ?? item.text}
                text={item.text}
                href={itemHref(item)}
              />
            ))}
          </ItemGroup>
        ))}
        {undrawn.length > 0 && (
          <ItemGroup title="More from GAIA">
            {undrawn.map((line) => (
              <p key={line} className="text-sm text-zinc-300">
                {line}
              </p>
            ))}
          </ItemGroup>
        )}
        {uncomposed.length > 0 && (
          <ItemGroup title={ON_YOUR_RADAR_TITLE}>
            <ul className="divide-y divide-white/5">
              {uncomposed.map((item) => (
                <PoolItemRow
                  key={`${item.app}-${item.todo_id ?? item.title}`}
                  item={item}
                  className="py-3 first:pt-0 last:pb-0"
                />
              ))}
            </ul>
          </ItemGroup>
        )}
      </div>
    </article>
  );
}

/** A titled list under the edition, in its column. */
function BelowEdition({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <section
      aria-labelledby={id}
      className={cn("mx-auto w-full", BRIEF_PAGE_COLUMN_CLASS)}
    >
      <h2 id={id} className="mb-1 text-sm font-medium text-zinc-300">
        {title}
      </h2>
      <ul className="divide-y divide-white/5">{children}</ul>
    </section>
  );
}

/** Where a left-out item came from and where it stands: its app, its state, then its own detail. */
function PoolItemContext({ item }: { item: BriefPoolItem }) {
  const parts = [item.app, BRIEF_ITEM_STATES[item.kind], item.detail].filter(
    (part): part is string => Boolean(part),
  );
  return (
    <p className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-zinc-500">
      {parts.map((part, index) => (
        <span key={part} className="flex items-center gap-2">
          {index > 0 && (
            <span aria-hidden className="size-0.5 rounded-full bg-zinc-600" />
          )}
          {part}
        </span>
      ))}
    </p>
  );
}

/** What GAIA read but left out of the brief, one row each, opening its source when it has one. */
function PoolItemRow({
  item,
  className,
}: {
  item: BriefPoolItem;
  className: string;
}) {
  const href = poolItemHref(item);
  return (
    <li className={cn("flex flex-col gap-1", className)}>
      {href ? (
        <Link
          href={href}
          {...(href.startsWith("/")
            ? {}
            : { target: "_blank", rel: "noopener noreferrer" })}
          className="inline-flex w-fit items-center gap-1 text-sm text-zinc-100 hover:text-white"
        >
          {item.title}
          <ArrowUpRight01Icon aria-hidden className="size-3.5 text-zinc-500" />
        </Link>
      ) : (
        <p className="text-sm text-zinc-100">{item.title}</p>
      )}
      <PoolItemContext item={item} />
    </li>
  );
}

const ON_YOUR_RADAR_TITLE = "Also on your radar";
const ON_YOUR_RADAR_NOTE =
  "Other things GAIA found that didn't make the brief.";

/**
 * The pool the composition left out, set apart from the brief as a quiet aside
 * so it reads as more to know about, not as part of the day's letter.
 */
function OnYourRadar({ items }: { items: BriefPoolItem[] }) {
  return (
    <section
      aria-labelledby="brief-on-your-radar"
      className={cn(
        "mx-auto w-full rounded-2xl bg-zinc-900 p-4",
        BRIEF_PAGE_COLUMN_CLASS,
      )}
    >
      <header className="mb-4 px-1">
        <h2
          id="brief-on-your-radar"
          className="text-base font-medium text-zinc-100"
        >
          {ON_YOUR_RADAR_TITLE}
        </h2>
        <p className="mt-1 text-sm text-pretty text-zinc-500">
          {ON_YOUR_RADAR_NOTE}
        </p>
      </header>
      <ul className="flex flex-col gap-2">
        {items.map((item) => (
          <PoolItemRow
            key={`${item.app}-${item.todo_id ?? item.title}`}
            item={item}
            className="rounded-xl bg-zinc-800 px-3 py-2.5"
          />
        ))}
      </ul>
    </section>
  );
}

/**
 * One brief. The rendered edition already carries every item it drew, so it
 * stands on the page alone with only what it could not draw or left out listed
 * under it; a brief stored before editions were rendered reads as text.
 */
export function BriefingEdition({ payload, imageUrl }: BriefingEditionProps) {
  if (!imageUrl) return <BriefingText payload={payload} />;
  const uncomposed = payload.uncomposed ?? [];
  const undrawn = undrawnLines(payload);
  const leftOut = leftOutItems(payload);
  const pastRows = hiddenEvents(payload.calendar);
  return (
    <div className="w-full space-y-8">
      <Image
        src={imageUrl}
        alt={payload.headline}
        width={EDITION_RENDER_WIDTH_PX}
        height={EDITION_TYPICAL_HEIGHT_PX}
        sizes="(max-width: 640px) 100vw, 572px"
        // On a phone the image's own transparent margin stands in for StandalonePage's
        // px-4 gutter, so the paper gets the screen's width instead of losing 32px.
        className="-mx-4 h-auto w-[calc(100%+2rem)] max-w-none sm:mx-auto sm:w-full sm:max-w-[572px]"
      />
      {/* The edition is a picture of the letter; a screen reader reads the letter itself. */}
      <div className="sr-only">
        <BriefingText payload={payload} letterOnly />
      </div>
      {(undrawn.length > 0 || leftOut.length > 0 || pastRows.length > 0) && (
        <BelowEdition id="brief-more-from-gaia" title="More from GAIA">
          {undrawn.map((line) => (
            <li key={line} className="py-3 text-sm text-zinc-300">
              {line}
            </li>
          ))}
          {pastRows.map((event) => (
            <li
              key={`${event.start ?? "all-day"}-${event.title}`}
              className="py-3 text-sm text-zinc-300"
            >
              {event.start ? `${formatClockTime(event.start)} ` : ""}
              {event.title}
            </li>
          ))}
          {leftOut.map((item) => (
            <li key={item.todo_id ?? item.text} className="py-3">
              <ItemRow text={item.text} href={itemHref(item)} />
            </li>
          ))}
        </BelowEdition>
      )}
      {uncomposed.length > 0 && <OnYourRadar items={uncomposed} />}
    </div>
  );
}
