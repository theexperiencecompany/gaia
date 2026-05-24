---
description: SEO rules for Next.js metadata, page titles, structured data, programmatic SEO, sitemaps, hreflang, and OG images
paths:
  - "apps/web/src/app/**/*.tsx"
  - "apps/web/src/app/**/*.ts"
  - "apps/web/src/lib/seo.ts"
  - "apps/web/src/utils/seoUtils.ts"
---

# SEO Rules

Full reference infrastructure lives in:
- `apps/web/src/lib/seo.ts` — siteConfig, 19 schema generators, `generatePageMetadata()`
- `apps/web/src/utils/seoUtils.ts` — blog/use-case metadata helpers
- `apps/web/src/lib/sitemapData.ts` — 11-part sitemap architecture
- `apps/web/src/i18n/getAlternates.ts` — hreflang helpers

---

## Page Titles

The root layout (`apps/web/src/app/layout.tsx`) defines:

```typescript
title: { template: `%s | GAIA` }
```

**Never include "GAIA" or "| GAIA" in a page's own title string** — it renders as `Page | GAIA | GAIA`.

```typescript
// Wrong — "Features — GAIA | GAIA"
export const metadata = { title: "Features — GAIA" };

// Wrong — "AI Chief of Staff | GAIA | GAIA"
export const metadata = { title: "AI Chief of Staff | GAIA" };

// Correct — "Features | GAIA"
export const metadata = { title: "Features" };

// Correct — "AI Chief of Staff — Your Proactive AI | GAIA"
export const metadata = { title: "AI Chief of Staff — Your Proactive AI" };
```

This applies to both static `export const metadata` objects and dynamic `generateMetadata()` functions — strip `| GAIA` from any returned title string.

**Title formatting:**
- Lead with the most descriptive keyword, not the brand name
- Use em-dash `—` (not pipe `|`) to separate primary topic from subtitle
- Keep under 60 characters where possible
- No trailing punctuation

---

## Meta Descriptions

- 120–155 characters
- Describe what the page *does*, not what the product *is*
- Do not repeat the title verbatim
- End with a benefit or differentiator

---

## Always Use `generatePageMetadata()` for New Pages

`lib/seo.ts` exports `generatePageMetadata()` — use it instead of building metadata objects by hand. It handles OG, Twitter, canonical, noIndex, article timestamps, and authors in one call:

```typescript
import { generatePageMetadata } from "@/lib/seo";

export async function generateMetadata(): Promise<Metadata> {
  return generatePageMetadata({
    title: "My Page Title",
    description: "What this page does in 120–155 chars.",
    path: "/my-page",
    keywords: ["relevant", "keyword", "list"],
  });
}
```

Never construct `openGraph` or `twitter` metadata blocks manually — `generatePageMetadata()` already does this correctly and consistently.

---

## Structured Data (JSON-LD)

`lib/seo.ts` exports 19 typed schema generators. Use them — never write raw JSON-LD objects inline.

| Need | Generator |
|---|---|
| Any new page | `generateWebPageSchema()` |
| FAQ section | `generateFAQSchema()` + render `<FAQAccordion>` |
| How-to / steps | `generateHowToSchema()` |
| Blog post | `generateArticleSchema()` |
| List of items | `generateItemListSchema()` |
| Glossary term | `generateDefinedTermSchema()` |
| Product/app | `generateProductSchema()` |
| Breadcrumbs | `generateBreadcrumbSchema()` |

Render schemas with `<JsonLd>` from `components/seo/JsonLd.tsx`. Every programmatic page should have at minimum a `WebPageSchema` and a `BreadcrumbSchema`.

```typescript
import JsonLd from "@/components/seo/JsonLd";
import { generateBreadcrumbSchema, generateWebPageSchema } from "@/lib/seo";

// In the page component (Server Component):
<JsonLd
  schema={[
    generateWebPageSchema({ title, description, url }),
    generateBreadcrumbSchema([
      { name: "Home", url: "/" },
      { name: "Features", url: "/features" },
      { name: feature.title, url: `/features/${slug}` },
    ]),
  ]}
/>
```

---

## Programmatic SEO Pages (`generateStaticParams` + `generateMetadata`)

Every `[slug]` route must implement both:

```typescript
export async function generateStaticParams() {
  const items = await fetchAllItems();
  return items.map((item) => ({ slug: item.slug }));
}

export async function generateMetadata({ params }): Promise<Metadata> {
  const item = await getItem(params.slug);
  if (!item) return {};
  return generatePageMetadata({
    title: item.title,
    description: item.description,
    path: `/section/${params.slug}`,
    keywords: [item.name, item.category, ...commonKeywords],
  });
}
```

**For integration/marketplace pages:**
- Use `revalidate = 60` (ISR) since content is API-driven
- Set `dynamicParams = true` to allow fallback rendering for new slugs
- Generate category-specific title and description templates (see `marketplace/[slug]/page.tsx` for the pattern)
- Always include a `SoftwareApplication` schema, HowTo schema, and FAQ schema

**Canonical URLs:**
- Use `getCanonicalUrl(path)` from `lib/seo.ts` — never construct URLs manually
- For near-duplicate pages (glossary terms, synonym slugs), set `canonicalPath` to the primary slug

---

## Hreflang / Internationalization

Translated pages (anything under `[locale]/`) that have content in all 7 locales must include `alternates.languages`:

```typescript
import { getAlternates } from "@/i18n/getAlternates";

export async function generateMetadata({ params }) {
  return {
    ...generatePageMetadata({ title, description, path }),
    alternates: {
      canonical: `/my-page`,
      languages: getAlternates("/my-page"),
    },
  };
}
```

**Translated (needs hreflang):** `/compare`, `/alternative-to`, `/automate`, `/for`, `/learn`, `/use-cases`

**Untranslated (English only — no hreflang):** `/marketplace`, `/blog`, `/download`, `/login`, `/signup`, `/terms`, `/privacy`

---

## Sitemaps

The sitemap system has 11 named segments (`lib/sitemapData.ts`). When adding new content types:

1. Add a new sitemap ID and handler in `sitemapData.ts`
2. Add the route to `app/sitemap/[id]/route.ts`
3. Set appropriate `priority` and `changefreq`:
   - Homepage: `1.0` / `daily`
   - Core feature/product pages: `0.9` / `weekly`
   - Blog posts: `0.8` / `weekly` (update `lastmod` from post date)
   - Static informational pages: `0.7–0.8` / `monthly`
   - Legal/auth: `0.4–0.6` / `monthly`
4. Use `withLocaleUrls()` for translated pages to include all language variants

---

## OG Images

Dynamic OG images live in `app/api/og/`. When adding a new section with programmatic pages:

1. Create `app/api/og/[section]/route.tsx` using `next/og` (edge runtime)
2. Reference it in `generateMetadata()`:
   ```typescript
   openGraph: {
     images: [`/api/og/my-section?slug=${params.slug}`],
   }
   ```
3. Always provide a 1200×630 fallback if the route fails
4. Preload the wallpaper and Inter font — see existing OG routes for the pattern

---

## FAQ Pages

Any page with an FAQ section should:
1. Render `<FAQAccordion faqs={feature.faqs} />` for the visible UI
2. Inject `generateFAQSchema(feature.faqs)` via `<JsonLd>` for rich snippets
3. Have at least 3 questions. Google won't show the rich snippet for fewer.

---

## noIndex

Use `generatePageMetadata({ noIndex: true })` for:
- Auth pages (`/login`, `/signup`, `/verify-email`)
- Internal/dashboard pages
- Thank-you / success pages
- Any page with `?q=` or pagination query params that duplicate content

Never set `noIndex` on public marketing or programmatic SEO pages.
