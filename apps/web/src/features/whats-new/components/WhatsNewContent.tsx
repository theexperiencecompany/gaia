"use client";

import DOMPurify from "dompurify";
import { useMemo } from "react";

interface WhatsNewContentProps {
  html: string;
}

/**
 * Injects Tailwind classes directly into raw RSS HTML elements via string
 * injection (not CSS arbitrary variants), since Tailwind's preflight resets
 * ul/ol list-style/padding at higher specificity.
 *
 * Expects the feed's structure: intro <p>, then repeating <h2><a>version</a></h2>
 * blocks (per package) separated by <hr>, each with <h3> sections of <ul><li>.
 */
function injectClasses(html: string): string {
  return (
    html
      // ── h2 version headings (always contain <a href>) ────────
      // Handle h2+a combo first (most specific), converting the anchor too
      .replace(
        /<h2([^>]*)>\s*<a\s/g,
        '<h2 class="mt-5 mb-0.5"><a class="text-[0.8125rem] font-semibold text-zinc-200 underline decoration-zinc-700 underline-offset-4 hover:text-white hover:decoration-zinc-400 transition-colors" ',
      )
      // Any remaining bare h2 (e.g. without anchor)
      .replace(
        /<h2([^>]*)>/g,
        '<h2 class="mt-5 mb-0.5 text-[0.8125rem] font-semibold text-zinc-200">',
      )

      // ── h3 category labels: Features / Bug Fixes / Improvements ──
      .replace(
        /<h3([^>]*)>/g,
        '<h3 class="mt-4 mb-2 font-semibold text-zinc-400">',
      )

      // ── Lists — restore bullet points (Tailwind preflight removes them) ──
      .replace(
        /<ul([^>]*)>/g,
        '<ul class="my-2 space-y-1.5 list-disc pl-4 marker:text-zinc-600">',
      )
      .replace(
        /<ol([^>]*)>/g,
        '<ol class="my-2 space-y-1.5 list-decimal pl-4">',
      )
      .replace(
        /<li([^>]*)>/g,
        '<li class="text-sm text-zinc-400 leading-[1.65] pl-0.5">',
      )

      // ── Bold feature name inside li ───────────────────────────
      .replace(
        /<strong([^>]*)>/g,
        '<strong class="font-semibold text-zinc-200">',
      )

      // ── Paragraphs ────────────────────────────────────────────
      .replace(
        /<p([^>]*)>/g,
        '<p class="my-2.5 text-sm text-zinc-400 leading-relaxed">',
      )

      // ── Horizontal rules (package section separators) ─────────
      .replace(
        /<hr\s*\/?>/g,
        '<hr class="my-5 border-0 border-t border-zinc-800">',
      )

      // ── Inline code ───────────────────────────────────────────
      .replace(
        /<code([^>]*)>/g,
        '<code class="rounded bg-zinc-800 px-1.5 py-0.5 font-mono text-[0.75rem] text-zinc-100">',
      )

      // ── Code blocks ───────────────────────────────────────────
      .replace(
        /<pre([^>]*)>/g,
        '<pre class="my-3 overflow-x-auto rounded-lg border border-zinc-800 bg-zinc-950 p-3 font-mono text-xs text-zinc-300">',
      )

      // ── Links (generic — not h2 anchors, those are already done) ──
      // Original h2 anchors now have class=" before href, so `<a href=` only
      // matches remaining links outside h2.
      .replace(
        /<a href=/g,
        '<a class="text-primary underline decoration-primary/30 underline-offset-[3px] hover:decoration-primary transition-colors" href=',
      )
  );
}

export function WhatsNewContent({ html }: WhatsNewContentProps) {
  const processed = useMemo(() => {
    const sanitized = DOMPurify.sanitize(html, {
      ADD_TAGS: ["img"],
      ADD_ATTR: ["target", "rel"],
    });
    return injectClasses(sanitized);
  }, [html]);

  return (
    <div className="text-sm" dangerouslySetInnerHTML={{ __html: processed }} />
  );
}
