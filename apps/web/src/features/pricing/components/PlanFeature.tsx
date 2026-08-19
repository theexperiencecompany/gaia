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

const SEPARATOR_ONLY = /^[\s,]*(?:&|and)?[\s,]*$/;

interface PlatformRun {
  platforms: BotPlatform[];
  at: number;
}

function parseFeature(feature: string): {
  segments: string[];
  runs: PlatformRun[];
} {
  const segments: string[] = [];
  const runs: PlatformRun[] = [];
  let cursor = 0;

  for (const match of feature.matchAll(PLATFORM_PATTERN)) {
    const platform = PLATFORM_BY_LABEL.get(match[0]);
    if (platform === undefined || match.index === undefined) continue;

    const gap = feature.slice(cursor, match.index);
    const previous = runs.at(-1);
    if (previous !== undefined && SEPARATOR_ONLY.test(gap)) {
      previous.platforms.push(platform);
    } else {
      segments.push(gap);
      runs.push({ platforms: [platform], at: match.index });
    }
    cursor = match.index + match[0].length;
  }
  segments.push(feature.slice(cursor));

  return { segments, runs };
}

interface PlatformIconsProps {
  platforms: BotPlatform[];
}

function PlatformIcons({ platforms }: PlatformIconsProps) {
  const label = platforms.map((p) => BOT_PLATFORM_LABELS[p]).join(", ");

  if (platforms.length === 1) {
    const platform = platforms[0];
    return (
      <span className="inline-flex items-center gap-1.5 whitespace-nowrap align-middle">
        <Image
          src={BOT_PLATFORM_ICONS[platform]}
          alt=""
          width={18}
          height={18}
          aria-hidden
          className="inline-block size-[18px] shrink-0 rounded-[5px]"
        />
        {BOT_PLATFORM_LABELS[platform]}
      </span>
    );
  }

  return (
    <span
      role="img"
      aria-label={label}
      title={label}
      className="mx-1 inline-flex items-center gap-1 align-middle"
    >
      {platforms.map((platform) => (
        <Image
          key={platform}
          src={BOT_PLATFORM_ICONS[platform]}
          alt=""
          width={22}
          height={22}
          aria-hidden
          className="size-[22px] shrink-0 rounded-[6px]"
        />
      ))}
    </span>
  );
}

interface PlanFeatureProps {
  feature: string;
}

export function PlanFeature({ feature }: PlanFeatureProps) {
  const { segments, runs } = parseFeature(feature);

  if (runs.length === 0) {
    return <span className="whitespace-nowrap text-zinc-300">{feature}</span>;
  }

  return (
    <span className="text-zinc-300">
      {segments[0]}
      {runs.map(({ platforms, at }, index) => (
        <span key={at}>
          <PlatformIcons platforms={platforms} />
          {segments[index + 1]}
        </span>
      ))}
    </span>
  );
}
