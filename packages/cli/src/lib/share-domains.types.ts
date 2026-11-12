/**
 * The share domains a self-host with a domain may add beside it.
 * @module lib/share-domains.types
 */

/** link: /<slug> redirects to GAIA's /l/<slug>. usercontent: shared files' bytes. */
export type ShareDomainKind = "link" | "usercontent";

/** The share domains a run serves; an absent kind is not served. */
export type ShareDomains = Partial<Record<ShareDomainKind, string>>;

/** `--link-domain` / `--usercontent-domain`, or false from their `--no-` forms. */
export type ShareDomainFlags = Partial<Record<ShareDomainKind, string | false>>;

/** What the share-domain prompt shows. */
export interface ShareDomainRequest {
  kind: ShareDomainKind;
  /** The domain GAIA itself is served at, which a share domain sits beside. */
  appDomain: string;
  /** Why the last answer was refused. */
  retry?: string;
}
