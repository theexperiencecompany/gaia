import type { BotPlatform } from "@/config/botPlatforms";
import { PLATFORM_GLYPHS } from "./platformGlyphs";

/** A messaging platform's brand mark, drawn from its art in platformGlyphs. */
export function PlatformGlyph({
  platform,
  className,
}: {
  platform: BotPlatform;
  className?: string;
}) {
  const art = PLATFORM_GLYPHS[platform];
  return (
    <svg viewBox={art.viewBox} className={className} fill={art.fill} role="img">
      <title>{art.title}</title>
      {art.paths.map((p) => (
        <path key={p.d.slice(0, 24)} d={p.d} fill={p.fill} />
      ))}
    </svg>
  );
}
