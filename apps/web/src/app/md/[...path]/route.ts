/**
 * GET /<path>.md — the markdown variant of a marketing page, for agents.
 *
 * Reached through the `/:path+.md` rewrite in next.config.mjs; a separate URL
 * rather than Accept negotiation, so Cloudflare's edge cache (which does not
 * key on Vary) can never hand markdown to a browser. Not indexed: it points
 * search engines at its HTML page as the canonical.
 */

import { MARKDOWN_CONTENT_TYPE } from "@/lib/pageMarkdown/markdown";
import { getPageMarkdown } from "@/lib/pageMarkdown/pageMarkdown";

export const revalidate = 3600;

interface RouteContext {
  readonly params: Promise<{ readonly path: string[] }>;
}

export async function GET(
  _request: Request,
  { params }: RouteContext,
): Promise<Response> {
  const page = await getPageMarkdown((await params).path);
  if (!page) {
    return new Response("Not found\n", {
      status: 404,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  }
  return new Response(page.body, {
    status: 200,
    headers: {
      "Content-Type": MARKDOWN_CONTENT_TYPE,
      "X-Robots-Tag": "noindex",
      Link: `<${page.canonicalUrl}>; rel="canonical"`,
    },
  });
}
