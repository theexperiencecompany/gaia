import { Card, Chip, PressableFeedback } from "heroui-native";
import { useEffect, useState } from "react";
import { Image, Linking, View } from "react-native";
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
  ArrowUpRight01Icon,
  Globe02Icon,
  InformationCircleIcon,
  LinkSquare01Icon,
  Search01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";

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
// Shared sub-components
// ---------------------------------------------------------------------------

function FaviconImage({ url }: { url?: string }) {
  const [errored, setErrored] = useState(false);
  const hostname = getHostname(url);

  if (!hostname || errored) {
    return (
      <View className="w-4 h-4 rounded-full bg-white/10 items-center justify-center">
        <AppIcon icon={Globe02Icon} size={10} color="#8e8e93" />
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
    <PressableFeedback
      onPress={() => Linking.openURL(source.url)}
      className="flex-row items-center gap-2 py-1.5"
    >
      <FaviconImage url={source.url} />
      <Text className="text-xs text-muted flex-1" numberOfLines={1}>
        {hostname || source.title}
      </Text>
    </PressableFeedback>
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
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        {/* Header */}
        <View className="flex-row items-center gap-2 mb-3">
          <View className="w-5 h-5 rounded-md bg-[#00bbff]/15 items-center justify-center">
            <AppIcon icon={Search01Icon} size={12} color="#00bbff" />
          </View>
          <Text className="text-xs font-medium text-[#00bbff]">
            Deep Research
          </Text>
          <View className="ml-auto">
            <PulsingDot />
          </View>
        </View>

        {/* Current step */}
        <View className="rounded-xl bg-white/5 border border-white/8 px-3 py-2 mb-3">
          <Text className="text-xs text-muted mb-0.5">Current step</Text>
          <Text className="text-sm text-foreground" numberOfLines={2}>
            {latestStep}
          </Text>
        </View>

        {/* Sub-steps history */}
        {subSteps.length > 1 && (
          <View className="mb-3 gap-1">
            {subSteps.slice(0, -1).map((step, index) => (
              <View
                key={`step-${index}-${step.slice(0, 10)}`}
                className="flex-row items-center gap-1.5"
              >
                <View className="w-1 h-1 rounded-full bg-white/30" />
                <Text className="text-[11px] text-muted" numberOfLines={1}>
                  {step}
                </Text>
              </View>
            ))}
          </View>
        )}

        {/* Recent sources being visited */}
        {recentSources.length > 0 && (
          <View>
            <Text className="text-[11px] text-muted mb-1">
              {totalSources > 0
                ? `Visiting sources (${totalSources} found)`
                : "Visiting sources"}
            </Text>
            <View className="rounded-xl bg-white/5 border border-white/8 px-3 overflow-hidden">
              {recentSources.map((source, index) => (
                <View
                  key={source.url || `src-${index}`}
                  className={
                    index < recentSources.length - 1
                      ? "border-b border-white/8"
                      : ""
                  }
                >
                  <RunningSourceRow source={source} />
                </View>
              ))}
            </View>
          </View>
        )}
      </Card.Body>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Error state
// ---------------------------------------------------------------------------

function DeepResearchErrorCard() {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        <View className="flex-row items-center gap-2">
          <AppIcon icon={Search01Icon} size={14} color="#f87171" />
          <Text className="text-xs text-[#f87171]">Deep Research</Text>
        </View>
        <Text className="text-sm text-muted mt-1.5">
          Research encountered an error.
        </Text>
      </Card.Body>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Completed state (original implementation, preserved)
// ---------------------------------------------------------------------------

function EnhancedResultRow({ result }: { result: EnhancedWebResult }) {
  const [showFull, setShowFull] = useState(false);
  const hostname = getHostname(result.url);
  const hasFullContent = !!result.full_content;

  return (
    <View className="py-3 border-b border-white/8">
      <PressableFeedback
        onPress={() => result.url && Linking.openURL(result.url)}
      >
        <Text className="text-sm font-medium text-[#00bbff]" numberOfLines={2}>
          {result.title || hostname || "Untitled"}
        </Text>
      </PressableFeedback>

      <View className="flex-row items-center gap-1.5 mt-1">
        <FaviconImage url={result.url} />
        <PressableFeedback
          onPress={() => result.url && Linking.openURL(result.url)}
          className="flex-row items-center gap-1"
        >
          <Text className="text-[11px] text-muted" numberOfLines={1}>
            {hostname}
          </Text>
          <AppIcon icon={ArrowUpRight01Icon} size={10} color="#8e8e93" />
        </PressableFeedback>
      </View>

      {!!result.content && (
        <Text
          className="text-xs text-muted leading-4 mt-1.5"
          numberOfLines={showFull ? undefined : 3}
        >
          {result.content}
        </Text>
      )}

      {hasFullContent && (
        <PressableFeedback
          onPress={() => setShowFull((prev) => !prev)}
          className="mt-1.5"
        >
          <Text className="text-[11px] text-[#00bbff] font-medium">
            {showFull ? "Show less" : "Show full content"}
          </Text>
        </PressableFeedback>
      )}

      {showFull && !!result.full_content && (
        <View className="rounded-lg bg-black/25 p-2.5 mt-2">
          <Text className="text-xs text-foreground leading-4">
            {result.full_content}
          </Text>
        </View>
      )}
    </View>
  );
}

function EnhancedResultsSection({ results }: { results: EnhancedWebResult[] }) {
  return (
    <View className="rounded-xl bg-white/5 border border-white/8 px-3 overflow-hidden">
      {results.map((result, index) => (
        <View
          key={result.url || result.title || String(index)}
          className={index === results.length - 1 ? "border-b-0" : ""}
        >
          <EnhancedResultRow result={result} />
        </View>
      ))}
    </View>
  );
}

function OriginalSearchSection({ search }: { search: SearchResults }) {
  const webResults = search.web ?? [];
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? webResults : webResults.slice(0, 3);

  return (
    <View>
      {!!search.query && (
        <View className="rounded-xl bg-white/5 border border-white/8 px-3 py-2 mb-3">
          <Text className="text-xs text-muted mb-0.5">Query</Text>
          <Text className="text-sm text-foreground font-medium">
            "{search.query}"
          </Text>
        </View>
      )}

      {!!search.answer && (
        <View className="rounded-xl bg-white/5 border border-white/8 px-3 py-2 mb-3">
          <Text className="text-xs text-muted mb-0.5">Answer</Text>
          <Text className="text-sm text-foreground" numberOfLines={4}>
            {search.answer}
          </Text>
        </View>
      )}

      {visible.length > 0 && (
        <View className="rounded-xl bg-white/5 border border-white/8 px-3 overflow-hidden">
          {visible.map((result, index) => (
            <PressableFeedback
              key={result.url || result.title || String(index)}
              onPress={() => result.url && Linking.openURL(result.url)}
              className={`py-3 ${index < visible.length - 1 ? "border-b border-white/8" : ""}`}
            >
              <View className="flex-row items-start gap-2.5">
                <View className="mt-0.5">
                  <FaviconImage url={result.url} />
                </View>
                <View className="flex-1 gap-0.5">
                  <Text
                    className="text-sm font-medium text-foreground"
                    numberOfLines={2}
                  >
                    {result.title || getHostname(result.url) || "Untitled"}
                  </Text>
                  {!!result.content && (
                    <Text
                      className="text-xs text-muted leading-4"
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
            </PressableFeedback>
          ))}
        </View>
      )}

      {webResults.length > 3 && (
        <PressableFeedback
          onPress={() => setExpanded((prev) => !prev)}
          className="mt-2 py-1.5 items-center"
        >
          <Text className="text-xs text-[#00bbff] font-medium">
            {expanded ? "Show less" : `Show all ${webResults.length} results`}
          </Text>
        </PressableFeedback>
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
    <View className="rounded-xl bg-white/5 border border-white/8 px-3 py-3 gap-2.5">
      <Text className="text-xs text-muted font-medium">Search Statistics</Text>

      {!!metadata.query && (
        <View className="flex-row items-center justify-between">
          <Text className="text-xs text-muted">Search query</Text>
          <Text
            className="text-xs text-foreground font-medium flex-shrink ml-4"
            numberOfLines={1}
          >
            {metadata.query}
          </Text>
        </View>
      )}

      {typeof metadata.elapsed_time === "number" && (
        <View className="flex-row items-center justify-between">
          <Text className="text-xs text-muted">Processing time</Text>
          <Text className="text-xs text-foreground font-medium">
            {metadata.elapsed_time.toFixed(2)}s
          </Text>
        </View>
      )}

      {typeof metadata.total_content_size === "number" && (
        <View className="flex-row items-center justify-between">
          <Text className="text-xs text-muted">Content size</Text>
          <Text className="text-xs text-foreground font-medium">
            {(metadata.total_content_size / 1024).toFixed(2)} KB
          </Text>
        </View>
      )}
    </View>
  );
}

const TABS: { key: Tab; label: string; icon: AnyIcon }[] = [
  { key: "enhanced", label: "Enhanced", icon: LinkSquare01Icon },
  { key: "original", label: "Original", icon: Search01Icon },
  { key: "metadata", label: "Info", icon: InformationCircleIcon },
];

function DeepResearchCompleteCard({ data }: { data: DeepResearchResults }) {
  const [expanded, setExpanded] = useState(true);
  const [activeTab, setActiveTab] = useState<Tab>("enhanced");

  const hasEnhanced =
    !!data.enhanced_results && data.enhanced_results.length > 0;
  const hasOriginal = !!data.original_search;
  const hasMetadata = !!data.metadata;

  const visibleTabs = TABS.filter(({ key }) => {
    if (key === "enhanced") return hasEnhanced;
    if (key === "original") return hasOriginal;
    if (key === "metadata") return hasMetadata;
    return false;
  });

  const resolvedTab: Tab =
    visibleTabs.find((t) => t.key === activeTab)?.key ??
    visibleTabs[0]?.key ??
    "enhanced";

  // Derive summary counts
  const sourcesCount =
    data.sources?.length ??
    data.enhanced_results?.length ??
    data.original_search?.web?.length ??
    0;

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        {/* Header */}
        <PressableFeedback onPress={() => setExpanded((prev) => !prev)}>
          <View className="flex-row items-center justify-between">
            <View className="flex-row items-center gap-2">
              <AppIcon icon={Search01Icon} size={14} color="#8e8e93" />
              <Text className="text-xs text-muted">Deep Research</Text>
            </View>
            <Chip
              size="sm"
              variant="secondary"
              color="default"
              animation="disable-all"
            >
              <Chip.Label>
                {expanded ? "Hide results" : "Show results"}
              </Chip.Label>
            </Chip>
          </View>
        </PressableFeedback>

        {/* Summary stats */}
        {(hasEnhanced || hasOriginal) && (
          <View className="flex-row gap-3 mt-2.5">
            {sourcesCount > 0 && (
              <View className="flex-row items-center gap-1">
                <AppIcon icon={Globe02Icon} size={11} color="#8e8e93" />
                <Text className="text-[11px] text-muted">
                  Researched {sourcesCount} source
                  {sourcesCount !== 1 ? "s" : ""}
                </Text>
              </View>
            )}
            {typeof data.metadata?.elapsed_time === "number" && (
              <Text className="text-[11px] text-muted">
                {data.metadata.elapsed_time.toFixed(1)}s
              </Text>
            )}
          </View>
        )}

        {/* Expanded content */}
        {expanded && (
          <View className="mt-3">
            {/* Tab bar */}
            {visibleTabs.length > 1 && (
              <View className="flex-row gap-1.5 mb-3">
                {visibleTabs.map(({ key, label, icon }) => {
                  const isActive = resolvedTab === key;
                  return (
                    <Chip
                      key={key}
                      onPress={() => setActiveTab(key)}
                      variant={isActive ? "primary" : "secondary"}
                      color={isActive ? "accent" : "default"}
                      className={isActive ? "" : "bg-white/5"}
                    >
                      <AppIcon
                        icon={icon}
                        size={12}
                        color={isActive ? "#00bbff" : "#8e8e93"}
                      />
                      <Chip.Label>{label}</Chip.Label>
                    </Chip>
                  );
                })}
              </View>
            )}

            {/* Tab content */}
            {resolvedTab === "enhanced" && hasEnhanced && (
              <EnhancedResultsSection results={data.enhanced_results!} />
            )}
            {resolvedTab === "original" && hasOriginal && (
              <OriginalSearchSection search={data.original_search!} />
            )}
            {resolvedTab === "metadata" && hasMetadata && (
              <MetadataSection metadata={data.metadata!} />
            )}
          </View>
        )}
      </Card.Body>
    </Card>
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
