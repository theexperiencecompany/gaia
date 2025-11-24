import { type NextRequest, NextResponse } from "next/server";

export function middleware(request: NextRequest) {
  // Check if the request is for the notes page or any of its subpaths
  if (request.nextUrl.pathname.startsWith("/notes")) {
    // Redirect to the not-found page which shows a user-friendly 404 page
    return NextResponse.rewrite(new URL("/not-found", request.url));
  }

  return NextResponse.next();
}

// Configure matcher to run the middleware only on specific paths
export const config = {
  matcher: ["/notes", "/notes/:path*"],
};
