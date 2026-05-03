import type {
  ImageResult,
  NewsResult,
  SearchResults,
  WebResult,
} from "@gaia/shared";
import { BottomSheetScrollView } from "@gorhom/bottom-sheet";
import { useEffect, useState } from "react";
import { Image, Linking, Pressable, ScrollView, View } from "react-native";
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
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";

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
// Mirrors web's `next/image` favicon with onError → display:none. We render a
// zinc-700 circle behind the favicon so failed loads still match the web
// stacked-circle look.
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
// SourcesPill — stacked favicons + "Search Results" label
// Mirrors web's SourcesButton: HeroUI Button variant="flat" radius="full"
// size="sm", 4 stacked favicons (-space-x-3, h-5 w-5 rounded-full border-2
// border-zinc-900). Tapping opens the WebResultsSheet bottom-sheet.
// ---------------------------------------------------------------------------

const FAVICON_OUTER_SIZE = 20; // h-5 w-5
const FAVICON_INNER_SIZE = 14; // sits inside the 2px border

function SourcesPill({
  web,
  onPress,
}: {
  web: WebResult[];
  onPress: () => void;
}) {
  const previewFavicons = web.slice(0, 4);

  return (
    <View className="flex-row">
      <Pressable
        onPress={onPress}
        android_ripple={{ color: "rgba(255,255,255,0.08)", borderless: false }}
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 8,
          paddingHorizontal: 12,
          paddingVertical: 6,
          borderRadius: 9999,
          backgroundColor: "#27272a", // zinc-800 (HeroUI flat)
          alignSelf: "flex-start",
        }}
      >
        {/* Overlapping favicon circles — mirrors web's -space-x-3 (12px) */}
        <View className="flex-row">
          {previewFavicons.map((result, index) => (
            <View
              key={(result.url ?? "") + (result.title ?? index)}
              style={{
                marginLeft: index === 0 ? 0 : -12,
                width: FAVICON_OUTER_SIZE,
                height: FAVICON_OUTER_SIZE,
                borderRadius: FAVICON_OUTER_SIZE / 2,
                backgroundColor: "#3f3f46", // zinc-700
                borderWidth: 2,
                borderColor: "#18181b", // zinc-900
                alignItems: "center",
                justifyContent: "center",
                overflow: "hidden",
                zIndex: previewFavicons.length - index,
              }}
            >
              <FaviconImage url={result.url} size={FAVICON_INNER_SIZE} />
            </View>
          ))}
        </View>
        <Text className="text-zinc-300 text-sm font-medium">
          Search Results
        </Text>
      </Pressable>
    </View>
  );
}

// ---------------------------------------------------------------------------
// WebResultRow — used inside the bottom-sheet web list
// Mirrors web's WebResults list item: title (sm font-medium, 1 line),
// snippet (xs foreground-500, 2 lines), favicon + hostname row (xs primary).
// Bottom border per row (zinc-700 / 15% white in dark).
// ---------------------------------------------------------------------------

function WebResultRow({
  result,
  isLast,
}: {
  result: WebResult;
  isLast: boolean;
}) {
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
// WebResultsSheet — bottom-sheet popover equivalent
// Mirrors web's PopoverContent → WebResults: rounded-2xl bg-zinc-800,
// scrollable list of WebResultRow. Bottom-sheet handles the "popover" UX.
// ---------------------------------------------------------------------------

function WebResultsSheet({
  web,
  isOpen,
  onOpenChange,
}: {
  web: WebResult[];
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <BottomSheet isOpen={isOpen} onOpenChange={onOpenChange}>
      <BottomSheet.Portal>
        <BottomSheet.Overlay />
        <BottomSheet.Content
          snapPoints={["60%", "85%"]}
          enableDynamicSizing={false}
          enablePanDownToClose
          backgroundStyle={{ backgroundColor: "#27272a" }}
          handleIndicatorStyle={{ backgroundColor: "#52525b", width: 40 }}
        >
          <View className="px-4 pt-1 pb-3">
            <Text className="text-zinc-100 text-base font-semibold">
              Sources
            </Text>
            <Text className="text-zinc-500 text-xs mt-0.5">
              {web.length} {web.length === 1 ? "result" : "results"}
            </Text>
          </View>
          <BottomSheetScrollView
            contentContainerStyle={{ paddingBottom: 24 }}
            showsVerticalScrollIndicator={false}
          >
            {web.map((result, index) => (
              <WebResultRow
                key={(result.url ?? "") + (result.title ?? "")}
                result={result}
                isLast={index === web.length - 1}
              />
            ))}
          </BottomSheetScrollView>
        </BottomSheet.Content>
      </BottomSheet.Portal>
    </BottomSheet>
  );
}

// ---------------------------------------------------------------------------
// NewsResultCard — full-bleed bg-zinc-800 cards stacked vertically
// Mirrors web's NewsResults: rounded-lg bg-zinc-800 p-4, news icon + title
// (text-lg font-medium, truncated 1 line, primary color), 2-line content
// snippet (sm foreground-700), score line.
// ---------------------------------------------------------------------------

function NewsResultCard({ article }: { article: NewsResult }) {
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

// ---------------------------------------------------------------------------
// ImageResults — horizontal scroll of 128×128 rounded tiles with alternating
// ±8deg rotation. Web uses overlapping (-space-x-14) tiles with the same
// rotation, but the overlap doesn't translate cleanly to RN, so we use a
// horizontal ScrollView (tap-to-open) per port spec.
// ---------------------------------------------------------------------------

const IMAGE_TILE_SIZE = 128;

function ImageTile({ imageUrl, index }: { imageUrl: string; index: number }) {
  const rotation = index % 2 === 0 ? "8deg" : "-8deg";

  return (
    <Animated.View
      entering={FadeInRight.delay(index * 60).duration(180)}
      style={{
        transform: [{ rotate: rotation }],
        marginRight: 16,
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

  if (validImages.length === 0) return null;

  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={{
        paddingHorizontal: 16,
        paddingVertical: 12,
      }}
    >
      {validImages.map((imageUrl, index) => (
        <ImageTile key={imageUrl} imageUrl={imageUrl} index={index} />
      ))}
    </ScrollView>
  );
}

// ---------------------------------------------------------------------------
// Running / streaming state — kept from previous mobile implementation since
// web doesn't have an explicit running view in SearchResultsTabs (it just
// renders nothing until the data arrives). We keep a minimal running card so
// the chat bubble shows progress instead of disappearing mid-stream.
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
// SearchCompleteCard — flat stacked sections (no outer card chrome)
// Mirrors web's SearchResultsTabs: <div className="space-y-6"> with three
// optional sections (SourcesButton → ImageResults → NewsResults). No
// ToolCardShell wrapping — the web version renders flat in the bubble area.
// ---------------------------------------------------------------------------

function SearchCompleteCard({ data }: { data: SearchResults }) {
  const webResults = data.web ?? [];
  const imageResults = data.images ?? [];
  const newsResults = data.news ?? [];

  const hasWeb = webResults.length > 0;
  const hasImages = imageResults.length > 0;
  const hasNews = newsResults.length > 0;

  const [sourcesOpen, setSourcesOpen] = useState(false);

  if (!hasWeb && !hasImages && !hasNews) return null;

  return (
    <View style={{ marginHorizontal: 16, marginVertical: 4 }}>
      {/* space-y-6 = 24px gap between sections */}
      <View style={{ gap: 24 }}>
        {hasWeb && (
          <SourcesPill web={webResults} onPress={() => setSourcesOpen(true)} />
        )}

        {hasImages && (
          <View style={{ marginHorizontal: -16 }}>
            <ImageResults images={imageResults} />
          </View>
        )}

        {hasNews && (
          <View style={{ gap: 8 }}>
            {newsResults.map((article, index) => (
              <NewsResultCard
                key={article.url || article.title || String(index)}
                article={article}
              />
            ))}
          </View>
        )}
      </View>

      {hasWeb && (
        <WebResultsSheet
          web={webResults}
          isOpen={sourcesOpen}
          onOpenChange={setSourcesOpen}
        />
      )}
    </View>
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
