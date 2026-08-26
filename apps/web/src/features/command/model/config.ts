// Visual contract for the command menu. Tweak here to restyle the whole
// palette.
//
// Motion philosophy (research consensus — Rauno, Linear, Geist): a palette
// is a hundred-times-a-day surface. It must APPEAR instantly; only the exit
// fades. The list keeps a directional slide between levels (browsing feels
// spatial) but stays still while filtering.

const EASE = [0.19, 1, 0.22, 1] as [number, number, number, number];

export const ANIMATION_CONFIG = {
  backdrop: {
    initial: { opacity: 0 },
    animate: { opacity: 1 },
    exit: { opacity: 0 },
    transition: { duration: 0.15, ease: "linear" as const },
  },
  container: {
    initial: { opacity: 0 },
    animate: { opacity: 1 },
    exit: { opacity: 0 },
    // Open is near-instant; exit gets a short fade so dismissal reads.
    transition: {
      duration: 0.12,
      ease: "linear" as const,
      exit: { duration: 0.15, ease: EASE },
    },
  },
} as const;

// List entrance — a subtle directional slide + stagger that plays when you open
// the palette or move between menu levels (browsing): rows ease in from the
// right going deeper, from the left going back. While searching it collapses to
// a plain instant fade so filtering never feels animated. The list clips
// overflow-x (see COMMAND_MENU_STYLES.list) so the transient slide never shows a
// horizontal scrollbar. Reduced motion = no movement.
const ROW_SLIDE_PX = 12;
const ROW_STAGGER_STEP = 0.022;
const ROW_STAGGER_CAP = 8;

interface RowEntranceArgs {
  index: number;
  direction: 1 | -1;
  browsing: boolean;
  reduced: boolean;
}

export function rowEntrance({
  index,
  direction,
  browsing,
  reduced,
}: RowEntranceArgs) {
  if (reduced)
    return { initial: false as const, animate: { opacity: 1, x: 0 } };
  return {
    initial: { opacity: 0, x: browsing ? direction * ROW_SLIDE_PX : 0 },
    animate: { opacity: 1, x: 0 },
    transition: {
      duration: 0.2,
      ease: EASE,
      delay: browsing ? Math.min(index, ROW_STAGGER_CAP) * ROW_STAGGER_STEP : 0,
    },
  };
}

export const COMMAND_MENU_STYLES = {
  backdrop: "fixed inset-0 bg-black/40 backdrop-blur-md",
  container:
    "relative w-full max-w-2xl overflow-hidden rounded-2xl border border-zinc-800/40 bg-zinc-900/50 backdrop-blur-2xl shadow-2xl",
  inputWrapper:
    "flex items-center gap-3 border-b border-zinc-800/30 px-5 py-4 mb-2",
  input:
    "flex-1 bg-transparent text-zinc-100 placeholder-zinc-500 outline-none",
  listWrapper: "relative",
  list: "max-h-[480px] overflow-x-hidden overflow-y-auto pb-3 outline-none!",
  // Gradient hairlines pinned to the list viewport edges; opacity toggled
  // from the scroll handler (see updateScrollShadow).
  scrollShadow:
    "pointer-events-none absolute inset-x-0 top-0 z-10 h-6 bg-gradient-to-b from-zinc-950/80 to-transparent transition-opacity duration-150",
  scrollShadowBottom:
    "bottom-auto top-auto inset-x-0 bottom-0 bg-gradient-to-t from-zinc-950/80 to-transparent",
  separator: "mx-3 h-px bg-zinc-800/50",
  flexOne: "flex-1",
  contentWrapper: "min-w-0 flex-1",
  resultSubtitle: "truncate text-xs text-zinc-500",
  footer: "border-t border-zinc-800/30 px-5 py-3",
  footerText: "text-xs text-zinc-500",
  liveRegion:
    "pointer-events-none absolute h-px w-px overflow-hidden whitespace-nowrap [clip:rect(0,0,0,0)]",
  modalWrapper: "fixed inset-0 z-50 flex items-start justify-center pt-[20vh]",
  groupHeadings:
    "[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:pt-5 [&_[cmdk-group-heading]]:pb-2 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-zinc-500",
} as const;
