import { IntegrationIcon } from "@/features/integrations/components/IntegrationIcon";
import type { ComboApp } from "@/features/integrations/lib/comboApps";
import { appIconUrl } from "@/features/integrations/lib/comboApps";

const ICON_SIZE = 28;
const TILT_DEGREES = 9;

/** One app's logo, from the icon catalog or else its site's favicon. */
export function ComboAppIcon({
  app,
  size = ICON_SIZE,
}: {
  readonly app: ComboApp;
  readonly size?: number;
}) {
  return (
    <IntegrationIcon
      integrationId={app.slug}
      iconUrl={appIconUrl(app.slug)}
      size={size}
    />
  );
}

/** A combo's two app logos, tilted apart and overlapping like the site's other icon stacks. */
export function ComboAppIcons({
  apps,
}: {
  readonly apps: readonly [ComboApp, ComboApp];
}) {
  return (
    <span className="flex shrink-0 items-center -space-x-2">
      {apps.map((app, index) => (
        <span
          key={app.slug}
          className="relative flex items-center justify-center"
          style={{
            rotate: `${index === 0 ? -TILT_DEGREES : TILT_DEGREES}deg`,
            zIndex: apps.length - index,
          }}
        >
          <ComboAppIcon app={app} />
        </span>
      ))}
    </span>
  );
}
