interface ValueHeadlineProps {
  headline: string;
  line: string;
}

/** The one-glance value statement every concept leads with: a headline and one supporting line. */
export function ValueHeadline({ headline, line }: ValueHeadlineProps) {
  return (
    <div className="flex flex-col gap-2">
      <h2 className="text-[1.75rem] leading-tight font-semibold tracking-tight text-balance text-zinc-100 @max-md:text-2xl">
        {headline}
      </h2>
      <p className="text-base leading-relaxed text-pretty text-zinc-400">
        {line}
      </p>
    </div>
  );
}
