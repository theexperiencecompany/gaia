import { readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { TOOL_FIXTURES } from "@gaia/shared/chat";

/** What a surface renders, which decides its viewport and capture mode. */
export type SurfaceGroup = "tool-card" | "openui" | "landing" | "app";

export interface Surface {
  id: string;
  group: SurfaceGroup;
  path: string;
}

const APP_DIR = join(import.meta.dirname, "..", "..", "src", "app", "[locale]");

// Auth and checkout hand-offs render a redirect or an external widget, not our UI.
const SKIPPED_LANDING_ROUTES = new Set([
  "desktop-login",
  "login",
  "signup",
  "payment",
  "thanks",
]);

/** Every static `page.tsx` route under a route group, as URL paths; dynamic segments are skipped. */
function staticRoutes(routeGroup: string): string[] {
  const root = join(APP_DIR, routeGroup);
  const routes: string[] = [];
  const walk = (dir: string): void => {
    for (const entry of readdirSync(dir)) {
      const full = join(dir, entry);
      if (statSync(full).isDirectory()) {
        if (!entry.startsWith("[") && !entry.startsWith("_")) walk(full);
      } else if (entry === "page.tsx") {
        // Route groups like `(auth)` shape the tree, not the URL.
        const segments = relative(root, dir)
          .split(sep)
          .filter((segment) => segment && !segment.startsWith("("));
        routes.push(`/${segments.join("/")}`);
      }
    }
  };
  walk(root);
  return routes.sort();
}

function toId(group: SurfaceGroup, path: string): string {
  const slug = path.replace(/^\/+/, "").replaceAll("/", "__") || "home";
  return `${group}--${slug}`;
}

/**
 * The surfaces the visual diff captures, derived from the HEAD checkout so
 * base and head runs walk an identical list. A surface base cannot render
 * shows up as a missing baseline, not as a silent skip.
 */
export function collectSurfaces(includeApp: boolean): Surface[] {
  const surfaces: Surface[] = [
    ...TOOL_FIXTURES.map((fixture) => ({
      group: "tool-card" as const,
      path: `/dev/tool-gallery/${fixture.toolName}`,
    })),
    { group: "openui" as const, path: "/dev/openui-samples" },
    ...staticRoutes("(landing)")
      .filter((path) => !SKIPPED_LANDING_ROUTES.has(path.split("/")[1]))
      .map((path) => ({ group: "landing" as const, path })),
    ...(includeApp
      ? staticRoutes("(main)").map((path) => ({
          group: "app" as const,
          path,
        }))
      : []),
  ].map((surface) => ({ ...surface, id: toId(surface.group, surface.path) }));
  return surfaces;
}
