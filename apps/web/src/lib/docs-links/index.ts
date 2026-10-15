/**
 * docs-links.ts - marketing pages -> docs.heygaia.io cross-links.
 *
 * One entry point for the four programmatic marketing templates
 * (`/learn`, `/compare`, `/alternative-to`, `/automate`). Static tables live
 * in `./data/`; the automate lookup is derived from the combo's tool slugs.
 * Templates render entries inside their existing related-links section as
 * server-rendered links. Slugs with no entry render nothing. Docs URLs are
 * absolute so they survive locale prefixes.
 */

export interface DocsGuideLink {
  readonly title: string;
  readonly url: string;
}

export { getAutomateDocsLinks } from "./automate-links";
export { ALTERNATIVE_DOCS_LINKS } from "./data/alternative-links";
export { COMPARE_DOCS_LINKS } from "./data/compare-links";
export { LEARN_DOCS_LINKS } from "./data/learn-links";
