import type {
  DeepResearchResults,
  DeepResearchSource,
  EnhancedWebResult,
  ImageResult,
  SearchResults,
} from "@gaia/shared";
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
  LinkBackwardIcon,
  Search01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  FaviconImage,
  getHostname,
  NewsResultCard,
  ToolCardHeader,
  ToolCardInner,
  ToolCardShell,
  WebResultRow,
} from "@/features/chat/tool-data/primitives";

export type { DeepResearchResults, DeepResearchSource, EnhancedWebResult };

type Tab = "enhanced" | "original" | "metadata";

// ---------------------------------------------------------------------------
// PulsingDot — running-state status indicator
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

// ---------------------------------------------------------------------------
// Running state
// ---------------------------------------------------------------------------

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

function DeepResearchRunningCard({ data }: { data: DeepResearchResults }) {
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
              <View className="w-1 h-1 rounded-full bg-zinc-500" />
              <Text className="text-zinc-500 text-xs" numberOfLines={1}>
                {step}
              </Text>
            </View>
          ))}
        </View>
      )}

      {/* Recent sources being visited */}
      {recentSources.length > 0 && (
        <View>
          <Text className="text-zinc-400 text-xs mb-1.5">
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
// Web: each card uses `rounded-2xl bg-zinc-800 p-4` with title (primary,
// truncated) + LinkBackward icon + hostname row. Full-content rendering is
// commented out on web — match exactly.
// ---------------------------------------------------------------------------

function EnhancedResultRow({ result }: { result: EnhancedWebResult }) {
  const hostname = getHostname(result.url);

  return (
    <Pressable
      onPress={() => result.url && Linking.openURL(result.url)}
      android_ripple={{ color: "rgba(255,255,255,0.05)", borderless: false }}
      style={{
        backgroundColor: "#27272a", // zinc-800
        borderRadius: 16,
        padding: 16,
      }}
    >
      <Text className="text-[#00bbff] text-sm font-medium" numberOfLines={1}>
        {result.title || hostname || "Untitled"}
      </Text>

      {!!hostname && (
        <View className="flex-row items-center gap-1 mt-1">
          <AppIcon icon={LinkBackwardIcon} size={13} color="#71717a" />
          <Text className="text-zinc-400 text-xs flex-1" numberOfLines={1}>
            {hostname}
          </Text>
        </View>
      )}
    </Pressable>
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
// Original search tab — mirrors web's nested SearchResultsTabs render.
// Reuses the shared WebResultRow + NewsResultCard primitives. Image strip
// is the deep-research-specific overlapping rotated tile pattern matching
// web's SearchResultsTabs ImageResults.
// ---------------------------------------------------------------------------

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
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={{
        paddingVertical: 8,
        alignItems: "center",
      }}
    >
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
    </ScrollView>
  );
}

function OriginalSearchSection({ search }: { search: SearchResults }) {
  const webResults = search.web ?? [];
  const imageResults = search.images ?? [];
  const newsResults = search.news ?? [];

  return (
    <View className="gap-3 pt-3">
      {/* Web results — list of WebResultRow primitives in a zinc-800 card.
         Mirrors web's PopoverContent → WebResults but always-open since the
         popover doesn't translate to mobile inside an already-collapsed
         accordion. */}
      {webResults.length > 0 && (
        <View
          style={{
            backgroundColor: "#27272a", // zinc-800
            borderRadius: 16,
            overflow: "hidden",
          }}
        >
          {webResults.map((result, index) => (
            <WebResultRow
              key={result.url || result.title || String(index)}
              result={result}
              isLast={index === webResults.length - 1}
            />
          ))}
        </View>
      )}

      {imageResults.length > 0 && <OriginalImageStrip images={imageResults} />}

      {newsResults.length > 0 && (
        <View className="gap-2">
          {newsResults.map((article, index) => (
            <NewsResultCard
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
// Web: "Search Statistics" heading, then label-value rows, all in one
// rounded-lg bg-zinc-800 card.
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
    <View
      className="mt-3"
      style={{
        backgroundColor: "#27272a", // zinc-800
        borderRadius: 8,
        padding: 16,
      }}
    >
      <Text className="text-[#00bbff] text-base font-medium mb-2">
        Search Statistics
      </Text>

      <View className="gap-2">
        {!!metadata.query && (
          <View className="flex-row items-center justify-between gap-4">
            <Text className="text-zinc-400 text-sm">Search Query:</Text>
            <Text
              className="text-zinc-100 text-sm font-medium flex-1 text-right"
              numberOfLines={1}
            >
              {metadata.query}
            </Text>
          </View>
        )}

        {showElapsed && (
          <View className="flex-row items-center justify-between gap-4">
            <Text className="text-zinc-400 text-sm">Processing Time:</Text>
            <Text className="text-zinc-100 text-sm font-medium">
              {(metadata.elapsed_time as number).toFixed(2)} seconds
            </Text>
          </View>
        )}

        {showContentSize && (
          <View className="flex-row items-center justify-between gap-4">
            <Text className="text-zinc-400 text-sm">Content Size:</Text>
            <Text className="text-zinc-100 text-sm font-medium">
              {((metadata.total_content_size as number) / 1024).toFixed(2)} KB
            </Text>
          </View>
        )}
      </View>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Completed state — flat (no ToolCardShell). Mirrors web:
// - Accordion trigger pill ("Hide/Show Deep research Results", bg-white/10)
// - Tab row when expanded (Enhanced / Original / Search Info)
// - Each tab content rendered below
// Matches web's `<Accordion><AccordionItem>` + `<Tabs>` layout, but rolled by
// hand — heroui-native doesn't ship a Tabs component the mobile app uses.
// ---------------------------------------------------------------------------

interface TabDef {
  key: Tab;
  label: string;
  icon?: typeof Search01Icon;
}

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

  const [isExpanded, setIsExpanded] = useState(true);
  const [activeTab, setActiveTab] = useState<Tab>(initialTab);

  if (!hasEnhanced && !hasOriginal && !hasMetadata) return null;

  const tabs: TabDef[] = [
    ...(hasEnhanced
      ? [{ key: "enhanced" as Tab, label: "Enhanced Results" }]
      : []),
    ...(hasOriginal
      ? [
          {
            key: "original" as Tab,
            label: "Original Search",
            icon: Search01Icon,
          },
        ]
      : []),
    ...(hasMetadata
      ? [{ key: "metadata" as Tab, label: "Search Info", icon: Globe02Icon }]
      : []),
  ];

  return (
    <View style={{ marginHorizontal: 16, marginVertical: 4 }}>
      {/* Accordion trigger — text pill only, no chevron, matches web */}
      <Pressable onPress={() => setIsExpanded((prev) => !prev)}>
        <View
          style={{
            backgroundColor: "rgba(255,255,255,0.1)",
            paddingHorizontal: 12,
            paddingVertical: 6,
            borderRadius: 8,
            alignSelf: "flex-start",
          }}
        >
          <Text className="text-zinc-100 text-sm font-medium">
            {isExpanded
              ? "Hide Deep research Results"
              : "Show Deep research Results"}
          </Text>
        </View>
      </Pressable>

      {isExpanded && (
        <>
          {/* Custom tab row — pill style matching web's Tabs color="primary"
             variant="light": active tab uses primary tint, inactive uses
             zinc-700 background. */}
          <View className="flex-row gap-1 mt-3 flex-wrap">
            {tabs.map((tab) => {
              const isActive = activeTab === tab.key;
              return (
                <Pressable
                  key={tab.key}
                  onPress={() => setActiveTab(tab.key)}
                  android_ripple={{
                    color: "rgba(255,255,255,0.05)",
                    borderless: false,
                  }}
                  style={{
                    flexDirection: "row",
                    alignItems: "center",
                    gap: 6,
                    borderRadius: 8,
                    paddingHorizontal: 12,
                    paddingVertical: 6,
                    backgroundColor: isActive
                      ? "rgba(0,187,255,0.18)"
                      : "rgba(63,63,70,0.4)",
                  }}
                >
                  {tab.icon && (
                    <AppIcon
                      icon={tab.icon}
                      size={13}
                      color={isActive ? "#00bbff" : "#a1a1aa"}
                    />
                  )}
                  <Text
                    className="text-xs font-medium"
                    style={{ color: isActive ? "#00bbff" : "#a1a1aa" }}
                  >
                    {tab.label}
                  </Text>
                </Pressable>
              );
            })}
          </View>

          {/* Tab content */}
          {activeTab === "enhanced" && hasEnhanced && data.enhanced_results && (
            <EnhancedResultsSection results={data.enhanced_results} />
          )}
          {activeTab === "original" && hasOriginal && data.original_search && (
            <OriginalSearchSection search={data.original_search} />
          )}
          {activeTab === "metadata" && hasMetadata && data.metadata && (
            <MetadataSection metadata={data.metadata} />
          )}
        </>
      )}
    </View>
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
