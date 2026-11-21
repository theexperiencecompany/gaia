import { tv } from "tailwind-variants";

/**
 * v2's month calendar on v3's Calendar parts, flat on the surface it sits in:
 * chevrons either side of a centred month, 32px round days in a 224px grid,
 * the chosen day on the accent, today in accent text, other months' days dimmed.
 */
export const calendarVariants = tv({
  slots: {
    base: "w-full max-w-none pb-[11px]",
    header: "flex items-center justify-between px-1 pt-1 pb-2",
    heading: "flex-1 text-center text-sm font-medium text-zinc-200",
    navButton:
      "size-8 rounded-full text-zinc-500 hover:bg-zinc-700 hover:text-zinc-200",
    grid: "mx-auto w-56 gap-y-1",
    headerCell: "pb-2.5 text-xs font-normal text-zinc-500",
    cell: "size-8 rounded-full text-[13px] font-normal text-foreground data-[outside-month=true]:text-zinc-600 data-[outside-month=true]:opacity-100 not-data-[selected=true]:hover:bg-zinc-700 data-[today=true]:not-data-[selected=true]:bg-transparent data-[today=true]:not-data-[selected=true]:text-accent data-[today=true]:not-data-[selected=true]:hover:bg-zinc-700 data-[selected=true]:bg-accent data-[selected=true]:font-medium data-[selected=true]:text-black",
  },
});
