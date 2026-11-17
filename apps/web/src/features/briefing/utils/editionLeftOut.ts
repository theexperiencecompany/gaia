/**
 * What a rendered edition left to the brief's page, and the words for an item's state.
 *
 * INTEGRATION(P-api2): the API will send the left-out items, the calendar events
 * past the edition's rows and each item's state label. Then these functions read
 * those fields, and EDITION_ROWS_SHOWN, BRIEF_ITEM_STATES and the drift test that
 * parses the Python for them (editionLeftOut.test.ts) are deleted.
 */
import type {
  BriefingEvent,
  BriefingPayload,
  BriefPoolItem,
} from "@shared/api/generated";

/** Rows an edition prints per items block or calendar. Mirrors EDITION_ROWS_SHOWN in apps/api/app/constants/briefing.py. */
export const EDITION_ROWS_SHOWN = 3;

/** Where a brief item stands, in a few words. Mirrors BRIEFING_ITEM_STATES in apps/api/app/models/briefing_models.py. */
export const BRIEF_ITEM_STATES: Record<BriefPoolItem["kind"], string> = {
  you: "Waiting on you",
  gaia: "In progress",
  lookback: "Done",
  failed: "Failed",
  note: "Note",
};

type LeftOutSource<Item> = Pick<BriefingPayload, "blocks" | "undrawn"> & {
  sections: { items: Item[] }[];
};

/** Every item the edition left out: the sections it could not draw, then the rows past its own. */
export function leftOutItems<Item>(
  payload: Partial<LeftOutSource<Item>> & Pick<LeftOutSource<Item>, "sections">,
): Item[] {
  const drawnOverflow = (payload.blocks ?? []).flatMap((block) =>
    block.kind === "items"
      ? (payload.sections[block.section]?.items ?? []).slice(EDITION_ROWS_SHOWN)
      : [],
  );
  const undrawnSections = (payload.undrawn ?? []).flatMap((block) =>
    block.kind === "lead" || block.kind === "items"
      ? (payload.sections[block.section]?.items ?? [])
      : [],
  );
  return [...undrawnSections, ...drawnOverflow];
}

/** The day's events past the rows the edition prints. */
export function hiddenEvents(calendar: BriefingEvent[] | undefined) {
  return (calendar ?? []).slice(EDITION_ROWS_SHOWN);
}
