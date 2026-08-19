import Image from "next/image";
import {
  BOT_PLATFORM_ICONS,
  BOT_PLATFORM_LABELS,
  BOT_PLATFORMS,
  type BotPlatform,
} from "@/config/botPlatforms";

const PLATFORM_BY_LABEL = new Map<string, BotPlatform>(
  BOT_PLATFORMS.map((platform) => [BOT_PLATFORM_LABELS[platform], platform]),
);

const PLATFORM_PATTERN = new RegExp(
  [...PLATFORM_BY_LABEL.keys()].join("|"),
  "g",
);

interface PlatformToken {
  platform: BotPlatform;
  at: number;
}

function tokenize(feature: string): {
  segments: string[];
  platforms: PlatformToken[];
} {
  const segments: string[] = [];
  const platforms: PlatformToken[] = [];
  let cursor = 0;

  for (const match of feature.matchAll(PLATFORM_PATTERN)) {
    const platform = PLATFORM_BY_LABEL.get(match[0]);
    if (platform === undefined || match.index === undefined) continue;
    segments.push(feature.slice(cursor, match.index));
    platforms.push({ platform, at: match.index });
    cursor = match.index + match[0].length;
  }
  segments.push(feature.slice(cursor));

  return { segments, platforms };
}

function PlatformMention({ platform }: { platform: BotPlatform }) {
  return (
    <span className="inline-flex items-center gap-1 whitespace-nowrap align-middle">
      <Image
        src={BOT_PLATFORM_ICONS[platform]}
        alt=""
        width={16}
        height={16}
        aria-hidden
        className="inline-block h-4 w-4 shrink-0 rounded-[4px]"
      />
      {BOT_PLATFORM_LABELS[platform]}
    </span>
  );
}

export function PlanFeature({ feature }: { feature: string }) {
  const { segments, platforms } = tokenize(feature);

  if (platforms.length === 0) {
    return <span className="whitespace-nowrap text-zinc-300">{feature}</span>;
  }

  return (
    <span className="text-zinc-300">
      {segments[0]}
      {platforms.map(({ platform, at }, index) => (
        <span key={`${platform}-${at}`}>
          <PlatformMention platform={platform} />
          {segments[index + 1]}
        </span>
      ))}
    </span>
  );
}
