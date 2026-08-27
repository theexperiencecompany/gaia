// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

// Every tool category the API's registry serves today, as returned by
// GET /api/v1/tools. `billing` shipped with no entry in toolIconConfigs, so
// getToolCategoryIcon returned null and its rows and category tab rendered with
// no icon at all — nothing failed, it just looked broken. Adding a category
// backend-side without an icon is the recurring shape of that bug.
//
// Keep this list in step with `_add_category(...)` in
// apps/api/app/agents/tools/core/registry.py.
const BUILTIN_TOOL_CATEGORIES = [
  "billing",
  "context",
  "creative",
  "documents",
  "integrations",
  "manual",
  "memory",
  "notifications",
  "posthog",
  "reminders",
  "search",
  "skills",
  "support",
  "todos",
  "tracked_todos",
  "weather",
  "workflows",
];

describe("tool category icons", () => {
  it.each(BUILTIN_TOOL_CATEGORIES)(
    "resolves an icon for the %s category",
    (category) => {
      // null is the "no config and no iconUrl fallback" return — the dropdown
      // renders nothing at all for it.
      expect(getToolCategoryIcon(category)).not.toBeNull();
    },
  );

  it("returns null for a category that genuinely has no icon and no url", () => {
    // Pins the failure mode above: this is what an unconfigured category does,
    // so the assertions in the first test cannot pass vacuously.
    expect(getToolCategoryIcon("definitely_not_a_real_category")).toBeNull();
  });
});
