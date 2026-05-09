import { Image } from "expo-image";
import { PressableFeedback } from "heroui-native";
import { useState } from "react";
import { ActivityIndicator, Pressable, View } from "react-native";
import {
  AppIcon,
  Clock04Icon,
  PackageOpenIcon,
  UserCircle02Icon,
  UserIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { getIntegrationLogo } from "../constants/logos";
import { useAddPublicIntegration } from "../hooks/useCommunityIntegrations";
import type { CommunityIntegration } from "../types";

interface CommunityIntegrationCardProps {
  integration: CommunityIntegration;
  onPress?: (integration: CommunityIntegration) => void;
}

function formatRelative(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  const diff = Math.max(0, Date.now() - date.getTime());
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;
  const month = 30 * day;
  const year = 365 * day;

  if (diff < minute) return "just now";
  if (diff < hour) {
    const m = Math.floor(diff / minute);
    return `${m}m ago`;
  }
  if (diff < day) {
    const h = Math.floor(diff / hour);
    return `${h}h ago`;
  }
  if (diff < month) {
    const d = Math.floor(diff / day);
    return `${d}d ago`;
  }
  if (diff < year) {
    const mo = Math.floor(diff / month);
    return `${mo}mo ago`;
  }
  const y = Math.floor(diff / year);
  return `${y}y ago`;
}

function formatCloneCount(count: number): string {
  if (count >= 1000) return `${(count / 1000).toFixed(1)}k`;
  return count.toString();
}

function formatCategory(category: string | undefined | null): string {
  if (!category) return "";
  const lower = category.toLowerCase();
  // Special-cases for acronym-heavy categories.
  if (lower === "ai/ml" || lower === "ai-ml" || lower === "ai_ml") {
    return "AI/ML";
  }
  // Title-case each word (split on -, _, space).
  return lower
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function CardLogo({ integration }: { integration: CommunityIntegration }) {
  const [errored, setErrored] = useState(false);
  const logoUri = getIntegrationLogo(
    integration.integrationId,
    integration.iconUrl,
  );

  if (logoUri && !errored) {
    return (
      <View
        className="items-center justify-center bg-zinc-900"
        style={{
          width: 40,
          height: 40,
          borderRadius: 12,
          overflow: "hidden",
        }}
      >
        <Image
          source={{ uri: logoUri }}
          style={{ width: 28, height: 28 }}
          contentFit="contain"
          onError={() => setErrored(true)}
        />
      </View>
    );
  }

  return (
    <View
      className="items-center justify-center bg-zinc-700"
      style={{
        width: 40,
        height: 40,
        borderRadius: 12,
      }}
    >
      <AppIcon icon={PackageOpenIcon} size={20} color="#d4d4d8" />
    </View>
  );
}

export function CommunityIntegrationCard({
  integration,
  onPress,
}: CommunityIntegrationCardProps) {
  const { mutate: addIntegration, isPending } = useAddPublicIntegration();
  const [added, setAdded] = useState(false);
  const { fontSize } = useResponsive();

  const handleAdd = () => {
    addIntegration(
      { slug: integration.slug },
      { onSuccess: () => setAdded(true) },
    );
  };

  const isPlatform = integration.source === "platform";
  const relTime = formatRelative(integration.publishedAt);
  const cloneLabel = formatCloneCount(integration.cloneCount);

  return (
    <PressableFeedback
      onPress={() => onPress?.(integration)}
      className="rounded-3xl bg-zinc-800"
      style={{ padding: 16 }}
    >
      <View style={{ flexDirection: "row", alignItems: "flex-start", gap: 12 }}>
        <CardLogo integration={integration} />

        <View style={{ flex: 1, minWidth: 0 }}>
          <Text
            className="text-zinc-100"
            style={{ fontSize: fontSize.base, fontWeight: "600" }}
            numberOfLines={1}
          >
            {integration.name}
          </Text>
          <Text
            className="text-zinc-500"
            style={{ fontSize: fontSize.xs, marginTop: 2 }}
            numberOfLines={1}
          >
            {formatCategory(integration.category)}
          </Text>
        </View>

        <Pressable
          onPress={handleAdd}
          disabled={isPending || added}
          hitSlop={6}
          accessibilityRole="button"
          accessibilityLabel={added ? "Added" : `Add ${integration.name}`}
          style={({ pressed }) => ({
            height: 32,
            paddingHorizontal: 14,
            borderRadius: 999,
            alignItems: "center",
            justifyContent: "center",
            flexDirection: "row",
            gap: 4,
            backgroundColor: added
              ? "rgba(34,197,94,0.18)"
              : pressed
                ? "#52525b"
                : "#3f3f46",
            opacity: isPending ? 0.7 : 1,
          })}
        >
          {isPending ? (
            <ActivityIndicator size="small" color="#a1a1aa" />
          ) : (
            <Text
              style={{
                fontSize: fontSize.xs,
                fontWeight: "600",
                color: added ? "#4ade80" : "#e4e4e7",
              }}
            >
              {added ? "Added" : "Add"}
            </Text>
          )}
        </Pressable>
      </View>

      <Text
        className="text-zinc-400"
        style={{
          fontSize: fontSize.sm,
          lineHeight: fontSize.sm * 1.5,
          marginTop: 12,
        }}
        numberOfLines={2}
      >
        {integration.description}
      </Text>

      <View
        style={{
          marginTop: 12,
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
        }}
      >
        {isPlatform ? (
          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              paddingHorizontal: 10,
              paddingVertical: 4,
              borderRadius: 999,
              backgroundColor: "rgba(0,187,255,0.12)",
            }}
          >
            <Text
              style={{
                fontSize: fontSize.xs - 1,
                fontWeight: "600",
                color: "#00bbff",
                letterSpacing: 0.2,
              }}
            >
              Native
            </Text>
          </View>
        ) : (
          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: 6,
              flex: 1,
              minWidth: 0,
            }}
          >
            {integration.creator?.picture ? (
              <Image
                source={{ uri: integration.creator.picture }}
                style={{ width: 20, height: 20, borderRadius: 999 }}
                contentFit="cover"
              />
            ) : (
              <View
                style={{
                  width: 20,
                  height: 20,
                  borderRadius: 999,
                  alignItems: "center",
                  justifyContent: "center",
                  backgroundColor: "rgba(255,255,255,0.06)",
                }}
              >
                <AppIcon icon={UserCircle02Icon} size={14} color="#71717a" />
              </View>
            )}
            <Text
              className="text-zinc-500"
              style={{ fontSize: fontSize.xs, flexShrink: 1 }}
              numberOfLines={1}
            >
              {integration.creator?.name ?? "Community"}
            </Text>
          </View>
        )}

        <View style={{ flexDirection: "row", alignItems: "center", gap: 12 }}>
          {!isPlatform ? (
            <View
              style={{ flexDirection: "row", alignItems: "center", gap: 4 }}
            >
              <AppIcon icon={UserIcon} size={12} color="#71717a" />
              <Text className="text-zinc-500" style={{ fontSize: fontSize.xs }}>
                {cloneLabel}
              </Text>
            </View>
          ) : null}
          {relTime ? (
            <View
              style={{ flexDirection: "row", alignItems: "center", gap: 4 }}
            >
              <AppIcon icon={Clock04Icon} size={12} color="#71717a" />
              <Text className="text-zinc-500" style={{ fontSize: fontSize.xs }}>
                {relTime}
              </Text>
            </View>
          ) : null}
        </View>
      </View>
    </PressableFeedback>
  );
}
