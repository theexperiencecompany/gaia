/**
 * AppIcon — renders any gaia icon component with size + color props.
 */

import type { IconProps } from "@icons";
import type React from "react";

export type AnyIcon = React.ComponentType<IconProps>;

interface AppIconProps extends IconProps {
  icon: AnyIcon;
}

export function AppIcon({ icon, ...props }: AppIconProps) {
  const Icon = icon;
  return <Icon {...props} />;
}
