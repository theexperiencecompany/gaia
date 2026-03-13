import { Card } from "heroui-native";
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

interface AlertBannerProps {
  variant: "danger" | "success" | "warning";
  children: React.ReactNode;
}

function AlertBanner({ variant, children }: AlertBannerProps) {
  const bgColors = {
    danger: "rgba(255,59,48,0.12)",
    success: "rgba(52,199,89,0.12)",
    warning: "rgba(255,159,10,0.12)",
  };
  const borderColors = {
    danger: "rgba(255,59,48,0.25)",
    success: "rgba(52,199,89,0.25)",
    warning: "rgba(255,159,10,0.25)",
  };

  return (
    <View
      style={{
        backgroundColor: bgColors[variant],
        borderWidth: 1,
        borderColor: borderColors[variant],
        borderRadius: 12,
        padding: 12,
        gap: 4,
      }}
    >
      {children}
    </View>
  );
}

export function TestConnectionResult({
  isLoading,
  result,
  error,
}: TestConnectionResultProps) {
  const { fontSize, spacing } = useResponsive();

  if (isLoading) {
    return (
      <Card variant="secondary" animation="disable-all" className="rounded-xl">
        <Card.Body className="flex-row items-center gap-2 py-3">
          <ActivityIndicator size="small" color="#00bbff" />
          <Text style={{ fontSize: fontSize.sm, color: "#8e8e93" }}>
            Testing connection...
          </Text>
        </Card.Body>
      </Card>
    );
  }

  if (error) {
    return (
      <AlertBanner variant="danger">
        <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
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
      </AlertBanner>
    );
  }

  if (!result) return null;

  if (result.status === "connected") {
    const toolCount = result.tools_count ?? 0;

    return (
      <AlertBanner variant="success">
        <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
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
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: spacing.xs,
          }}
        >
          <AppIcon icon={Wrench01Icon} size={13} color="#8e8e93" />
          <Text style={{ fontSize: fontSize.xs, color: "#8e8e93" }}>
            {toolCount === 0
              ? "No tools discovered"
              : `${toolCount} tool${toolCount !== 1 ? "s" : ""} discovered`}
          </Text>
        </View>
      </AlertBanner>
    );
  }

  if (result.status === "requires_oauth") {
    return (
      <AlertBanner variant="warning">
        <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
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
      </AlertBanner>
    );
  }

  // status === "failed"
  return (
    <AlertBanner variant="danger">
      <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
        <AppIcon icon={Alert01Icon} size={16} color="#ff3b30" />
        <Text
          style={{ fontSize: fontSize.sm, fontWeight: "600", color: "#ff3b30" }}
        >
          Connection Failed
        </Text>
      </View>
      {result.error ? (
        <Text style={{ fontSize: fontSize.xs, color: "#ff6b6b" }}>
          {result.error}
        </Text>
      ) : null}
    </AlertBanner>
  );
}
