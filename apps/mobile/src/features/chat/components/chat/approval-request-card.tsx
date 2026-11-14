import type {
  ApprovalDecision,
  ApprovalLabels,
  ApprovalRequestData,
  ApprovalScope,
} from "@gaia/shared/chat";
import { approvalLabel } from "@gaia/shared/chat";
import { endAfterDecision, flattenArgsPreview } from "@gaia/shared/utils";
import * as Haptics from "expo-haptics";
import { Button, Chip } from "heroui-native";
import { useState } from "react";
import { Alert, Pressable, TextInput, View } from "react-native";
import {
  AlertCircleIcon,
  AppIcon,
  Cancel01Icon,
  CheckmarkCircle02Icon,
  Clock01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { chatApi } from "@/features/chat/api/chat-api";
import {
  APPROVAL_RESOLVED_META,
  approvalOutcomeText,
} from "@/features/chat/utils/approval-status";

interface ApprovalRequestCardProps {
  data: ApprovalRequestData;
}

/** Icons for every way an approval ends; labels and colors live in APPROVAL_RESOLVED_META. */
const RESOLVED_ICONS: ApprovalLabels<typeof Cancel01Icon> = {
  pending: AlertCircleIcon,
  autoApproved: CheckmarkCircle02Icon,
  outcome: {
    approved: CheckmarkCircle02Icon,
    denied: Cancel01Icon,
    expired: Clock01Icon,
    cancelled: Cancel01Icon,
    withdrawn: Cancel01Icon,
  },
  action: {
    executing: CheckmarkCircle02Icon,
    executed: CheckmarkCircle02Icon,
    failed: Cancel01Icon,
    unknown: AlertCircleIcon,
  },
};

function ArgsPreview({ args }: { args: Record<string, unknown> }) {
  const { rows, omitted } = flattenArgsPreview(args);
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
      {rows.map((row, index) => {
        const showGroup =
          row.group !== null && row.group !== (rows[index - 1]?.group ?? null);
        return (
          <View key={`${row.group ?? "top"}:${row.key}:${row.value}`}>
            {showGroup && row.group !== null ? (
              <Text
                style={{
                  fontSize: 11,
                  fontWeight: "500",
                  color: "#a1a1aa",
                  textTransform: "uppercase",
                  marginBottom: 2,
                }}
              >
                {row.group}
              </Text>
            ) : null}
            <View style={{ flexDirection: "row", gap: 8 }}>
              <Text style={{ fontSize: 12, color: "#71717a" }}>
                {row.key.replace(/^./, (char) => char.toUpperCase())}
              </Text>
              <Text
                style={{
                  flex: 1,
                  fontSize: 12,
                  color: "#d4d4d8",
                  textAlign: "right",
                }}
                numberOfLines={2}
              >
                {row.value}
              </Text>
            </View>
          </View>
        );
      })}
      {omitted > 0 ? (
        <Text style={{ fontSize: 11, color: "#71717a" }}>+{omitted} more</Text>
      ) : null}
    </View>
  );
}

export function ApprovalRequestCard({
  data: incoming,
}: ApprovalRequestCardProps) {
  const [submitting, setSubmitting] = useState<ApprovalDecision | null>(null);
  // The decision response settles the card on its own: the resolved frame is
  // best-effort and may never arrive. A real frame outranks it (executed/failed).
  const [settled, setSettled] = useState<Pick<
    ApprovalRequestData,
    "outcome" | "decider" | "action" | "feedback"
  > | null>(null);
  const data: ApprovalRequestData =
    incoming.outcome == null && settled
      ? { ...incoming, ...settled }
      : incoming;
  const [denyOpen, setDenyOpen] = useState(false);
  const [feedback, setFeedback] = useState("");

  const decide = async (
    decision: ApprovalDecision,
    scope: ApprovalScope = "once",
  ) => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    setSubmitting(decision);
    try {
      // Reaching the catch means the submit genuinely failed.
      const outcome = await chatApi.postApprovalDecision(data.approval_id, {
        decision,
        feedback: feedback.trim() || undefined,
        scope,
      });
      const end = endAfterDecision(decision, outcome);
      if (end === null) {
        setSubmitting(null);
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
        Alert.alert(
          "Approval moved",
          "That approval already moved — tap again to confirm.",
        );
        return;
      }
      setSettled({
        ...end,
        feedback:
          outcome.success && decision === "deny"
            ? feedback.trim() || null
            : null,
      });
    } catch {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      Alert.alert(
        "Couldn't submit",
        "Your decision didn't go through. Please try again.",
      );
      setSubmitting(null);
    }
  };

  const isAuto = data.outcome === "approved" && data.decider === "auto";

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
        <AppIcon
          icon={isAuto ? CheckmarkCircle02Icon : AlertCircleIcon}
          size={18}
          color={isAuto ? "#34d399" : "#fbbf24"}
        />
        <View style={{ flex: 1 }}>
          <Text style={{ color: "#f4f4f5", fontSize: 14 }} numberOfLines={2}>
            {data.summary}
          </Text>
          <Text style={{ color: "#71717a", fontSize: 12 }}>
            {isAuto ? "Ran without asking" : "Approval required"}
          </Text>
        </View>
      </View>
      <ArgsPreview args={data.args_preview} />
      {children}
    </View>
  );

  const meta = approvalLabel(data, APPROVAL_RESOLVED_META);
  if (meta !== null) {
    const icon = approvalLabel(data, RESOLVED_ICONS);
    return shell(
      <View style={{ marginTop: 12, gap: 6 }}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
          <AppIcon icon={icon} size={18} color={meta.color} />
          <Chip size="sm" variant="soft">
            <Chip.Label>{meta.label}</Chip.Label>
          </Chip>
        </View>
        <Text style={{ fontSize: 12, color: "#a1a1aa" }} numberOfLines={2}>
          {approvalOutcomeText(data)}
        </Text>
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
      {!data.always_asks && (
        <Pressable
          onPress={() => decide("approve", "always_tool")}
          disabled={submitting !== null}
          hitSlop={8}
        >
          <Text style={{ fontSize: 12, color: "#71717a" }}>
            Always allow this tool
          </Text>
        </Pressable>
      )}
    </View>,
  );
}
