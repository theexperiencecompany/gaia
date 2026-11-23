"use client";

import { WORKFLOW_ICON_MAP } from "../../constants/workflowIconCatalog";
import {
  CustomIconTile,
  StepCategoryIcons,
  type StepCategoryIconsProps,
} from "./WorkflowIconParts";

/** A custom icon resolved from the full client catalog; loaded only where no server parent rendered it. */
export default function CatalogWorkflowIcons({
  icon,
  iconColor,
  ...categoryProps
}: StepCategoryIconsProps & { icon: string; iconColor?: string | null }) {
  const def = WORKFLOW_ICON_MAP.get(icon);
  if (!def) return <StepCategoryIcons {...categoryProps} />;
  return (
    <CustomIconTile
      iconElement={
        <def.Icon
          size={categoryProps.iconSize}
          style={iconColor ? { color: iconColor } : undefined}
        />
      }
      iconColor={iconColor}
      className={categoryProps.className}
      showBackground={categoryProps.showBackground}
    />
  );
}
