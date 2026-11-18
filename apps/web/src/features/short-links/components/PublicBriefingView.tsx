import type { LinkViewProps } from "../types";

/** A shared brief's front page: its kicker, date and headline, never its items or edition. */
export function PublicBriefingView({ view }: LinkViewProps<"briefing">) {
  return (
    <article className="flex flex-col gap-2">
      <p className="flex items-center gap-2 text-xs tracking-wide text-zinc-500 uppercase">
        {view.kicker}
        <span aria-hidden className="size-0.5 rounded-full bg-zinc-600" />
        {view.date}
      </p>
      <h1 className="text-2xl font-medium text-pretty text-white">
        {view.headline}
      </h1>
    </article>
  );
}
