/** Separator dot between inline metadata ("10:15 PM · Work"); a shape, not a glyph. */
export function MetaDot() {
  return (
    <span aria-hidden className="size-1 shrink-0 rounded-full bg-zinc-500" />
  );
}
