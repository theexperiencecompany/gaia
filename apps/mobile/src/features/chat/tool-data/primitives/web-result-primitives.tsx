import type { NewsResult, WebResult } from "@gaia/shared";
import { useState } from "react";
import { Image, Linking, Pressable, View } from "react-native";
import { AppIcon, Globe02Icon, News01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";

// ---------------------------------------------------------------------------
// Hostname helper — used by every web/news/source primitive
// ---------------------------------------------------------------------------

export function getHostname(url?: string): string {
  if (!url) return "";
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

// ---------------------------------------------------------------------------
// FaviconImage — Google s2 favicon with globe fallback
// Mirrors web's `next/image` favicon with onError → display:none. We render a
// zinc-700 circle behind the favicon so failed loads still match the web
// stacked-circle look.
// ---------------------------------------------------------------------------

interface FaviconImageProps {
  url?: string;
  size?: number;
}

export function FaviconImage({ url, size = 14 }: FaviconImageProps) {
  const [errored, setErrored] = useState(false);
  const hostname = getHostname(url);

  if (!hostname || errored) {
    return (
      <View
        className="rounded-full bg-zinc-700 items-center justify-center"
        style={{ width: size, height: size }}
      >
        <AppIcon
          icon={Globe02Icon}
          size={Math.round(size * 0.65)}
          color="#a1a1aa"
        />
      </View>
    );
  }

  return (
    <Image
      source={{
        uri: `https://www.google.com/s2/favicons?domain=${hostname}&sz=64`,
      }}
      style={{ width: size, height: size, borderRadius: size / 2 }}
      onError={() => setErrored(true)}
    />
  );
}

// ---------------------------------------------------------------------------
// WebResultRow — popover-style web result row used by both search-results
// and deep-research cards.
// Mirrors web's WebResults list item: title (sm font-medium, 1 line), snippet
// (xs foreground-500, 2 lines), favicon + hostname row (xs primary). Bottom
// border per row (zinc-700 / 15% white in dark).
// ---------------------------------------------------------------------------

interface WebResultRowProps {
  result: WebResult;
  isLast?: boolean;
}

export function WebResultRow({ result, isLast = false }: WebResultRowProps) {
  const hostname = getHostname(result.url);
  const description = result.content || result.snippet;

  return (
    <Pressable
      onPress={() => result.url && Linking.openURL(result.url)}
      android_ripple={{ color: "rgba(255,255,255,0.05)", borderless: false }}
      style={{
        paddingHorizontal: 16,
        paddingTop: 16,
        paddingBottom: 12,
        borderBottomWidth: isLast ? 0 : 1,
        borderBottomColor: "rgba(228,228,231,0.15)",
      }}
    >
      <View className="gap-1">
        <Text className="text-zinc-100 text-sm font-medium" numberOfLines={1}>
          {result.title || hostname || "Untitled"}
        </Text>

        {!!description && (
          <Text className="text-zinc-400 text-xs" numberOfLines={2}>
            {description}
          </Text>
        )}

        {!!hostname && (
          <View className="flex-row items-center gap-2 mt-1">
            <FaviconImage url={result.url} size={14} />
            <Text className="text-[#00bbff] text-xs" numberOfLines={1}>
              {hostname}
            </Text>
          </View>
        )}
      </View>
    </Pressable>
  );
}

// ---------------------------------------------------------------------------
// NewsResultCard — full-bleed bg-zinc-800 cards stacked vertically
// Mirrors web's NewsResults: rounded-lg bg-zinc-800 p-4, news icon + title
// (text-lg font-medium, truncated 1 line, primary color), 2-line content
// snippet (sm foreground-700), score line.
// ---------------------------------------------------------------------------

interface NewsResultCardProps {
  article: NewsResult;
}

export function NewsResultCard({ article }: NewsResultCardProps) {
  return (
    <Pressable
      onPress={() => article.url && Linking.openURL(article.url)}
      android_ripple={{ color: "rgba(255,255,255,0.05)", borderless: false }}
      style={{
        backgroundColor: "#27272a", // zinc-800
        borderRadius: 8,
        padding: 16,
      }}
    >
      <View className="flex-row items-center gap-2 mb-1">
        <AppIcon icon={News01Icon} size={20} color="#00bbff" />
        <Text
          className="text-[#00bbff] text-lg font-medium flex-1"
          numberOfLines={1}
        >
          {article.title || "Untitled"}
        </Text>
      </View>

      {!!article.content && (
        <Text className="text-zinc-300 text-sm mb-1" numberOfLines={2}>
          {article.content}
        </Text>
      )}

      {typeof article.score === "number" && (
        <Text className="text-zinc-500 text-xs">
          Score: {article.score.toFixed(2)}
        </Text>
      )}
    </Pressable>
  );
}
