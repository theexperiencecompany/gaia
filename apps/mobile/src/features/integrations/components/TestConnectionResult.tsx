import { ActivityIndicator, View } from "react-native";
import {
  Alert01Icon,
  AppIcon,
  CheckmarkCircle02Icon,
  Wrench01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import type { TestConnectionResponse } from "../api/integrations-api";

interface TestConnectionResultProps {
  isLoading: boolean;
  result: TestConnectionResponse | null;
  error: string | null;
}

export function TestConnectionResult({
  isLoading,
  result,
  error,
}: TestConnectionResultProps) {
  const { fontSize, spacing, moderateScale } = useResponsive();

  if (isLoading) {
    return (
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: spacing.sm,
          backgroundColor: "rgba(255,255,255,0.04)",
          borderRadius: moderateScale(12, 0.5),
          padding: spacing.md,
        }}
      >
        <ActivityIndicator size="small" color="#00bbff" />
        <Text style={{ fontSize: fontSize.sm, color: "#8e8e93" }}>
          Testing connection...
        </Text>
      </View>
    );
  }

  if (error) {
    return (
      <View
        style={{
          backgroundColor: "rgba(255,59,48,0.08)",
          borderRadius: moderateScale(12, 0.5),
          padding: spacing.md,
          gap: spacing.sm,
        }}
      >
        <View
          style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}
        >
          <AppIcon icon={Alert01Icon} size={16} color="#ff3b30" />
          <Text
            style={{
              fontSize: fontSize.sm,
              fontWeight: "600",
              color: "#ff3b30",
            }}
          >
            Connection Failed
          </Text>
        </View>
        <Text style={{ fontSize: fontSize.xs, color: "#ff6b6b" }}>{error}</Text>
      </View>
    );
  }

  if (!result) return null;

  if (result.status === "connected") {
    const toolCount = result.tools_count ?? 0;

    return (
      <View
        style={{
          backgroundColor: "rgba(52,199,89,0.08)",
          borderRadius: moderateScale(12, 0.5),
          padding: spacing.md,
          gap: spacing.sm,
        }}
      >
        <View
          style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}
        >
          <AppIcon icon={CheckmarkCircle02Icon} size={16} color="#34c759" />
          <Text
            style={{
              fontSize: fontSize.sm,
              fontWeight: "600",
              color: "#34c759",
            }}
          >
            Connected Successfully
          </Text>
        </View>

        <View
          style={{ flexDirection: "row", alignItems: "center", gap: spacing.xs }}
        >
          <AppIcon icon={Wrench01Icon} size={13} color="#8e8e93" />
          <Text style={{ fontSize: fontSize.xs, color: "#8e8e93" }}>
            {toolCount === 0
              ? "No tools discovered"
              : `${toolCount} tool${toolCount !== 1 ? "s" : ""} discovered`}
          </Text>
        </View>
      </View>
    );
  }

  if (result.status === "requires_oauth") {
    return (
      <View
        style={{
          backgroundColor: "rgba(255,159,10,0.08)",
          borderRadius: moderateScale(12, 0.5),
          padding: spacing.md,
          gap: spacing.sm,
        }}
      >
        <View
          style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}
        >
          <AppIcon icon={Alert01Icon} size={16} color="#ff9f0a" />
          <Text
            style={{
              fontSize: fontSize.sm,
              fontWeight: "600",
              color: "#ff9f0a",
            }}
          >
            OAuth Required
          </Text>
        </View>
        <Text style={{ fontSize: fontSize.xs, color: "#c9934a" }}>
          This integration requires OAuth authorization. Save it first, then
          connect from the integrations list.
        </Text>
      </View>
    );
  }

  // status === "failed"
  return (
    <View
      style={{
        backgroundColor: "rgba(255,59,48,0.08)",
        borderRadius: moderateScale(12, 0.5),
        padding: spacing.md,
        gap: spacing.sm,
      }}
    >
      <View
        style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}
      >
        <AppIcon icon={Alert01Icon} size={16} color="#ff3b30" />
        <Text
          style={{
            fontSize: fontSize.sm,
            fontWeight: "600",
            color: "#ff3b30",
          }}
        >
          Connection Failed
        </Text>
      </View>
      {result.error && (
        <Text style={{ fontSize: fontSize.xs, color: "#ff6b6b" }}>
          {result.error}
        </Text>
      )}
    </View>
  );
}
