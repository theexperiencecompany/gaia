import { Tooltip } from "@heroui/tooltip";
import { SquareArrowUpRight02Icon } from "@icons";
import type { Components } from "streamdown";
import type { CitationRef } from "@/features/chat/utils/citationUtils";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import CustomAnchor from "../../code-block/CustomAnchor";

type CitationSurface = "inline" | "footer";

const trackCitationOpened = (ref: CitationRef, surface: CitationSurface) => {
  trackEvent(ANALYTICS_EVENTS.CHAT_CITATION_OPENED, {
    surface,
    citation_number: ref.n,
  });
};

function CitationTooltip({ ref }: Readonly<{ ref: CitationRef }>) {
  return (
    <div className="max-w-[240px]">
      <div className="truncate text-xs font-medium text-zinc-100">
        {ref.label}
      </div>
      {ref.host && (
        <div className="mt-0.5 truncate text-[10px] text-zinc-400">
          {ref.host}
        </div>
      )}
    </div>
  );
}

/**
 * Superscript numbered chip for an `[n]` marker inside the answer text.
 * Links to the source; hover reveals the source title and host.
 */
export function CitationChip({ ref }: Readonly<{ ref: CitationRef }>) {
  return (
    <Tooltip
      showArrow
      placement="top"
      className="border-2 border-zinc-800 bg-secondary-bg p-3 text-white shadow-lg"
      content={<CitationTooltip ref={ref} />}
    >
      <a
        href={ref.url}
        target="_blank"
        rel="noopener noreferrer"
        onClick={() => trackCitationOpened(ref, "inline")}
        className="mx-0.5 inline-flex h-[14px] min-w-[14px] cursor-pointer items-center justify-center rounded-[4px] bg-zinc-700 px-[3px] align-super text-[10px] font-semibold leading-none text-zinc-200 transition-colors hover:bg-primary hover:text-white"
      >
        {ref.n}
      </a>
    </Tooltip>
  );
}

/**
 * Markdown `a` override that turns exactly the `[n](url)` links produced by
 * applyCitationLinks into numbered chips and leaves every other link with the
 * normal preview anchor.
 */
export function createCitationAComponent(
  citations: readonly CitationRef[],
  isStreaming: boolean | undefined,
): NonNullable<Components["a"]> {
  return ({ href, children, ...props }) => {
    const text = typeof children === "string" ? children : undefined;
    const marker = text?.match(/^\[(\d+)\]$/);
    const ref = marker ? citations[Number(marker[1]) - 1] : undefined;
    if (ref) return <CitationChip ref={ref} />;
    return (
      <CustomAnchor href={href} isStreaming={isStreaming} {...props}>
        {children}
      </CustomAnchor>
    );
  };
}

/** Compact source list under the answer, matching the inline chip numbering. */
export function CitationsFooter({
  refs,
}: Readonly<{ refs: readonly CitationRef[] }>) {
  return (
    <div className="mt-2 w-full rounded-2xl bg-zinc-800 p-3">
      <span className="mb-1.5 block px-1.5 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
        Sources
      </span>
      <ul className="space-y-0.5">
        {refs.map((ref) => (
          <li key={ref.n}>
            <a
              href={ref.url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => trackCitationOpened(ref, "footer")}
              className="group flex items-center gap-2 rounded-xl px-1.5 py-1 transition-colors hover:bg-zinc-700/50"
            >
              <span className="flex h-4 min-w-4 shrink-0 items-center justify-center rounded-md bg-zinc-700 px-1 text-[10px] font-semibold text-zinc-200">
                {ref.n}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm text-zinc-100 group-hover:underline">
                  {ref.label}
                </span>
                {ref.host && (
                  <span className="block truncate text-[11px] text-zinc-500">
                    {ref.host}
                  </span>
                )}
              </span>
              <SquareArrowUpRight02Icon
                className="size-3.5 shrink-0 text-zinc-500 transition-colors group-hover:text-zinc-200"
                width={14}
                height={14}
              />
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
