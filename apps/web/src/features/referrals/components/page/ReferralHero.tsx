import { cn } from "@/lib/utils";

interface ReferralHeroProps {
  title: string;
  body: string;
  /** The minimal layout speaks at settings volume instead of display size. */
  compact?: boolean;
}

export function ReferralHero({
  title,
  body,
  compact = false,
}: ReferralHeroProps) {
  return (
    <header className={cn("flex flex-col", compact ? "gap-1" : "gap-2")}>
      <h1
        className={cn(
          "text-balance text-zinc-100",
          compact
            ? "text-base font-semibold"
            : "font-serif text-[2rem] leading-[1.1] font-normal tracking-tight",
        )}
      >
        {title}
      </h1>
      <p className="max-w-[52ch] text-sm leading-relaxed text-pretty text-zinc-400">
        {body}
      </p>
    </header>
  );
}
