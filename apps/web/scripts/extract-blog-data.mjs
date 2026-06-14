#!/usr/bin/env node
/**
 * extract-blog-data.mjs — build-time codegen for blog posts.
 *
 * The blog used to read markdown straight off the filesystem at runtime
 * (`fs.readdirSync(process.cwd()/content/blog)`). That works on Node/Vercel but
 * FAILS on Cloudflare Workers (no fs at request time), so the blog sitemap shard
 * came back empty and `/blog/[slug]` pages broke on cf.
 *
 * This emits the same `public/data/{feature}/…` shape every other static feature
 * (comparisons, alternatives, …) uses, so `src/lib/blog.ts` can load posts via
 * `@/lib/feature-data` (fs at build, the Cloudflare ASSETS binding at runtime).
 *
 * Output: public/data/blog/_slugs.json + public/data/blog/{slug}.json
 */
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import matter from "gray-matter";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const CONTENT_DIR = join(root, "content/blog");
const OUT_DIR = join(root, "public/data/blog");
const EXCLUDE = new Set(["README", "TEMPLATE"]);

if (!existsSync(CONTENT_DIR)) {
  console.error(`[extract-blog] content dir missing: ${CONTENT_DIR}`);
  process.exit(1);
}

const files = readdirSync(CONTENT_DIR).filter(
  (f) => (f.endsWith(".mdx") || f.endsWith(".md")) && !EXCLUDE.has(f.replace(/\.(mdx|md)$/, "")),
);

// Rebuild the output dir from scratch so deleted posts don't linger.
rmSync(OUT_DIR, { recursive: true, force: true });
mkdirSync(OUT_DIR, { recursive: true });

const slugs = [];
const seenSlugs = new Set();
for (const file of files) {
  const raw = readFileSync(join(CONTENT_DIR, file), "utf8");
  const { data, content } = matter(raw);
  const slug = data.slug || file.replace(/\.(mdx|md)$/, "");
  if (seenSlugs.has(slug)) {
    console.error(`[extract-blog] duplicate slug "${slug}" from ${file}`);
    process.exit(1);
  }
  seenSlugs.add(slug);
  const post = {
    slug,
    title: data.title,
    date: data.date,
    authors: data.authors,
    category: data.category,
    image: data.image,
    content,
    featured: data.featured ?? false,
  };
  writeFileSync(join(OUT_DIR, `${slug}.json`), JSON.stringify(post));
  slugs.push(slug);
}

slugs.sort((a, b) => a.localeCompare(b));
writeFileSync(join(OUT_DIR, "_slugs.json"), JSON.stringify(slugs));
console.log(`[extract-blog] wrote ${slugs.length} posts -> public/data/blog/`);
