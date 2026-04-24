import type {
  DeepResearchResults,
  DeepResearchSource,
  EnhancedWebResult,
  ImageResult,
  NewsResult,
  SearchResults,
  WebResult,
} from "@gaia/shared";
import { Accordion, Tabs } from "heroui-native";
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
  Globe02Icon,
  LinkBackwardIcon,
  News01Icon,
  Search01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  ToolCardHeader,
  ToolCardInner,
  ToolCardShell,
} from "@/features/chat/tool-data/primitives";

export type { DeepResearchResults, DeepResearchSource, EnhancedWebResult };

type Tab = "enhanced" | "original" | "metadata";

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

function FaviconImage({ url }: { url?: string }) {
  const [errored, setErrored] = useState(false);
  const hostname = getHostname(url);

  if (!hostname || errored) {
    return (
      <View className="w-4 h-4 rounded-full bg-zinc-700 items-center justify-center">
        <AppIcon icon={Globe02Icon} size={10} color="#71717a" />
      </View>
    );
  }

  return (
    <Image
      source={{
        uri: `https://www.google.com/s2/favicons?domain=${hostname}&sz=64`,
      }}
      style={{ width: 14, height: 14, borderRadius: 7 }}
      onError={() => setErrored(true)}
    />
  );
}

// ---------------------------------------------------------------------------
// Streaming / running state
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

interface RunningSourceRowProps {
  source: DeepResearchSource;
}

function RunningSourceRow({ source }: RunningSourceRowProps) {
  const hostname = getHostname(source.url);
  return (
    <View className="flex-row items-center gap-2">
      <FaviconImage url={source.url} />
      <Text className="text-zinc-400 text-xs flex-1" numberOfLines={1}>
        {hostname || source.title}
      </Text>
    </View>
  );
}

interface DeepResearchRunningCardProps {
  data: DeepResearchResults;
}

function DeepResearchRunningCard({ data }: DeepResearchRunningCardProps) {
  const sources = data.sources ?? [];
  const recentSources = sources.slice(-3);
  const totalSources = data.totalSources ?? sources.length;
  const subSteps = data.subSteps ?? [];
  const latestStep =
    data.progress ?? subSteps[subSteps.length - 1] ?? "Researching...";

  return (
    <ToolCardShell>
      <ToolCardHeader
        icon={Search01Icon}
        title="Deep Research"
        trailing={<PulsingDot />}
      />

      {/* Current step */}
      <ToolCardInner dense className="mb-3">
        <Text className="text-zinc-500 text-xs mb-0.5">Current step</Text>
        <Text className="text-zinc-100 text-sm" numberOfLines={2}>
          {latestStep}
        </Text>
      </ToolCardInner>

      {/* Sub-steps history */}
      {subSteps.length > 1 && (
        <View className="mb-3 gap-1">
          {subSteps.slice(0, -1).map((step, index) => (
            <View
              key={`step-${index}-${step.slice(0, 10)}`}
              className="flex-row items-center gap-1.5"
            >
              <View className="w-1 h-1 rounded-full bg-zinc-600" />
              <Text className="text-zinc-500 text-[11px]" numberOfLines={1}>
                {step}
              </Text>
            </View>
          ))}
        </View>
      )}

      {/* Recent sources being visited */}
      {recentSources.length > 0 && (
        <View>
          <Text className="text-zinc-400 text-[11px] mb-1.5">
            {totalSources > 0
              ? `Visiting sources (${totalSources} found)`
              : "Visiting sources"}
          </Text>
          <View className="gap-1.5">
            {recentSources.map((source, index) => (
              <ToolCardInner
                key={source.url || `src-${index}`}
                dense
                onPress={() => source.url && Linking.openURL(source.url)}
              >
                <RunningSourceRow source={source} />
              </ToolCardInner>
            ))}
          </View>
        </View>
      )}
    </ToolCardShell>
  );
}

// ---------------------------------------------------------------------------
// Error state
// ---------------------------------------------------------------------------

function DeepResearchErrorCard() {
  return (
    <ToolCardShell>
      <View className="flex-row items-center gap-2">
        <AppIcon icon={Search01Icon} size={14} color="#f87171" />
        <Text className="text-[#f87171] text-xs">Deep Research</Text>
      </View>
      <Text className="text-zinc-400 text-sm mt-1.5">
        Research encountered an error.
      </Text>
    </ToolCardShell>
  );
}

// ---------------------------------------------------------------------------
// Enhanced results tab
// Web: each result shows title (blue, primary link), then LinkBackward icon
// + hostname below it. Full content is commented out on web — not shown here.
// ---------------------------------------------------------------------------

function EnhancedResultRow({ result }: { result: EnhancedWebResult }) {
  const hostname = getHostname(result.url);

  return (
    <ToolCardInner onPress={() => result.url && Linking.openURL(result.url)}>
      {/* Title — blue, truncated */}
      <Text className="text-[#00bbff] text-sm font-medium" numberOfLines={1}>
        {result.title || hostname || "Untitled"}
      </Text>

      {/* Hostname with link icon */}
      {!!hostname && (
        <View className="flex-row items-center gap-1 mt-1">
          <AppIcon icon={LinkBackwardIcon} size={12} color="#71717a" />
          <Text className="text-zinc-400 text-xs flex-1" numberOfLines={1}>
            {hostname}
          </Text>
        </View>
      )}
    </ToolCardInner>
  );
}

function EnhancedResultsSection({ results }: { results: EnhancedWebResult[] }) {
  return (
    <View className="gap-2 pt-3">
      {results.map((result, index) => (
        <EnhancedResultRow
          key={result.url || result.title || String(index)}
          result={result}
        />
      ))}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Original search tab — web results, images (rotated tiles), news
// Web: WebResults shows title / content (2 lines) / favicon + hostname
// ---------------------------------------------------------------------------

function OriginalWebResultRow({ result }: { result: WebResult }) {
  const hostname = getHostname(result.url);

  return (
    <ToolCardInner onPress={() => result.url && Linking.openURL(result.url)}>
      {/* Title — zinc-100 */}
      <Text className="text-zinc-100 text-sm font-medium" numberOfLines={1}>
        {result.title || hostname || "Untitled"}
      </Text>

      {/* Content snippet — 2 lines, zinc-400 */}
      {!!result.content && (
        <Text className="text-zinc-400 text-xs mt-1" numberOfLines={2}>
          {result.content}
        </Text>
      )}

      {/* Favicon + hostname */}
      {!!hostname && (
        <View className="flex-row items-center gap-2 mt-1.5">
          <FaviconImage url={result.url} />
          <Text className="text-[#00bbff] text-xs flex-1" numberOfLines={1}>
            {hostname}
          </Text>
        </View>
      )}
    </ToolCardInner>
  );
}

// News row — NewsIcon + title, content snippet, score
function OriginalNewsResultRow({ article }: { article: NewsResult }) {
  return (
    <ToolCardInner onPress={() => article.url && Linking.openURL(article.url)}>
      <View className="flex-row items-center gap-2">
        <AppIcon icon={News01Icon} size={16} color="#00bbff" />
        <Text
          className="text-[#00bbff] text-sm font-medium flex-1"
          numberOfLines={1}
        >
          {article.title || "Untitled"}
        </Text>
      </View>
      {!!article.content && (
        <Text className="text-zinc-400 text-xs mt-1" numberOfLines={2}>
          {article.content}
        </Text>
      )}
      {typeof article.score === "number" && (
        <Text className="text-zinc-500 text-xs mt-1">
          Score: {article.score.toFixed(2)}
        </Text>
      )}
    </ToolCardInner>
  );
}

// Image strip — rotated overlapping tiles matching the search results card
// (consistent with web's ImageResults pattern)
const IMAGE_TILE_SIZE = 96;
const IMAGE_OVERLAP = -32;
const MAX_VISIBLE_IMAGES = 4;

function ImageTile({
  url,
  index,
  total,
}: {
  url: string;
  index: number;
  total: number;
}) {
  const rotation = total > 1 ? (index % 2 === 0 ? "6deg" : "-6deg") : "0deg";

  return (
    <Animated.View
      entering={FadeInRight.delay(index * 60).duration(150)}
      style={{
        transform: [{ rotate: rotation }],
        zIndex: index,
        marginLeft: index === 0 ? 0 : IMAGE_OVERLAP,
      }}
    >
      <Pressable onPress={() => Linking.openURL(url)}>
        <Image
          source={{ uri: url }}
          style={{
            width: IMAGE_TILE_SIZE,
            height: IMAGE_TILE_SIZE,
            borderRadius: 14,
            backgroundColor: "#27272a",
          }}
          resizeMode="cover"
        />
      </Pressable>
    </Animated.View>
  );
}

function OriginalImageStrip({ images }: { images: ImageResult[] }) {
  const validUrls = images.filter(
    (img): img is string => typeof img === "string" && img.length > 0,
  );
  const [startIndex, setStartIndex] = useState(0);

  if (validUrls.length === 0) return null;

  const displayImages = validUrls.slice(
    startIndex,
    startIndex + MAX_VISIBLE_IMAGES,
  );
  const remaining = validUrls.length - (startIndex + MAX_VISIBLE_IMAGES);
  const nextBatchCount =
    remaining > 0
      ? remaining
      : Math.min(MAX_VISIBLE_IMAGES, validUrls.length - MAX_VISIBLE_IMAGES);
  const showCycleButton = validUrls.length > MAX_VISIBLE_IMAGES;

  const cycleNext = () => {
    const next = startIndex + MAX_VISIBLE_IMAGES;
    setStartIndex(next >= validUrls.length ? 0 : next);
  };

  return (
    <View className="flex-row items-center py-2">
      {displayImages.map((url, index) => (
        <ImageTile
          key={`${url}-${startIndex}`}
          url={url}
          index={index}
          total={displayImages.length}
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
            borderRadius: 14,
            backgroundColor: "rgba(39,39,42,0.85)",
            alignItems: "center",
            justifyContent: "center",
            transform: [
              { rotate: displayImages.length % 2 === 0 ? "6deg" : "-6deg" },
            ],
          }}
        >
          <Text className="text-zinc-100 text-sm font-semibold">
            +{nextBatchCount}
          </Text>
        </Pressable>
      )}
    </View>
  );
}

function OriginalSearchSection({ search }: { search: SearchResults }) {
  const webResults = search.web ?? [];
  const imageResults = search.images ?? [];
  const newsResults = search.news ?? [];

  return (
    <View className="gap-3 pt-3">
      {webResults.length > 0 && (
        <View className="gap-2">
          {webResults.map((result, index) => (
            <OriginalWebResultRow
              key={result.url || result.title || String(index)}
              result={result}
            />
          ))}
        </View>
      )}

      {imageResults.length > 0 && <OriginalImageStrip images={imageResults} />}

      {newsResults.length > 0 && (
        <View className="gap-2">
          {newsResults.map((article, index) => (
            <OriginalNewsResultRow
              key={article.url || article.title || String(index)}
              article={article}
            />
          ))}
        </View>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Search metadata tab — query / elapsed time / content size
// Web: "Search Statistics" heading, then label-value rows.
// ---------------------------------------------------------------------------

function MetadataSection({
  metadata,
}: {
  metadata: NonNullable<DeepResearchResults["metadata"]>;
}) {
  const showElapsed =
    typeof metadata.elapsed_time === "number" && metadata.elapsed_time > 0;
  const showContentSize =
    typeof metadata.total_content_size === "number" &&
    metadata.total_content_size > 0;

  return (
    <ToolCardInner className="mt-3">
      {/* Section heading — matches web's "Search Statistics" */}
      <Text className="text-zinc-100 text-sm font-semibold mb-3">
        Search Statistics
      </Text>

      <View className="gap-2">
        {!!metadata.query && (
          <View className="flex-row items-center justify-between gap-4">
            <Text className="text-zinc-400 text-xs">Search Query:</Text>
            <Text
              className="text-zinc-100 text-xs font-medium flex-1 text-right"
              numberOfLines={1}
            >
              {metadata.query}
            </Text>
          </View>
        )}

        {showElapsed && (
          <View className="flex-row items-center justify-between gap-4">
            <Text className="text-zinc-400 text-xs">Processing Time:</Text>
            <Text className="text-zinc-100 text-xs font-medium">
              {(metadata.elapsed_time as number).toFixed(2)} seconds
            </Text>
          </View>
        )}

        {showContentSize && (
          <View className="flex-row items-center justify-between gap-4">
            <Text className="text-zinc-400 text-xs">Content Size:</Text>
            <Text className="text-zinc-100 text-xs font-medium">
              {((metadata.total_content_size as number) / 1024).toFixed(2)} KB
            </Text>
          </View>
        )}
      </View>
    </ToolCardInner>
  );
}

// ---------------------------------------------------------------------------
// Completed state
// Mirrors web: accordion toggle (Hide/Show Deep research Results) then tabs
// for Enhanced Results / Original Search / Search Info.
// The accordion trigger shows only the text button — no extra chevron indicator.
// ---------------------------------------------------------------------------

function DeepResearchCompleteCard({ data }: { data: DeepResearchResults }) {
  const hasEnhanced =
    !!data.enhanced_results && data.enhanced_results.length > 0;
  const hasOriginal = !!data.original_search;
  const hasMetadata = !!data.metadata;

  const initialTab: Tab = hasEnhanced
    ? "enhanced"
    : hasOriginal
      ? "original"
      : "metadata";

  const [activeTab, setActiveTab] = useState<Tab>(initialTab);

  return (
    <ToolCardShell>
      <Accordion
        selectionMode="single"
        defaultValue="1"
        animation="disable-all"
      >
        <Accordion.Item value="1">
          {({ isExpanded }) => (
            <>
              {/* Accordion trigger — text pill only, no chevron, matches web */}
              <Accordion.Trigger className="p-0">
                <View className="rounded-lg bg-white/10 px-3 py-1.5 self-start">
                  <Text className="text-zinc-200 text-sm font-medium">
                    {isExpanded
                      ? "Hide Deep Research Results"
                      : "Show Deep Research Results"}
                  </Text>
                </View>
              </Accordion.Trigger>

              {/* Tab content */}
              <Accordion.Content>
                <Tabs
                  value={activeTab}
                  onValueChange={(v) => setActiveTab(v as Tab)}
                  variant="primary"
                  animation="disable-all"
                >
                  <Tabs.List className="mt-3">
                    <Tabs.Indicator />
                    {hasEnhanced && (
                      <Tabs.Trigger value="enhanced">
                        <Tabs.Label>Enhanced Results</Tabs.Label>
                      </Tabs.Trigger>
                    )}
                    {hasOriginal && (
                      <Tabs.Trigger value="original">
                        <View className="flex-row items-center gap-1.5">
                          <AppIcon
                            icon={Search01Icon}
                            size={13}
                            color="#a1a1aa"
                          />
                          <Tabs.Label>Original Search</Tabs.Label>
                        </View>
                      </Tabs.Trigger>
                    )}
                    {hasMetadata && (
                      <Tabs.Trigger value="metadata">
                        <View className="flex-row items-center gap-1.5">
                          <AppIcon
                            icon={Globe02Icon}
                            size={13}
                            color="#a1a1aa"
                          />
                          <Tabs.Label>Search Info</Tabs.Label>
                        </View>
                      </Tabs.Trigger>
                    )}
                  </Tabs.List>

                  {hasEnhanced && data.enhanced_results && (
                    <Tabs.Content value="enhanced">
                      <EnhancedResultsSection results={data.enhanced_results} />
                    </Tabs.Content>
                  )}
                  {hasOriginal && data.original_search && (
                    <Tabs.Content value="original">
                      <OriginalSearchSection search={data.original_search} />
                    </Tabs.Content>
                  )}
                  {hasMetadata && data.metadata && (
                    <Tabs.Content value="metadata">
                      <MetadataSection metadata={data.metadata} />
                    </Tabs.Content>
                  )}
                </Tabs>
              </Accordion.Content>
            </>
          )}
        </Accordion.Item>
      </Accordion>
    </ToolCardShell>
  );
}

// ---------------------------------------------------------------------------
// Main export — routes to running / error / complete sub-component
// ---------------------------------------------------------------------------

export function DeepResearchCard({ data }: { data: DeepResearchResults }) {
  if (data.status === "running") {
    return <DeepResearchRunningCard data={data} />;
  }

  if (data.status === "error") {
    return <DeepResearchErrorCard />;
  }

  return <DeepResearchCompleteCard data={data} />;
}
