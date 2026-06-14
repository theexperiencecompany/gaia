/**
 * Brand / press-kit image assets exposed to search engines via the brand image
 * sitemap (`/brand/sitemap.xml`). Single source of truth for the marks served
 * from `/public/brand` that should be discoverable in image search.
 *
 * The interactive download UI (`brand/components/BrandAssets.tsx`) additionally
 * offers per-format variants (e.g. an `.svg` alongside the `.png`); search
 * engines only index raster images, so this list intentionally points at the
 * canonical raster of each mark.
 */
export interface BrandImageAsset {
  /** Path under `/public`. */
  path: string;
  /** Title for `<image:title>`. */
  title: string;
  /** Description for `<image:caption>`. */
  caption: string;
}

// [file stem under /public/brand (.png), <image:title>, <image:caption>]
const ASSETS: ReadonlyArray<readonly [string, string, string]> = [
  ["gaia_logo", "GAIA Logo", "The primary GAIA brand mark"],
  [
    "gaia_wordmark_black",
    "GAIA Wordmark (Black)",
    "GAIA wordmark, light backgrounds",
  ],
  [
    "gaia_wordmark_white",
    "GAIA Wordmark (White)",
    "GAIA wordmark, dark backgrounds",
  ],
  [
    "experience_logo_black",
    "The Experience Company Logo (Black)",
    "Experience mark, light backgrounds",
  ],
  [
    "experience_logo_white",
    "The Experience Company Logo (White)",
    "Experience mark, dark backgrounds",
  ],
  [
    "experience_wordmark_black",
    "Experience Wordmark (Black)",
    "Experience wordmark, light backgrounds",
  ],
  [
    "experience_wordmark_white",
    "Experience Wordmark (White)",
    "Experience wordmark, dark backgrounds",
  ],
  [
    "experience_full_wordmark_black",
    "The Experience Company Full Wordmark (Black)",
    "Full Experience wordmark, light backgrounds",
  ],
  [
    "experience_full_wordmark_white",
    "The Experience Company Full Wordmark (White)",
    "Full Experience wordmark, dark backgrounds",
  ],
];

export const BRAND_IMAGE_ASSETS: readonly BrandImageAsset[] = ASSETS.map(
  ([file, title, caption]) => ({ path: `/brand/${file}.png`, title, caption }),
);

/** Path of the brand / press-kit page that hosts these assets. */
export const BRAND_PAGE_PATH = "/brand";
