import type {
  ImageResult,
  NewsResult,
  SearchResults,
  WebResult,
} from "@gaia/shared";
import { useEffect, useState } from "react";
import { Image, Linking, Pressable, View } from "react-native";
import Animated, {
  FadeInRight,
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withSequence,
  withTiming,
} from "react-native-reanimated";
import {
  AppIcon,
  ArrowRight01Icon,
  Globe02Icon,
  News01Icon,
  Search01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  ToolCardHeader,
  ToolCardInner,
  ToolCardShell,
} from "@/features/chat/tool-data/primitives";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getHostname(url?: string): string {
  if (!url) return "";
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

// ---------------------------------------------------------------------------
// Favicon image with globe fallback
// ---------------------------------------------------------------------------

function FaviconImage({ url, size = 14 }: { url?: string; size?: number }) {
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
          size={Math.round(size * 0.7)}
          color="#71717a"
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
// Sources pill — stacked favicons + "Search Results" label
// Mirrors web's SourcesButton: flat rounded-full button with overlapping
// favicon circles, toggles an inline web results list on press.
// ---------------------------------------------------------------------------

function SourcesPill({
  web,
  expanded,
  onToggle,
}: {
  web: WebResult[];
  expanded: boolean;
  onToggle: () => void;
}) {
  const previewFavicons = web.slice(0, 4);

  return (
    <Pressable
      onPress={onToggle}
      className="self-start flex-row items-center gap-2 px-3 py-1.5 rounded-full bg-zinc-700 active:bg-zinc-600"
      android_ripple={{ color: "rgba(255,255,255,0.08)", borderless: false }}
    >
      {/* Overlapping favicon circles — mirrors web's -space-x-3 */}
      <View className="flex-row">
        {previewFavicons.map((result, index) => (
          <View
            key={(result.url ?? "") + (result.title ?? index)}
            style={{
              marginLeft: index === 0 ? 0 : -8,
              width: 20,
              height: 20,
              borderRadius: 10,
              backgroundColor: "#3f3f46",
              borderWidth: 2,
              borderColor: "#27272a",
              alignItems: "center",
              justifyContent: "center",
              overflow: "hidden",
            }}
          >
            <FaviconImage url={result.url} size={16} />
          </View>
        ))}
      </View>
      <Text className="text-zinc-300 text-xs font-medium">
        {expanded ? "Hide sources" : "Search Results"}
      </Text>
    </Pressable>
  );
}

// ---------------------------------------------------------------------------
// Web result row — title, snippet (2 lines), favicon + hostname
// Mirrors web's WebResults list item exactly.
// ---------------------------------------------------------------------------

function WebResultRow({ result }: { result: WebResult }) {
  const hostname = getHostname(result.url);
  const description = result.content || result.snippet;

  return (
    <ToolCardInner
      dense
      onPress={() => result.url && Linking.openURL(result.url)}
    >
      <View className="gap-1">
        {/* Title — truncated single line, zinc-100 */}
        <Text className="text-zinc-100 text-sm font-medium" numberOfLines={1}>
          {result.title || hostname || "Untitled"}
        </Text>

        {/* Snippet — 2 line clamp, zinc-500 */}
        {!!description && (
          <Text className="text-zinc-500 text-xs" numberOfLines={2}>
            {description}
          </Text>
        )}

        {/* Favicon + hostname row — primary blue */}
        {!!hostname && (
          <View className="flex-row items-center gap-1.5 mt-0.5">
            <FaviconImage url={result.url} size={14} />
            <Text className="text-[#00bbff] text-xs" numberOfLines={1}>
              {hostname}
            </Text>
          </View>
        )}
      </View>
    </ToolCardInner>
  );
}

// ---------------------------------------------------------------------------
// News result row — news icon + title (large), content snippet, score
// Mirrors web's NewsResults: icon + text-lg title, 2-line content, score.
// ---------------------------------------------------------------------------

function NewsResultRow({ article }: { article: NewsResult }) {
  return (
    <ToolCardInner onPress={() => article.url && Linking.openURL(article.url)}>
      {/* Header row: news icon + title */}
      <View className="flex-row items-center gap-2 mb-1">
        <AppIcon icon={News01Icon} size={18} color="#00bbff" />
        <Text
          className="text-[#00bbff] text-base font-medium flex-1"
          numberOfLines={1}
        >
          {article.title || "Untitled"}
        </Text>
      </View>

      {/* Content snippet — 2 line clamp, zinc-400 */}
      {!!article.content && (
        <Text className="text-zinc-400 text-sm mb-1" numberOfLines={2}>
          {article.content}
        </Text>
      )}

      {/* Relevance score */}
      {typeof article.score === "number" && (
        <Text className="text-zinc-500 text-xs">
          Score: {article.score.toFixed(2)}
        </Text>
      )}
    </ToolCardInner>
  );
}

// ---------------------------------------------------------------------------
// Image carousel — rotated overlapping tiles with +N cycle button
// Mirrors web's ImageResults exactly: alternating ±8deg rotation, -space-x-14
// overlap, cycle button with arrow icon.
// ---------------------------------------------------------------------------

const IMAGE_TILE_SIZE = 112;
const IMAGE_OVERLAP = -40;
const MAX_VISIBLE_IMAGES = 5;

function ImageTile({
  imageUrl,
  index,
  totalVisible,
}: {
  imageUrl: string;
  index: number;
  totalVisible: number;
}) {
  const rotation =
    totalVisible > 1 ? (index % 2 === 0 ? "8deg" : "-8deg") : "0deg";

  return (
    <Animated.View
      entering={FadeInRight.delay(index * 70).duration(150)}
      style={{
        transform: [{ rotate: rotation }],
        zIndex: index,
        marginLeft: index === 0 ? 0 : IMAGE_OVERLAP,
      }}
    >
      <Pressable onPress={() => Linking.openURL(imageUrl)}>
        <Image
          source={{ uri: imageUrl }}
          style={{
            width: IMAGE_TILE_SIZE,
            height: IMAGE_TILE_SIZE,
            borderRadius: 16,
            backgroundColor: "#27272a",
          }}
          resizeMode="cover"
        />
      </Pressable>
    </Animated.View>
  );
}

function ImageResults({ images }: { images: ImageResult[] }) {
  const validImages = images.filter(
    (url): url is string => typeof url === "string" && url.length > 0,
  );
  const [startIndex, setStartIndex] = useState(0);

  if (validImages.length === 0) return null;

  const displayImages = validImages.slice(
    startIndex,
    startIndex + MAX_VISIBLE_IMAGES,
  );
  const remaining = validImages.length - (startIndex + MAX_VISIBLE_IMAGES);
  const nextBatchCount =
    remaining > 0
      ? remaining
      : Math.min(MAX_VISIBLE_IMAGES, validImages.length - MAX_VISIBLE_IMAGES);

  const cycleNext = () => {
    const nextStart = startIndex + MAX_VISIBLE_IMAGES;
    setStartIndex(nextStart >= validImages.length ? 0 : nextStart);
  };

  const showCycleButton = validImages.length > MAX_VISIBLE_IMAGES;

  return (
    <View className="flex-row items-center py-2">
      {displayImages.map((imageUrl, index) => (
        <ImageTile
          key={`${imageUrl}-${startIndex}`}
          imageUrl={imageUrl}
          index={index}
          totalVisible={displayImages.length}
        />
      ))}
      {showCycleButton && (
        <Pressable
          onPress={cycleNext}
          style={{
            marginLeft: IMAGE_OVERLAP,
            zIndex: displayImages.length,
            width: IMAGE_TILE_SIZE,
            height: IMAGE_TILE_SIZE,
            borderRadius: 16,
            backgroundColor: "rgba(39,39,42,0.85)",
            alignItems: "center",
            justifyContent: "center",
            gap: 6,
            transform: [
              { rotate: displayImages.length % 2 === 0 ? "8deg" : "-8deg" },
            ],
          }}
        >
          <Text className="text-zinc-100 text-base font-semibold">
            +{nextBatchCount}
          </Text>
          <AppIcon icon={ArrowRight01Icon} size={16} color="#a1a1aa" />
        </Pressable>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Running / streaming state
// ---------------------------------------------------------------------------

function PulsingDot() {
  const opacity = useSharedValue(1);

  useEffect(() => {
    opacity.value = withRepeat(
      withSequence(
        withTiming(0.25, { duration: 600 }),
        withTiming(1, { duration: 600 }),
      ),
      -1,
      false,
    );
  }, [opacity]);

  const animatedStyle = useAnimatedStyle(() => ({ opacity: opacity.value }));

  return (
    <Animated.View
      style={[
        animatedStyle,
        { width: 6, height: 6, borderRadius: 3, backgroundColor: "#00bbff" },
      ]}
    />
  );
}

function SearchRunningCard({ data }: { data: SearchResults }) {
  const queryText = data.query;
  const progressText = data.progress ?? "Searching the web...";

  return (
    <ToolCardShell>
      <ToolCardHeader
        icon={Search01Icon}
        title="Web Search"
        trailing={<PulsingDot />}
      />
      {!!queryText && (
        <ToolCardInner dense className="mb-2">
          <Text className="text-zinc-500 text-xs mb-0.5">Query</Text>
          <Text className="text-zinc-100 text-sm font-medium">
            &quot;{queryText}&quot;
          </Text>
        </ToolCardInner>
      )}
      <Text className="text-zinc-400 text-xs">{progressText}</Text>
    </ToolCardShell>
  );
}

// ---------------------------------------------------------------------------
// Complete state — sources pill + expandable web list + images + news
// Mirrors web's SearchResultsTabs layout: sources pill (web), images, news,
// each section separated by gap-6 to match web's space-y-6.
// ---------------------------------------------------------------------------

function SearchCompleteCard({ data }: { data: SearchResults }) {
  const webResults = data.web ?? [];
  const imageResults = data.images ?? [];
  const newsResults = data.news ?? [];

  const hasWeb = webResults.length > 0;
  const hasImages = imageResults.length > 0;
  const hasNews = newsResults.length > 0;

  const [sourcesExpanded, setSourcesExpanded] = useState(false);

  if (!hasWeb && !hasImages && !hasNews) return null;

  return (
    <ToolCardShell>
      <View className="gap-6">
        {/* Web sources — pill toggle + expandable list */}
        {hasWeb && (
          <View className="gap-2">
            <SourcesPill
              web={webResults}
              expanded={sourcesExpanded}
              onToggle={() => setSourcesExpanded((prev) => !prev)}
            />
            {sourcesExpanded && (
              <View className="gap-1.5">
                {webResults.map((result, index) => (
                  <WebResultRow
                    key={result.url || result.title || String(index)}
                    result={result}
                  />
                ))}
              </View>
            )}
          </View>
        )}

        {/* Image carousel */}
        {hasImages && <ImageResults images={imageResults} />}

        {/* News articles */}
        {hasNews && (
          <View className="gap-2">
            {newsResults.map((article, index) => (
              <NewsResultRow
                key={article.url || article.title || String(index)}
                article={article}
              />
            ))}
          </View>
        )}
      </View>
    </ToolCardShell>
  );
}

// ---------------------------------------------------------------------------
// Main export — routes to running or complete sub-component
// ---------------------------------------------------------------------------

export function SearchResultsCard({ data }: { data: SearchResults }) {
  if (data.status === "running") {
    return <SearchRunningCard data={data} />;
  }
  return <SearchCompleteCard data={data} />;
}
