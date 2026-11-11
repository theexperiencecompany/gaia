"use client";

import { Link } from "@heroui/link";
import type {
  BriefingEvent,
  BriefingPayload,
  BriefPoolItem,
} from "@shared/api/generated";
import Image from "next/image";
import type { ReactNode } from "react";
import type { z } from "zod";

import type { briefingSchema } from "@/config/openui/promptSpecs";
import MarkdownRenderer from "@/features/chat/components/interface/MarkdownRenderer";

/** The brief's fields this view reads: the stored payload and the OpenUI component share them. */
export type BriefingEditionPayload = z.infer<typeof briefingSchema> & {
  calendar?: BriefingEvent[];
  message?: string | null;
  /** What the brief read but GAIA left out of today's composition. */
  uncomposed?: BriefPoolItem[];
  /** Composed blocks the day's edition could not draw in its idiom. */
  undrawn?: BriefingPayload["undrawn"];
};

type UndrawnBlock = BriefingPayload["undrawn"][number];

type EditionItem = BriefingEditionPayload["sections"][number]["items"][number];

export interface BriefingEditionProps {
  payload: BriefingEditionPayload;
  /** The day's rendered edition, when the brief was rendered. */
  imageUrl?: string | null;
}

// Rendered 540 CSS px wide at 3x, shown at that width (max-w-[540px]). The height
// only reserves space while loading: `h-auto` keeps the natural ratio, never cropping.
const EDITION_WIDTH = 1620;
const EDITION_TYPICAL_HEIGHT = 4500;

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

/** A calendar event's wall-clock "HH:MM" as the reader's own clock writes it. */
function clockTime(start: string): string {
  const [hours, minutes] = start.split(":").map(Number);
  const at = new Date();
  at.setHours(hours, minutes, 0, 0);
  return at.toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
}

/** A brief with no rendered edition, read as text: the headline, GAIA's message, its items, then what it could not draw or left out. */
function BriefingText({ payload }: { payload: BriefingEditionPayload }) {
  const calendar = payload.calendar ?? [];
  const uncomposed = payload.uncomposed ?? [];
  const undrawn = undrawnLines(payload);
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
                  {event.start ? clockTime(event.start) : "All day"}
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
          <ItemGroup title="Everything else">
            {uncomposed.map((item) => (
              <ItemRow
                key={`${item.app}-${item.todo_id ?? item.title}`}
                text={item.title}
                href={poolItemHref(item)}
              />
            ))}
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
    <section aria-labelledby={id} className="mx-auto w-full max-w-[540px]">
      <h2 id={id} className="mb-1 text-sm font-medium text-zinc-300">
        {title}
      </h2>
      <ul className="divide-y divide-white/5">{children}</ul>
    </section>
  );
}

/** What GAIA read but left out of the edition, one row each, opening its source when it has one. */
function PoolItemRow({ item }: { item: BriefPoolItem }) {
  const href = poolItemHref(item);
  return (
    <li className="flex flex-col gap-0.5 py-3">
      {href ? (
        <Link
          href={href}
          isExternal={!href.startsWith("/")}
          className="w-fit text-sm text-zinc-100 hover:text-white"
        >
          {item.title}
        </Link>
      ) : (
        <p className="text-sm text-zinc-100">{item.title}</p>
      )}
      {item.detail && <p className="text-xs text-zinc-500">{item.detail}</p>}
    </li>
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
  return (
    <div className="w-full space-y-8">
      <Image
        src={imageUrl}
        alt={payload.headline}
        width={EDITION_WIDTH}
        height={EDITION_TYPICAL_HEIGHT}
        sizes="(max-width: 572px) 100vw, 540px"
        className="mx-auto h-auto w-full max-w-[540px]"
      />
      {undrawn.length > 0 && (
        <BelowEdition id="brief-more-from-gaia" title="More from GAIA">
          {undrawn.map((line) => (
            <li key={line} className="py-3 text-sm text-zinc-300">
              {line}
            </li>
          ))}
        </BelowEdition>
      )}
      {uncomposed.length > 0 && (
        <BelowEdition id="brief-everything-else" title="Everything else">
          {uncomposed.map((item) => (
            <PoolItemRow
              key={`${item.app}-${item.todo_id ?? item.title}`}
              item={item}
            />
          ))}
        </BelowEdition>
      )}
    </div>
  );
}
