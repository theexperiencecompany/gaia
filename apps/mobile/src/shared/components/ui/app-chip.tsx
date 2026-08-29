/**
 * AppChip — GAIA wrapper around heroui-native 1.0.8 Chip
 *
 * Migration beta.9 -> 1.0.8:
 * - Props `variant` ("primary" | "secondary" | "tertiary" | "soft") and `color` ("accent" | "default" | "success" | "warning" | "danger") UNCHANGED
 * - New `background` prop (like Button) for glass theme — defaults to theme layer for default-colored surfaces
 * - New sub-component `Chip.Background` (absolute-fill behind surface, clipped by overflow) — use only for custom glass/gradient chips
 * - Style internals: tailwind-variants -> CSS class chip__root--variant-* (no consumer change)
 * - `animation="disable-all"` still supported (common in GAIA chips for static pills)
 *
 * Theme parity: Chip colors map to heroui-native tokens pinned to GAIA brand in global.css
 * (--accent => #00bbff). Web parity: web Chip variant flat/color maps to mobile soft/accent.
 *
 * Uniwind: className strings remain tailwind-merge compatible; heroui-native 1.0.8 still uses tailwind-variants ^3.2.2 + uniwind ^1.10.0
 */
import { Chip } from "heroui-native";
import { cn } from "@/lib/utils";

export { Chip };
export type AppChipProps = React.ComponentProps<typeof Chip>;

export function AppChip({
  className,
  variant = "soft",
  color = "default",
  animation,
  ...props
}: AppChipProps) {
  return (
    <Chip
      variant={variant}
      color={color}
      animation={animation}
      className={cn(className)}
      {...props}
    />
  );
}
AppChip.Label = Chip.Label;
// New in 1.0.8 — re-export if present (type-safe optional)
export const AppChipBackground = (
  Chip as unknown as { Background?: typeof Chip }
).Background;

/**
 * GAIA semantic helpers — mirror web HeroUI Chip tones
 */
export function StatusChip({
  tone = "default",
  variant = "soft",
  ...props
}: Omit<AppChipProps, "color" | "variant"> & {
  tone?: AppChipProps["color"];
  variant?: AppChipProps["variant"];
}) {
  return (
    <Chip color={tone} variant={variant} animation="disable-all" {...props} />
  );
}

/**
 * Usage (1.0.8):
 * <Chip size="sm" variant="soft" color="success" animation="disable-all"><Chip.Label>Connected</Chip.Label></Chip>
 * <Chip size="sm" variant="soft" color="accent"><Chip.Label>New</Chip.Label></Chip>
 * // New glass background (1.0.8):
 * <Chip background={<Chip.Background />} variant="secondary">Glass</Chip>
 */
