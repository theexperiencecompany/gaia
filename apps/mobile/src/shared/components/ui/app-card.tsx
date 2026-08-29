/**
 * AppCard — GAIA wrapper around heroui-native 1.0.8 Card
 *
 * Migration beta.9 -> 1.0.8: Card API UNCHANGED (Card, Card.Header/Body/Footer/Title/Description)
 * Internals changed: styles moved from tailwind-variants `bg-accent` -> CSS class `card__root--*`
 * No prop renames; Surface variant still "default" | "secondary" | "tertiary" | "transparent"
 * Uniwind + Tailwind 4: @source for heroui-native/lib in global.css ensures new CSS classes are generated.
 *
 * Theme parity: Card inherits Surface tokens which are pinned to GAIA dark tokens in global.css
 * (@layer theme :root dark { --surface, --surface-secondary, --surface-tertiary })
 * Must stay 1:1 with web Card (bg-zinc-800 p-4 rounded-2xl) — mobile uses same radius via design tokens shared.
 *
 * For ToolCard parity with web OpenUI primitives, import toolCardTokens from @gaia/shared/ui/toolCardTokens
 * and keep mx-4/p-4 gap-3 conventions in renderers (see features/chat/tool-data/renderers.tsx).
 */
import { Card } from "heroui-native";
import { cn } from "@/lib/utils";

export { Card };
export type AppCardProps = React.ComponentProps<typeof Card>;
export type AppCardHeaderProps = React.ComponentProps<typeof Card.Header>;
export type AppCardBodyProps = React.ComponentProps<typeof Card.Body>;
export type AppCardFooterProps = React.ComponentProps<typeof Card.Footer>;

/**
 * GAIA-branded card with default GAIA surface styling.
 * Mirrors web `rounded-2xl bg-zinc-800 p-4` but lets heroui-native Surface handle the bg via tokens.
 */
export function AppCard({
  className,
  variant = "secondary",
  ...props
}: AppCardProps) {
  return (
    <Card
      variant={variant}
      className={cn("rounded-2xl", className)}
      {...props}
    />
  );
}
AppCard.Header = Card.Header;
AppCard.Body = Card.Body;
AppCard.Footer = Card.Footer;
AppCard.Title = Card.Title;
AppCard.Description = Card.Description;

/**
 * Usage (1.0.8 — identical to beta.9):
 * <AppCard variant="secondary" className="rounded-2xl bg-surface">
 *   <Card.Body className="p-4 gap-3">
 *     <Card.Title>Title</Card.Title>
 *     <Card.Description>Description</Card.Description>
 *   </Card.Body>
 *   <Card.Footer><AppButton>Action</AppButton></Card.Footer>
 * </AppCard>
 */
