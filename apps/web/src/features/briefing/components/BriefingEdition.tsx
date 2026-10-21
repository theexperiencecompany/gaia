"use client";

import { Link } from "@heroui/link";
import type { BriefingEvent } from "@shared/api/generated";
import Image from "next/image";
import type { ReactNode } from "react";
import type { z } from "zod";

import type { briefingSchema } from "@/config/openui/promptSpecs";

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

// The edition renders 540 CSS px wide at 3x. Its height follows the day's
// content, so this height only reserves space while loading: with `h-auto` the
// browser switches to the image's natural ratio, never cropping it.
const EDITION_WIDTH = 1620;
const EDITION_TYPICAL_HEIGHT = 4500;

function itemHref(item: EditionItem): string | null {
  if (item.link) return item.link;
  return item.todo_id ? `/todos?todoId=${item.todo_id}` : null;
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

/** One brief: the day's rendered edition, the message GAIA wrote, then its real items as a tappable list. */
export function BriefingEdition({ payload, imageUrl }: BriefingEditionProps) {
  const calendar = payload.calendar ?? [];
  return (
    <article className="w-full rounded-2xl bg-zinc-800 p-4">
      {imageUrl && (
        <Image
          src={imageUrl}
          alt={payload.headline}
          width={EDITION_WIDTH}
          height={EDITION_TYPICAL_HEIGHT}
          sizes="(max-width: 768px) 100vw, 768px"
          className="mb-4 h-auto w-full rounded-xl"
        />
      )}
      <p className="mb-3 text-sm font-semibold text-zinc-100">
        {payload.headline}
      </p>
      {payload.message && (
        <p className="mb-4 whitespace-pre-line text-sm leading-relaxed text-zinc-300">
          {payload.message}
        </p>
      )}
      <div className="space-y-2">
        {calendar.length > 0 && (
          <ItemGroup title="Today">
            {calendar.map((event) => (
              <p
                key={`${event.start ?? "all-day"}-${event.title}`}
                className="text-sm font-medium text-zinc-200"
              >
                <span className="mr-2 text-xs text-zinc-500">
                  {event.start ?? "All day"}
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
