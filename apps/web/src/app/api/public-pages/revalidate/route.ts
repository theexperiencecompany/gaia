import { revalidatePath } from "next/cache";

import { carriesInternalToken } from "@/lib/internalApiHeaders";
import { isPublicPageDomain, PUBLIC_PAGE_ROUTES } from "@/lib/publicPages";

async function readDomain(request: Request): Promise<unknown> {
  try {
    const body: unknown = await request.json();
    return typeof body === "object" && body !== null && "domain" in body
      ? body.domain
      : undefined;
  } catch (error) {
    if (error instanceof SyntaxError) return undefined;
    throw error;
  }
}

/**
 * Clear the cached public pages that show the data the API says changed
 * (apps/api/app/services/public_pages.py). Each page rebuilds on its next visit.
 */
export async function POST(request: Request): Promise<Response> {
  if (!carriesInternalToken(request.headers)) {
    return Response.json(
      { message: "INTERNAL_API_TOKEN is missing or wrong" },
      { status: 401 },
    );
  }
  const domain = await readDomain(request);
  if (!isPublicPageDomain(domain)) {
    return Response.json(
      { message: "The body names no data a cached public page shows" },
      { status: 400 },
    );
  }
  const routes = PUBLIC_PAGE_ROUTES[domain];
  for (const { route, type } of routes) revalidatePath(route, type);
  return Response.json({ revalidated: routes });
}
