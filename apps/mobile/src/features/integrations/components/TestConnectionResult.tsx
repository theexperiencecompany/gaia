import { Alert, Card } from "heroui-native";
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
      <Alert variant="danger" className="rounded-xl">
        <AppIcon icon={Alert01Icon} size={16} color="#ff3b30" />
        <Alert.Title
          style={{ fontSize: fontSize.sm, fontWeight: "600", color: "#ff3b30" }}
        >
          Connection Failed
        </Alert.Title>
        <Text style={{ fontSize: fontSize.xs, color: "#ff6b6b" }}>{error}</Text>
      </Alert>
    );
  }

  if (!result) return null;

  if (result.status === "connected") {
    const toolCount = result.tools_count ?? 0;

    return (
      <Alert variant="success" className="rounded-xl">
        <AppIcon icon={CheckmarkCircle02Icon} size={16} color="#34c759" />
        <Alert.Title
          style={{ fontSize: fontSize.sm, fontWeight: "600", color: "#34c759" }}
        >
          Connected Successfully
        </Alert.Title>
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
      </Alert>
    );
  }

  if (result.status === "requires_oauth") {
    return (
      <Alert variant="warning" className="rounded-xl">
        <AppIcon icon={Alert01Icon} size={16} color="#ff9f0a" />
        <Alert.Title
          style={{ fontSize: fontSize.sm, fontWeight: "600", color: "#ff9f0a" }}
        >
          OAuth Required
        </Alert.Title>
        <Text style={{ fontSize: fontSize.xs, color: "#c9934a" }}>
          This integration requires OAuth authorization. Save it first, then
          connect from the integrations list.
        </Text>
      </Alert>
    );
  }

  // status === "failed"
  return (
    <Alert variant="danger" className="rounded-xl">
      <AppIcon icon={Alert01Icon} size={16} color="#ff3b30" />
      <Alert.Title
        style={{ fontSize: fontSize.sm, fontWeight: "600", color: "#ff3b30" }}
      >
        Connection Failed
      </Alert.Title>
      {result.error ? (
        <Text style={{ fontSize: fontSize.xs, color: "#ff6b6b" }}>
          {result.error}
        </Text>
      ) : null}
    </Alert>
  );
}
