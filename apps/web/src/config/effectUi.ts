/**
 * The `?effect=1` branches are a migration preview, not a production surface.
 * They stay enabled in development, and require an explicit flag in a built app.
 */
export const EFFECT_UI_ENABLED =
  process.env.NEXT_PUBLIC_EFFECT_UI === "1" ||
  process.env.NODE_ENV !== "production";
