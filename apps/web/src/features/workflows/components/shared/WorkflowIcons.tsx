"use client";

import dynamic from "next/dynamic";
import { useWorkflowIconElement } from "./WorkflowIconElements";
import { CustomIconTile, StepCategoryIcons } from "./WorkflowIconParts";

// The 178-icon catalog (~120 KB gzip) loads only for a custom icon no server parent rendered.
const CatalogWorkflowIcons = dynamic(() => import("./CatalogWorkflowIcons"));

interface WorkflowIconsProps {
  steps: Array<{ category: string }>;
  /** User-chosen icon slug — rendered in place of the step-category icons when set */
  icon?: string | null;
  /** Hex color for the user-chosen icon */
  iconColor?: string | null;
  iconSize?: number;
  maxIcons?: number;
  className?: string;
  spacing?: string;
  showBackground?: boolean;
}

/**
 * Displays workflow step category icons with rotated styling.
 * Reusable across UnifiedWorkflowCard and WorkflowsSidebar.
 */
export default function WorkflowIcons({
  steps,
  icon,
  iconColor,
  iconSize = 25,
  maxIcons = 3,
  className = "",
  spacing = "-space-x-1.5 ",
  showBackground = true,
}: WorkflowIconsProps) {
  const serverIcon = useWorkflowIconElement(icon, iconColor, iconSize);
  const categoryProps = {
    steps,
    iconSize,
    maxIcons,
    className,
    spacing,
    showBackground,
  };

  // An explicit icon always wins over step-category icons: gating it on "no
  // integrations" made rendering depend on the auth-gated catalog, flipping icons
  // the moment /integrations/me resolved and behaving differently from the slug page.
  if (serverIcon) {
    return (
      <CustomIconTile
        iconElement={serverIcon}
        iconColor={iconColor}
        className={className}
        showBackground={showBackground}
      />
    );
  }
  if (icon) {
    return (
      <CatalogWorkflowIcons
        icon={icon}
        iconColor={iconColor}
        {...categoryProps}
      />
    );
  }
  return <StepCategoryIcons {...categoryProps} />;
}
