"use client";

import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

export function AppIcon({ id, size = 16 }: { id: string; size?: number }) {
  return (
    <span className="flex shrink-0 items-center justify-center">
      {getToolCategoryIcon(id, {
        size,
        width: size,
        height: size,
        showBackground: false,
      })}
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
