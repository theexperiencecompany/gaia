import { BriefingEdition } from "@/features/briefing";

import type { LinkViewProps } from "../types";

/** A shared brief: its rendered edition, or its text when it was never rendered. */
export function PublicBriefingView({ view }: LinkViewProps<"briefing">) {
  return (
    <BriefingEdition payload={view.payload} imageUrl={view.edition_image_url} />
  );
}
