import type { ReactNode } from "react";
import type { WorkflowIconElements } from "../components/shared/WorkflowIconElements";
import { WORKFLOW_ICON_MAP } from "../constants/workflowIconCatalog";
import {
  WORKFLOW_CARD_ICON_SIZE,
  workflowIconKey,
} from "../constants/workflowIconStyle";

/** One catalog icon rendered on the server; undefined for a slug the catalog does not have. */
export function workflowIconElement(
  icon: string | null | undefined,
  iconColor: string | null | undefined,
  size: number,
): ReactNode | undefined {
  const def = icon ? WORKFLOW_ICON_MAP.get(icon) : undefined;
  if (!def) return undefined;
  return (
    <def.Icon
      size={size}
      style={iconColor ? { color: iconColor } : undefined}
    />
  );
}

/** Render, on the server, the catalog icons these workflows use, so the client never loads the catalog. */
export function workflowIconElements(
  workflows: ReadonlyArray<{
    readonly icon?: string | null;
    readonly icon_color?: string | null;
  }>,
  size: number = WORKFLOW_CARD_ICON_SIZE,
): WorkflowIconElements {
  const elements: Record<string, ReactNode> = {};
  for (const { icon, icon_color } of workflows) {
    if (!icon) continue;
    const key = workflowIconKey(icon, icon_color);
    if (key in elements) continue;
    const element = workflowIconElement(icon, icon_color, size);
    if (element) elements[key] = element;
  }
  return { size, elements };
}
