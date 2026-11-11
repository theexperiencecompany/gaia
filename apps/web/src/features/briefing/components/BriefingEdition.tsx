"use client";

import { Link } from "@heroui/link";
import type { BriefingEvent } from "@shared/api/generated";
import Image from "next/image";
import type { ReactNode } from "react";
import type { z } from "zod";

import type { briefingSchema } from "@/config/openui/promptSpecs";
import MarkdownRenderer from "@/features/chat/components/interface/MarkdownRenderer";

/** The brief's fields this view reads: the stored payload and the OpenUI component share them. */
export type BriefingEditionPayload = z.infer<typeof briefingSchema> & {
  calendar?: BriefingEvent[];
  message?: string | null;
};

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

function ItemRow({ item }: { item: EditionItem }) {
  const href = itemHref(item);
  if (!href) {
    return <p className="text-sm font-medium text-zinc-200">{item.text}</p>;
  }
  return (
    <Link
      href={href}
      className="block text-sm font-medium text-zinc-200 hover:text-zinc-50"
    >
      {item.text}
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

/** A brief with no rendered edition, read as text: the headline, GAIA's message, then its items. */
function BriefingText({ payload }: { payload: BriefingEditionPayload }) {
  const calendar = payload.calendar ?? [];
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
              <ItemRow key={item.todo_id ?? item.text} item={item} />
            ))}
          </ItemGroup>
        ))}
      </div>
    </article>
  );
}

/**
 * One brief. The rendered edition already carries every item, so it stands on
 * the page alone; a brief stored before editions were rendered reads as text.
 */
export function BriefingEdition({ payload, imageUrl }: BriefingEditionProps) {
  if (!imageUrl) return <BriefingText payload={payload} />;
  return (
    <Image
      src={imageUrl}
      alt={payload.headline}
      width={EDITION_WIDTH}
      height={EDITION_TYPICAL_HEIGHT}
      sizes="(max-width: 572px) 100vw, 540px"
      className="mx-auto h-auto w-full max-w-[540px]"
    />
  );
}
