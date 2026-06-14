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

export const BRAND_IMAGE_ASSETS: readonly BrandImageAsset[] = [
  {
    path: "/brand/gaia_logo.png",
    title: "GAIA Logo",
    caption: "The primary GAIA brand mark",
  },
  {
    path: "/brand/gaia_wordmark_black.png",
    title: "GAIA Wordmark (Black)",
    caption: "GAIA wordmark for light backgrounds",
  },
  {
    path: "/brand/gaia_wordmark_white.png",
    title: "GAIA Wordmark (White)",
    caption: "GAIA wordmark for dark backgrounds",
  },
  {
    path: "/brand/experience_logo_black.png",
    title: "The Experience Company Logo (Black)",
    caption: "The Experience Company brand mark for light backgrounds",
  },
  {
    path: "/brand/experience_logo_white.png",
    title: "The Experience Company Logo (White)",
    caption: "The Experience Company brand mark for dark backgrounds",
  },
  {
    path: "/brand/experience_wordmark_black.png",
    title: "Experience Wordmark (Black)",
    caption: "Experience wordmark for light backgrounds",
  },
  {
    path: "/brand/experience_wordmark_white.png",
    title: "Experience Wordmark (White)",
    caption: "Experience wordmark for dark backgrounds",
  },
  {
    path: "/brand/experience_full_wordmark_black.png",
    title: "The Experience Company Full Wordmark (Black)",
    caption: "Complete The Experience Company wordmark for light backgrounds",
  },
  {
    path: "/brand/experience_full_wordmark_white.png",
    title: "The Experience Company Full Wordmark (White)",
    caption: "Complete The Experience Company wordmark for dark backgrounds",
  },
] as const;

/** Path of the brand / press-kit page that hosts these assets. */
export const BRAND_PAGE_PATH = "/brand";
