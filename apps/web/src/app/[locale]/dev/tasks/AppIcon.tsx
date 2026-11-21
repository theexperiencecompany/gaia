"use client";

import { toolFaviconUrl } from "@/data/tools";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

/** An app's logo by its integration id, or a site's icon by its host. */
export function AppIcon({
  id,
  site,
  size = 16,
}: {
  id?: string;
  site?: string;
  size?: number;
}) {
  return (
    <span className="flex shrink-0 items-center justify-center">
      {getToolCategoryIcon(
        id ?? site ?? "",
        {
          size,
          width: size,
          height: size,
          showBackground: false,
        },
        site && !id ? toolFaviconUrl(site) : undefined,
      )}
    </span>
  );
}

export function IntegrationStack({
  ids,
  size = 16,
}: {
  ids: string[];
  size?: number;
}) {
  if (ids.length === 0) return null;
  return (
    <span className="flex items-center gap-1.5">
      {ids.map((id) => (
        <AppIcon key={id} id={id} size={size} />
      ))}
    </span>
  );
}
