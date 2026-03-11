/**
 * AppIcon — renders any gaia icon component with size + color props.
 */

import type { IconProps } from "@theexperiencecompany/gaia-icons";
import type React from "react";

export type AnyIcon = React.ComponentType<IconProps>;

interface AppIconProps {
  icon: AnyIcon;
  size?: number;
  color?: string;
}

export function AppIcon({ icon, size = 24, color = "#ffffff" }: AppIconProps) {
  const Icon = icon;
  return <Icon size={size} color={color} />;
}
