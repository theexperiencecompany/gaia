import type { ReactNode } from "react";

import type {
  LinkContent,
  LinkEnvelope,
  ShortLinkTargetType,
} from "@/types/features/shortLinkTypes";

import type { DEAD_LINK_COPY } from "./constants";

/** A denial that means the link will never open again (or never did). */
export type DeadLinkDenial = keyof typeof DEAD_LINK_COPY;

/** What a viewer sees instead of the link's target. */
export type LinkUnavailableState =
  | { denial: DeadLinkDenial }
  | { denial: "link_sign_in_required"; slug: string }
  | { denial: "link_forbidden"; signedInAs: string };

/** How opening a link turned out, on the server or in the browser. */
export type LinkResolution =
  | { kind: "open"; envelope: LinkEnvelope }
  | { kind: "unavailable"; state: LinkUnavailableState };

/** The public view one target type resolves to. */
export type LinkViewOf<T extends ShortLinkTargetType> = Extract<
  LinkEnvelope["view"],
  { target_type: T }
>;

export interface LinkViewProps<T extends ShortLinkTargetType> {
  slug: string;
  view: LinkViewOf<T>;
  content: LinkContent | null;
  /** The Report action, for a view that draws its own bar. */
  reportAction: ReactNode;
}
