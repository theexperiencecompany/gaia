import type { ApprovalRequestData, ApprovalStatus } from "@gaia/shared/chat";
import * as Haptics from "expo-haptics";
import { Button, Chip } from "heroui-native";
import { useState } from "react";
import { Pressable, TextInput, View } from "react-native";
import {
  AlertCircleIcon,
  AppIcon,
  Cancel01Icon,
  CheckmarkCircle02Icon,
  Clock01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { chatApi } from "@/features/chat/api/chat-api";

interface ApprovalRequestCardProps {
  data: ApprovalRequestData;
}

const RESOLVED: Record<
  Exclude<ApprovalStatus, "pending">,
  { icon: typeof Cancel01Icon; label: string; color: string }
> = {
  approved: {
    icon: CheckmarkCircle02Icon,
    label: "Approved",
    color: "#34d399",
  },
  denied: { icon: Cancel01Icon, label: "Declined", color: "#f87171" },
  timeout: { icon: Clock01Icon, label: "Timed out", color: "#fbbf24" },
};

function ArgsPreview({ args }: { args: Record<string, unknown> }) {
  const rows = Object.entries(args).filter(
    ([, v]) =>
      typeof v === "string" || typeof v === "number" || typeof v === "boolean",
  );
  if (rows.length === 0) return null;
  return (
    <View
      style={{
        marginTop: 12,
        borderRadius: 16,
        backgroundColor: "#18181b",
        padding: 12,
        gap: 6,
      }}
    >
      {rows.map(([key, value]) => (
        <View key={key} style={{ flexDirection: "row", gap: 8 }}>
          <Text style={{ fontSize: 12, color: "#71717a" }}>{key}</Text>
          <Text
            style={{
              flex: 1,
              fontSize: 12,
              color: "#d4d4d8",
              textAlign: "right",
            }}
            numberOfLines={1}
          >
            {String(value)}
          </Text>
        </View>
      ))}
    </View>
  );
}

export function ApprovalRequestCard({ data }: ApprovalRequestCardProps) {
  const [submitting, setSubmitting] = useState<"approve" | "deny" | null>(null);
  const [denyOpen, setDenyOpen] = useState(false);
  const [feedback, setFeedback] = useState("");

  const decide = async (
    decision: "approve" | "deny",
    scope: "once" | "always_tool" = "once",
  ) => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    setSubmitting(decision);
    // The resolved frame replaces this card over the stream; reset local state
    // only if the request itself failed (a 410 still resolves the card).
    const ok = await chatApi.postApprovalDecision(data.approval_id, {
      decision,
      feedback: feedback.trim() || undefined,
      scope,
    });
    if (!ok) setSubmitting(null);
  };

  const shell = (children: React.ReactNode) => (
    <View
      style={{
        marginHorizontal: 16,
        marginVertical: 4,
        borderRadius: 24,
        backgroundColor: "#27272a",
        padding: 16,
      }}
    >
      <View style={{ flexDirection: "row", alignItems: "flex-start", gap: 8 }}>
        <AppIcon icon={AlertCircleIcon} size={18} color="#fbbf24" />
        <View style={{ flex: 1 }}>
          <Text style={{ color: "#f4f4f5", fontSize: 14 }} numberOfLines={2}>
            {data.summary}
          </Text>
          <Text style={{ color: "#71717a", fontSize: 12 }}>
            Approval required
          </Text>
        </View>
      </View>
      <ArgsPreview args={data.args_preview} />
      {children}
    </View>
  );

  if (data.status !== "pending") {
    const meta = RESOLVED[data.status];
    return shell(
      <View
        style={{
          marginTop: 12,
          flexDirection: "row",
          alignItems: "center",
          gap: 8,
        }}
      >
        <AppIcon icon={meta.icon} size={18} color={meta.color} />
        <Chip size="sm" variant="soft">
          <Chip.Label>{meta.label}</Chip.Label>
        </Chip>
        {data.feedback ? (
          <Text
            style={{ flex: 1, fontSize: 12, color: "#a1a1aa" }}
            numberOfLines={1}
          >
            {data.feedback}
          </Text>
        ) : null}
      </View>,
    );
  }

  return shell(
    <View style={{ marginTop: 12, gap: 8 }}>
      {denyOpen && (
        <TextInput
          value={feedback}
          onChangeText={setFeedback}
          placeholder="Optional: tell GAIA why (or what to do instead)"
          placeholderTextColor="#71717a"
          style={{
            borderRadius: 12,
            backgroundColor: "#18181b",
            paddingHorizontal: 12,
            paddingVertical: 8,
            color: "#e4e4e7",
            fontSize: 14,
          }}
        />
      )}
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
        <Button
          variant="primary"
          size="sm"
          isDisabled={submitting !== null}
          onPress={() => decide("approve")}
        >
          <Button.Label>
            {submitting === "approve" ? "Approving..." : "Approve"}
          </Button.Label>
        </Button>
        <Button
          variant="secondary"
          size="sm"
          isDisabled={submitting !== null}
          onPress={() => (denyOpen ? decide("deny") : setDenyOpen(true))}
        >
          <Button.Label>
            {submitting === "deny" ? "Declining..." : "Deny"}
          </Button.Label>
        </Button>
      </View>
      <Pressable
        onPress={() => decide("approve", "always_tool")}
        disabled={submitting !== null}
        hitSlop={8}
      >
        <Text style={{ fontSize: 12, color: "#71717a" }}>
          Always allow this tool
        </Text>
      </Pressable>
    </View>,
  );
}
