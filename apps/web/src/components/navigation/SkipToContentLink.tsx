/** The id of each layout's primary content region, the skip link's target. */
export const MAIN_CONTENT_ID = "main-content";

/** Keyboard bypass past the navigation; visually hidden until focused. */
export function SkipToContentLink() {
  return (
    // A native fragment link, not HeroUI/Next Link: those route through
    // router.push, which scrolls but leaves focus on the link, so Tab would
    // land back in the navigation instead of the content.
    <a
      href={`#${MAIN_CONTENT_ID}`}
      className="fixed top-4 left-4 z-100 rounded-full bg-primary px-4 py-2 text-sm font-medium text-black not-focus:sr-only"
    >
      Skip to content
    </a>
  );
}
