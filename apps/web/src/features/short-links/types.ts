import type { ReactNode } from "react";

import type {
  LinkContent,
  LinkDenial,
  LinkEnvelope,
  ShortLinkTargetType,
} from "@/types/features/shortLinkTypes";

import type { GATED_LINK_DENIALS, LINK_LOOKUP_LOCKED_CODE } from "./constants";

/** A denial that means the link will never open again (or never did). */
export type DeadLinkDenial = Exclude<
  LinkDenial,
  (typeof GATED_LINK_DENIALS)[number]
>;

/** Every state that renders the dead-link page: a dead denial, or the guessing lockout. */
export type DeadLinkState = DeadLinkDenial | typeof LINK_LOOKUP_LOCKED_CODE;

/** What a viewer sees instead of the link's target. */
export type LinkUnavailableState =
  | { denial: DeadLinkState }
  | { denial: Extract<LinkDenial, "link_sign_in_required">; slug: string }
  | { denial: Extract<LinkDenial, "link_forbidden">; signedInAs: string };

/** How opening a link turned out, on the server or in the browser. */
export type LinkResolution =
  | { kind: "open"; envelope: LinkEnvelope }
  | { kind: "unavailable"; state: LinkUnavailableState };

/** The browser's answer for a gated link: what it resolved to, or why resolving threw. */
export type GatedOutcome =
  | { resolution: LinkResolution }
  | { failure: unknown };

/** The public view one target type resolves to. */
export type LinkViewOf<T extends ShortLinkTargetType> = Extract<
  LinkEnvelope["view"],
  { target_type: T }
>;

export interface LinkViewProps<T extends ShortLinkTargetType> {
  slug: string;
  view: LinkViewOf<T>;
  content: LinkContent | null;
  /** The link's file can be saved from the API's download route. */
  downloadable: boolean;
  /** The Report action, for a view that draws its own bar. */
  reportAction: ReactNode;
}
