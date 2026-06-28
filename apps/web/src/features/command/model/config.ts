// Visual contract for the command menu — kept identical to the original GAIA
// Command K so the look is unchanged. Tweak here to restyle the whole palette.

const EASE = [0.19, 1, 0.22, 1] as [number, number, number, number];

export const ANIMATION_CONFIG = {
  backdrop: {
    initial: { opacity: 0 },
    animate: { opacity: 1 },
    exit: { opacity: 0 },
    transition: { duration: 0.2, ease: EASE },
  },
  container: {
    initial: { opacity: 0, scale: 0.95, y: -8 },
    animate: { opacity: 1, scale: 1, y: 0 },
    exit: { opacity: 0, scale: 0.95, y: -8 },
    transition: { duration: 0.2, ease: EASE },
  },
} as const;

export const COMMAND_MENU_STYLES = {
  backdrop: "fixed inset-0 bg-black/40 backdrop-blur-md",
  container:
    "relative w-full max-w-2xl overflow-hidden rounded-2xl border border-zinc-800/40 bg-zinc-900/50 backdrop-blur-2xl shadow-2xl",
  inputWrapper:
    "flex items-center gap-3 border-b border-zinc-800/30 px-5 py-4 mb-2",
  searchIcon: "h-4 w-4 text-zinc-500",
  input:
    "flex-1 bg-transparent text-zinc-100 placeholder-zinc-500 outline-none",
  list: "max-h-[400px] overflow-y-auto pb-3 outline-none!",
  empty: "flex h-16 items-center justify-center text-sm text-zinc-500",
  item: "mx-2 flex cursor-pointer items-center gap-3 rounded-lg px-2.5 py-3 text-sm text-zinc-500 transition-all duration-200 hover:bg-zinc-800/40 aria-selected:bg-zinc-800/50 aria-selected:text-zinc-300!",
  separator: "mx-3 h-px bg-zinc-800/50",
  itemShortcut:
    "inline-flex h-5 items-center gap-0.5 rounded-md bg-zinc-800/50 px-1.5 font-mono text-[10px] font-medium text-zinc-500",
  flexOne: "flex-1",
  contentWrapper: "min-w-0 flex-1",
  resultTitle: "truncate text-sm",
  resultSubtitle: "truncate text-xs text-zinc-500",
  footer: "border-t border-zinc-800/30 px-5 py-3",
  footerText: "text-xs text-zinc-500",
  modalWrapper: "fixed inset-0 z-50 flex items-start justify-center pt-[20vh]",
  groupHeadings:
    "[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:pt-5 [&_[cmdk-group-heading]]:pb-2 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-zinc-500",
} as const;
