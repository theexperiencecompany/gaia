import { ComputerIcon, PackageOpenIcon } from "@icons";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { DEVICE_INTEGRATION_CATEGORY } from "../constants/categories";

interface IntegrationIconProps {
  integrationId: string;
  iconUrl?: string | null;
  size?: number;
  showBackground?: boolean;
  /** Integration category; drives the fallback glyph (a device server gets the
   * computer icon rather than the generic package). */
  category?: string;
}

/**
 * The one icon for a tool category or integration, used by the slash menu, tool-call
 * rows, the integrations surfaces and settings. Falls back to a glyph (computer for a
 * device server, else a package) when there is no known icon and no iconUrl.
 */
export function IntegrationIcon({
  integrationId,
  iconUrl,
  size = 28,
  showBackground = false,
  category,
}: IntegrationIconProps) {
  const icon = getToolCategoryIcon(
    integrationId,
    { size, width: size, height: size, showBackground },
    iconUrl,
  );
  if (icon) return <>{icon}</>;

  const FallbackIcon =
    category === DEVICE_INTEGRATION_CATEGORY ? ComputerIcon : PackageOpenIcon;
  const fallback = (
    <FallbackIcon width={size} height={size} className="text-zinc-400" />
  );
  return showBackground ? (
    <div className="flex aspect-square items-center justify-center rounded-lg bg-zinc-700 p-1">
      {fallback}
    </div>
  ) : (
    fallback
  );
}
