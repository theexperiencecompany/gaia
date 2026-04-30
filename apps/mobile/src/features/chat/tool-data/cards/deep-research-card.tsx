import { useEffect, useState } from "react";
import { Image, Linking, Pressable, View } from "react-native";
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withSequence,
  withTiming,
} from "react-native-reanimated";
import {
  type AnyIcon,
  AppIcon,
  ArrowDown01Icon,
  ArrowUp01Icon,
  ArrowUpRight01Icon,
  Globe02Icon,
  InformationCircleIcon,
  LinkSquare01Icon,
  Search01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  ToolCardHeader,
  ToolCardInner,
  ToolCardShell,
} from "../primitives";

export interface WebResult {
  title?: string;
  url?: string;
  content?: string;
  score?: number;
  raw_content?: string;
  favicon?: string;
}

export interface EnhancedWebResult extends WebResult {
  full_content?: string;
  screenshot_url?: string;
}

export interface SearchResults {
  web?: WebResult[];
  images?: string[];
  news?: Array<{ title?: string; url?: string; content?: string }>;
  answer?: string;
  query?: string;
}

export interface DeepResearchSource {
  url: string;
  title: string;
  snippet?: string;
}

export interface DeepResearchResults {
  /** Present when streaming / running */
  status?: "running" | "complete" | "error";
  progress?: string;
  subSteps?: string[];
  sources?: DeepResearchSource[];
  totalSources?: number;

  /** Present when complete */
  original_search?: SearchResults;
  enhanced_results?: EnhancedWebResult[];
  screenshots_taken?: boolean;
  metadata?: {
    total_content_size?: number;
    elapsed_time?: number;
    query?: string;
  };
}

type TabKey = "enhanced" | "original" | "metadata";

function getHostname(url?: string): string {
  if (!url) return "";
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

// ---------------------------------------------------------------------------
// Shared sub-components
// ---------------------------------------------------------------------------

function FaviconImage({ url }: { url?: string }) {
  const [errored, setErrored] = useState(false);
  const hostname = getHostname(url);

  if (!hostname || errored) {
    return (
      <View className="w-4 h-4 rounded-full bg-zinc-800 items-center justify-center">
        <AppIcon icon={Globe02Icon} size={10} color="#a1a1aa" />
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
// Streaming / running state
// ---------------------------------------------------------------------------

interface RunningSourceRowProps {
  source: DeepResearchSource;
}

function RunningSourceRow({ source }: RunningSourceRowProps) {
  const hostname = getHostname(source.url);
  return (
    <Pressable
      onPress={() => source.url && Linking.openURL(source.url)}
      className="flex-row items-center gap-2 py-1.5"
    >
      <FaviconImage url={source.url} />
      <Text className="text-xs text-zinc-400 flex-1" numberOfLines={1}>
        {hostname || source.title}
      </Text>
    </Pressable>
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
        iconColor="#00bbff"
        title="Deep Research"
        trailing={<PulsingDot />}
      />

      <ToolCardInner className="mb-3">
        <Text className="text-xs text-zinc-400 mb-0.5">Current step</Text>
        <Text className="text-sm text-zinc-100" numberOfLines={2}>
          {latestStep}
        </Text>
      </ToolCardInner>

      {subSteps.length > 1 && (
        <View className="mb-3 gap-1">
          {subSteps.slice(0, -1).map((step, index) => (
            <View
              key={`step-${index}-${step.slice(0, 10)}`}
              className="flex-row items-center gap-1.5"
            >
              <View className="w-1 h-1 rounded-full bg-zinc-500" />
              <Text className="text-[11px] text-zinc-400" numberOfLines={1}>
                {step}
              </Text>
            </View>
          ))}
        </View>
      )}

      {recentSources.length > 0 && (
        <View>
          <Text className="text-[11px] text-zinc-400 mb-1">
            {totalSources > 0
              ? `Visiting sources (${totalSources} found)`
              : "Visiting sources"}
          </Text>
          <ToolCardInner>
            {recentSources.map((source, index) => (
              <View
                key={source.url || `src-${index}`}
                className={index > 0 ? "mt-1" : ""}
              >
                <RunningSourceRow source={source} />
              </View>
            ))}
          </ToolCardInner>
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
      <ToolCardHeader
        icon={Search01Icon}
        iconColor="#f87171"
        title="Deep Research"
      />
      <Text className="text-sm text-zinc-400">
        Research encountered an error.
      </Text>
    </ToolCardShell>
  );
}

// ---------------------------------------------------------------------------
// Completed state — tabs + rows
// ---------------------------------------------------------------------------

function EnhancedResultRow({
  result,
  isLast,
}: {
  result: EnhancedWebResult;
  isLast: boolean;
}) {
  const [showFull, setShowFull] = useState(false);
  const hostname = getHostname(result.url);
  const hasFullContent = !!result.full_content;

  return (
    <View className={`py-3 ${isLast ? "" : "mb-1"}`}>
      <Pressable onPress={() => result.url && Linking.openURL(result.url)}>
        <Text
          className="text-sm font-medium text-[#00bbff]"
          numberOfLines={2}
        >
          {result.title || hostname || "Untitled"}
        </Text>
      </Pressable>

      <View className="flex-row items-center gap-1.5 mt-1">
        <FaviconImage url={result.url} />
        <Pressable
          onPress={() => result.url && Linking.openURL(result.url)}
          className="flex-row items-center gap-1"
        >
          <Text className="text-[11px] text-zinc-400" numberOfLines={1}>
            {hostname}
          </Text>
          <AppIcon icon={ArrowUpRight01Icon} size={10} color="#a1a1aa" />
        </Pressable>
      </View>

      {!!result.content && (
        <Text
          className="text-xs text-zinc-400 leading-4 mt-1.5"
          numberOfLines={showFull ? undefined : 3}
        >
          {result.content}
        </Text>
      )}

      {hasFullContent && (
        <Pressable
          onPress={() => setShowFull((prev) => !prev)}
          className="mt-1.5"
        >
          <Text className="text-[11px] text-[#00bbff] font-medium">
            {showFull ? "Show less" : "Show full content"}
          </Text>
        </Pressable>
      )}

      {showFull && !!result.full_content && (
        <View className="rounded-xl bg-zinc-950 p-2.5 mt-2">
          <Text className="text-xs text-zinc-200 leading-4">
            {result.full_content}
          </Text>
        </View>
      )}
    </View>
  );
}

function EnhancedResultsSection({ results }: { results: EnhancedWebResult[] }) {
  return (
    <ToolCardInner>
      {results.map((result, index) => (
        <EnhancedResultRow
          key={result.url || result.title || String(index)}
          result={result}
          isLast={index === results.length - 1}
        />
      ))}
    </ToolCardInner>
  );
}

function OriginalSearchSection({ search }: { search: SearchResults }) {
  const webResults = search.web ?? [];
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? webResults : webResults.slice(0, 3);

  return (
    <View>
      {!!search.query && (
        <ToolCardInner className="mb-3">
          <Text className="text-xs text-zinc-400 mb-0.5">Query</Text>
          <Text className="text-sm text-zinc-100 font-medium">
            "{search.query}"
          </Text>
        </ToolCardInner>
      )}

      {!!search.answer && (
        <ToolCardInner className="mb-3">
          <Text className="text-xs text-zinc-400 mb-0.5">Answer</Text>
          <Text className="text-sm text-zinc-100" numberOfLines={4}>
            {search.answer}
          </Text>
        </ToolCardInner>
      )}

      {visible.length > 0 && (
        <ToolCardInner>
          {visible.map((result, index) => (
            <Pressable
              key={result.url || result.title || String(index)}
              onPress={() => result.url && Linking.openURL(result.url)}
              className={`py-3 ${index === 0 ? "" : "mt-1"}`}
            >
              <View className="flex-row items-start gap-2.5">
                <View className="mt-0.5">
                  <FaviconImage url={result.url} />
                </View>
                <View className="flex-1 gap-0.5">
                  <Text
                    className="text-sm font-medium text-zinc-100"
                    numberOfLines={2}
                  >
                    {result.title || getHostname(result.url) || "Untitled"}
                  </Text>
                  {!!result.content && (
                    <Text
                      className="text-xs text-zinc-400 leading-4"
                      numberOfLines={2}
                    >
                      {result.content}
                    </Text>
                  )}
                  {!!result.url && (
                    <Text
                      className="text-[11px] text-[#00bbff] mt-0.5"
                      numberOfLines={1}
                    >
                      {getHostname(result.url)}
                    </Text>
                  )}
                </View>
              </View>
            </Pressable>
          ))}
        </ToolCardInner>
      )}

      {webResults.length > 3 && (
        <Pressable
          onPress={() => setExpanded((prev) => !prev)}
          className="mt-2 py-1.5 items-center"
        >
          <Text className="text-xs text-[#00bbff] font-medium">
            {expanded ? "Show less" : `Show all ${webResults.length} results`}
          </Text>
        </Pressable>
      )}
    </View>
  );
}

function MetadataSection({
  metadata,
}: {
  metadata: NonNullable<DeepResearchResults["metadata"]>;
}) {
  return (
    <ToolCardInner>
      <Text className="text-xs text-zinc-400 font-medium mb-2">
        Search Statistics
      </Text>

      {!!metadata.query && (
        <View className="flex-row items-center justify-between mb-2">
          <Text className="text-xs text-zinc-400">Search query</Text>
          <Text
            className="text-xs text-zinc-100 font-medium flex-shrink ml-4"
            numberOfLines={1}
          >
            {metadata.query}
          </Text>
        </View>
      )}

      {typeof metadata.elapsed_time === "number" &&
        metadata.elapsed_time > 0 && (
          <View className="flex-row items-center justify-between mb-2">
            <Text className="text-xs text-zinc-400">Processing time</Text>
            <Text className="text-xs text-zinc-100 font-medium">
              {metadata.elapsed_time.toFixed(2)}s
            </Text>
          </View>
        )}

      {typeof metadata.total_content_size === "number" &&
        metadata.total_content_size > 0 && (
          <View className="flex-row items-center justify-between">
            <Text className="text-xs text-zinc-400">Content size</Text>
            <Text className="text-xs text-zinc-100 font-medium">
              {(metadata.total_content_size / 1024).toFixed(2)} KB
            </Text>
          </View>
        )}
    </ToolCardInner>
  );
}

interface TabDef {
  key: TabKey;
  label: string;
  icon: AnyIcon;
}

const ALL_TABS: TabDef[] = [
  { key: "enhanced", label: "Enhanced Results", icon: LinkSquare01Icon },
  { key: "original", label: "Original Search", icon: Search01Icon },
  { key: "metadata", label: "Search Info", icon: InformationCircleIcon },
];

function DeepResearchCompleteCard({ data }: { data: DeepResearchResults }) {
  const hasEnhanced =
    !!data.enhanced_results && data.enhanced_results.length > 0;
  const hasOriginal = !!data.original_search;
  const hasMetadata = !!data.metadata;

  const visibleTabs = ALL_TABS.filter(({ key }) => {
    if (key === "enhanced") return hasEnhanced;
    if (key === "original") return hasOriginal;
    if (key === "metadata") return hasMetadata;
    return false;
  });

  const initialTab: TabKey = visibleTabs[0]?.key ?? "enhanced";

  const [isExpanded, setIsExpanded] = useState(true);
  const [activeTab, setActiveTab] = useState<TabKey>(initialTab);

  const resolvedTab: TabKey =
    visibleTabs.find((t) => t.key === activeTab)?.key ?? initialTab;

  return (
    <ToolCardShell>
      {/* Accordion trigger — text pill only, matches web */}
      <Pressable onPress={() => setIsExpanded((prev) => !prev)}>
        <View className="flex-row items-center gap-1.5 rounded-lg bg-zinc-700 px-3 py-1.5 self-start">
          <Text className="text-zinc-100 text-sm font-medium">
            {isExpanded
              ? "Hide Deep Research Results"
              : "Show Deep Research Results"}
          </Text>
          <AppIcon
            icon={isExpanded ? ArrowUp01Icon : ArrowDown01Icon}
            size={12}
            color="#e4e4e7"
          />
        </View>
      </Pressable>

      {isExpanded && visibleTabs.length > 0 && (
        <>
          {/* Pressable-based tab row */}
          <View className="flex-row gap-1.5 mt-3 flex-wrap">
            {visibleTabs.map((tab) => {
              const isActive = resolvedTab === tab.key;
              return (
                <Pressable
                  key={tab.key}
                  onPress={() => setActiveTab(tab.key)}
                  className="flex-row items-center gap-1.5 rounded-lg px-3 py-1.5"
                  style={{
                    backgroundColor: isActive
                      ? "rgba(0,187,255,0.18)"
                      : "#3f3f46",
                  }}
                >
                  <AppIcon
                    icon={tab.icon}
                    size={13}
                    color={isActive ? "#00bbff" : "#a1a1aa"}
                  />
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
          <View className="mt-3">
            {resolvedTab === "enhanced" && hasEnhanced && (
              <EnhancedResultsSection
                results={data.enhanced_results as EnhancedWebResult[]}
              />
            )}
            {resolvedTab === "original" && hasOriginal && (
              <OriginalSearchSection
                search={data.original_search as SearchResults}
              />
            )}
            {resolvedTab === "metadata" && hasMetadata && (
              <MetadataSection
                metadata={
                  data.metadata as NonNullable<DeepResearchResults["metadata"]>
                }
              />
            )}
          </View>
        </>
      )}
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
