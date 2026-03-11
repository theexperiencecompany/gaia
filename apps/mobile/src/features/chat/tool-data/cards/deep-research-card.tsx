import { Card } from "heroui-native";
import { useState } from "react";
import { Image, Linking, Pressable, View } from "react-native";
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

export interface DeepResearchResults {
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

function EnhancedResultRow({ result }: { result: EnhancedWebResult }) {
  const [showFull, setShowFull] = useState(false);
  const hostname = getHostname(result.url);
  const hasFullContent = !!result.full_content;

  return (
    <View className="py-3 border-b border-white/8">
      {/* Title */}
      <Pressable
        onPress={() => result.url && Linking.openURL(result.url)}
        className="active:opacity-70"
      >
        <Text className="text-sm font-medium text-[#00bbff]" numberOfLines={2}>
          {result.title || hostname || "Untitled"}
        </Text>
      </Pressable>

      {/* Domain row */}
      <View className="flex-row items-center gap-1.5 mt-1">
        <FaviconImage url={result.url} />
        <Pressable
          onPress={() => result.url && Linking.openURL(result.url)}
          className="flex-row items-center gap-1 active:opacity-70"
        >
          <Text className="text-[11px] text-muted" numberOfLines={1}>
            {hostname}
          </Text>
          <AppIcon icon={ArrowUpRight01Icon} size={10} color="#8e8e93" />
        </Pressable>
      </View>

      {/* Snippet */}
      {!!result.content && (
        <Text
          className="text-xs text-muted leading-4 mt-1.5"
          numberOfLines={showFull ? undefined : 3}
        >
          {result.content}
        </Text>
      )}

      {/* Full content toggle */}
      {hasFullContent && (
        <Pressable
          onPress={() => setShowFull((prev) => !prev)}
          className="mt-1.5 active:opacity-70"
        >
          <Text className="text-[11px] text-[#00bbff] font-medium">
            {showFull ? "Show less" : "Show full content"}
          </Text>
        </Pressable>
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
            <Pressable
              key={result.url || result.title || String(index)}
              onPress={() => result.url && Linking.openURL(result.url)}
              className={`py-3 active:opacity-70 ${
                index < visible.length - 1 ? "border-b border-white/8" : ""
              }`}
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
            </Pressable>
          ))}
        </View>
      )}

      {webResults.length > 3 && (
        <Pressable
          onPress={() => setExpanded((prev) => !prev)}
          className="mt-2 py-1.5 items-center active:opacity-70"
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

export function DeepResearchCard({ data }: { data: DeepResearchResults }) {
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

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        {/* Header */}
        <Pressable
          onPress={() => setExpanded((prev) => !prev)}
          className="active:opacity-70"
        >
          <View className="flex-row items-center justify-between">
            <View className="flex-row items-center gap-2">
              <AppIcon icon={Search01Icon} size={14} color="#8e8e93" />
              <Text className="text-xs text-muted">Deep Research</Text>
            </View>
            <View className="rounded-lg bg-white/10 px-3 py-1">
              <Text className="text-xs text-foreground font-medium">
                {expanded ? "Hide results" : "Show results"}
              </Text>
            </View>
          </View>
        </Pressable>

        {/* Summary stats */}
        {(hasEnhanced || hasOriginal) && (
          <View className="flex-row gap-3 mt-2.5">
            {hasEnhanced && (
              <View className="flex-row items-center gap-1">
                <AppIcon icon={LinkSquare01Icon} size={11} color="#8e8e93" />
                <Text className="text-[11px] text-muted">
                  {data.enhanced_results!.length} enhanced result
                  {data.enhanced_results!.length !== 1 ? "s" : ""}
                </Text>
              </View>
            )}
            {hasOriginal && (data.original_search?.web?.length ?? 0) > 0 && (
              <View className="flex-row items-center gap-1">
                <AppIcon icon={Globe02Icon} size={11} color="#8e8e93" />
                <Text className="text-[11px] text-muted">
                  {data.original_search!.web!.length} web result
                  {data.original_search!.web!.length !== 1 ? "s" : ""}
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
                    <Pressable
                      key={key}
                      onPress={() => setActiveTab(key)}
                      className={`flex-row items-center gap-1.5 rounded-full px-3 py-1.5 active:opacity-70 ${
                        isActive ? "bg-[#00bbff]/20" : "bg-white/5"
                      }`}
                    >
                      <AppIcon
                        icon={icon}
                        size={12}
                        color={isActive ? "#00bbff" : "#8e8e93"}
                      />
                      <Text
                        className={`text-xs font-medium ${
                          isActive ? "text-[#00bbff]" : "text-muted"
                        }`}
                      >
                        {label}
                      </Text>
                    </Pressable>
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
