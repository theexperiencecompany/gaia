import { useState } from "react";
import { Pressable, ScrollView, TextInput, View } from "react-native";
import {
  AppIcon,
  Cancel01Icon,
  Comment01Icon,
  HelpCircleIcon,
  PencilEdit01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  ToolCardInner,
  ToolCardShell,
} from "@/features/chat/tool-data/primitives";

export type SupportTicketType = "support" | "feature";

export interface SupportTicketData {
  type?: SupportTicketType;
  title?: string;
  description?: string;
  status?: string;
  priority?: "high" | "medium" | "low" | "critical";
  user_name?: string;
  user_email?: string;
}

// -- Priority config -----------------------------------------------------------

const PRIORITY_CONFIG: Record<
  string,
  { bg: string; text: string; label: string }
> = {
  critical: {
    bg: "bg-red-500/15",
    text: "text-red-400",
    label: "Critical Priority",
  },
  high: { bg: "bg-red-500/15", text: "text-red-400", label: "High Priority" },
  medium: {
    bg: "bg-amber-400/10",
    text: "text-amber-400",
    label: "Medium Priority",
  },
  low: { bg: "bg-primary/10", text: "text-primary", label: "Low Priority" },
};

// -- Status config -------------------------------------------------------------

const STATUS_CONFIG: Record<
  string,
  { bg: string; text: string; label: string }
> = {
  open: { bg: "bg-emerald-400/10", text: "text-emerald-400", label: "Open" },
  closed: { bg: "bg-zinc-700/50", text: "text-zinc-400", label: "Closed" },
  pending: {
    bg: "bg-amber-400/10",
    text: "text-amber-400",
    label: "Pending",
  },
  resolved: {
    bg: "bg-primary/10",
    text: "text-primary",
    label: "Resolved",
  },
};

// -- Divider ------------------------------------------------------------------

function Divider() {
  return <View className="h-px bg-zinc-700/50 my-1.5" />;
}

// -- Pill badge ---------------------------------------------------------------

function Pill({
  bg,
  text,
  label,
}: {
  bg: string;
  text: string;
  label: string;
}) {
  return (
    <View className={`self-start rounded-full px-2.5 py-0.5 ${bg}`}>
      <Text className={`text-xs font-medium ${text}`}>{label}</Text>
    </View>
  );
}

// -- Edit sheet (inline, no modal dependency) ---------------------------------

function EditSheet({
  editData,
  onSave,
  onClose,
}: {
  editData: SupportTicketData;
  onSave: (updated: SupportTicketData) => void;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState<SupportTicketData>(editData);

  return (
    <ToolCardShell className="mt-2">
      {/* Sheet header */}
      <View className="flex-row items-center justify-between mb-3">
        <Text className="text-zinc-100 text-sm font-semibold">Edit Ticket</Text>
        <Pressable onPress={onClose} hitSlop={8} className="p-1">
          <AppIcon icon={Cancel01Icon} size={16} color="#71717a" />
        </Pressable>
      </View>

      {/* Type toggle */}
      <Text className="text-zinc-400 text-xs mb-1.5">Type</Text>
      <View className="flex-row gap-2 mb-3">
        {(["support", "feature"] as SupportTicketType[]).map((t) => (
          <Pressable
            key={t}
            onPress={() => setDraft({ ...draft, type: t })}
            className={`flex-1 rounded-xl py-2 items-center ${
              draft.type === t ? "bg-primary" : "bg-zinc-800"
            }`}
          >
            <Text
              className={`text-xs font-semibold ${
                draft.type === t ? "text-black" : "text-zinc-200"
              }`}
            >
              {t === "feature" ? "Feature Request" : "Support"}
            </Text>
          </Pressable>
        ))}
      </View>

      {/* Title input */}
      <Text className="text-zinc-400 text-xs mb-1.5">Title</Text>
      <View className="rounded-xl bg-zinc-800 px-3 py-2 mb-3">
        <TextInput
          value={draft.title ?? ""}
          onChangeText={(v) => setDraft({ ...draft, title: v })}
          placeholder="Brief description of your issue"
          placeholderTextColor="#71717a"
          style={{
            color: "#f4f4f5",
            fontSize: 14,
            paddingVertical: 0,
          }}
        />
      </View>

      {/* Description input */}
      <Text className="text-zinc-400 text-xs mb-1.5">Description</Text>
      <View className="rounded-xl bg-zinc-800 px-3 py-2 mb-4">
        <TextInput
          value={draft.description ?? ""}
          onChangeText={(v) => setDraft({ ...draft, description: v })}
          placeholder="Detailed information about your issue or request"
          placeholderTextColor="#71717a"
          multiline
          numberOfLines={4}
          textAlignVertical="top"
          style={{
            color: "#f4f4f5",
            fontSize: 14,
            paddingVertical: 0,
            minHeight: 80,
          }}
        />
      </View>

      {/* Action buttons */}
      <View className="flex-row justify-end gap-2">
        <Pressable
          onPress={onClose}
          className="rounded-full bg-zinc-800 px-4 py-2"
        >
          <Text className="text-zinc-200 text-sm font-medium">Cancel</Text>
        </Pressable>
        <Pressable
          onPress={() => onSave(draft)}
          className="rounded-full bg-primary px-4 py-2"
          android_ripple={{ color: "rgba(0,0,0,0.1)" }}
        >
          <Text className="text-black text-sm font-medium">Save</Text>
        </Pressable>
      </View>
    </ToolCardShell>
  );
}

// -- Card ---------------------------------------------------------------------

export function SupportTicketCard({ data }: { data: SupportTicketData }) {
  const [editData, setEditData] = useState<SupportTicketData>(data);
  const [isEditing, setIsEditing] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const isFeature = editData.type === "feature";
  const typeLabel = isFeature ? "Feature Request" : "Support Ticket";

  const priorityInfo =
    editData.priority && PRIORITY_CONFIG[editData.priority]
      ? PRIORITY_CONFIG[editData.priority]
      : null;

  const statusKey = (editData.status ?? "open").toLowerCase();
  const statusInfo = STATUS_CONFIG[statusKey] ?? STATUS_CONFIG.open;

  const handleSave = (updated: SupportTicketData) => {
    setEditData(updated);
    setIsEditing(false);
  };

  const handleSubmit = async () => {
    if (isSubmitting) return;
    setIsSubmitting(true);
    try {
      // Submit logic is handled by the parent or API layer
      // Kept as a no-op placeholder consistent with web's supportApi call
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <>
      {/* Outer uses rounded-3xl to match web's rounded-3xl bg-zinc-800 */}
      <View className="rounded-3xl bg-zinc-800 mx-4 my-1 overflow-hidden">
        {/* Header row — type icon + chip + status */}
        <View className="flex-row items-center gap-2 px-4 pt-4 pb-2">
          <View
            className={`rounded-full p-1 ${isFeature ? "bg-emerald-400/10" : "bg-primary/10"}`}
          >
            <AppIcon
              icon={isFeature ? Comment01Icon : HelpCircleIcon}
              size={14}
              color={isFeature ? "#34d399" : "#00bbff"}
            />
          </View>
          <Pill
            bg={isFeature ? "bg-emerald-400/10" : "bg-primary/10"}
            text={isFeature ? "text-emerald-400" : "text-primary"}
            label={typeLabel}
          />
          <View className="ml-auto">
            <Pill
              bg={statusInfo.bg}
              text={statusInfo.text}
              label={statusInfo.label}
            />
          </View>
        </View>

        <View className="px-4 pb-4 flex-col gap-1">
          {/* Title row with edit button */}
          <View className="flex-row items-center justify-between mb-1">
            <Text className="text-zinc-100 text-lg font-semibold flex-1 mr-2">
              {editData.title ?? "Untitled Ticket"}
            </Text>
            <Pressable
              hitSlop={8}
              className="p-1"
              onPress={() => setIsEditing(true)}
            >
              <AppIcon icon={PencilEdit01Icon} size={16} color="#71717a" />
            </Pressable>
          </View>

          <Divider />

          {/* Priority pill — shown inline below title, above user info */}
          {priorityInfo ? (
            <View className="mt-1 mb-2">
              <Pill
                bg={priorityInfo.bg}
                text={priorityInfo.text}
                label={priorityInfo.label}
              />
            </View>
          ) : null}

          {/* User info */}
          {editData.user_name || editData.user_email ? (
            <>
              <View className="flex-row items-center gap-1.5 mb-2">
                <Text className="text-zinc-400 text-sm">From:</Text>
                <Text className="text-zinc-200 text-sm font-medium">
                  {editData.user_name ?? editData.user_email}
                  {editData.user_name && editData.user_email ? (
                    <Text className="text-zinc-500 text-sm font-normal">
                      {" "}
                      ({editData.user_email})
                    </Text>
                  ) : null}
                </Text>
              </View>
              <Divider />
            </>
          ) : null}

          {/* Description — scrollable, matches web's ScrollShadow */}
          {editData.description ? (
            <ScrollView
              className="mt-1 mb-3 max-h-40"
              showsVerticalScrollIndicator={false}
              nestedScrollEnabled
            >
              <ToolCardInner dense>
                <Text className="text-zinc-200 text-sm leading-relaxed">
                  {editData.description}
                </Text>
              </ToolCardInner>
            </ScrollView>
          ) : null}

          {/* Submit button — right-aligned, rounded-full, matches web */}
          <View className="flex-row justify-end">
            <Pressable
              className={`rounded-full px-4 py-2 ${isSubmitting ? "bg-primary/50" : "bg-primary"}`}
              onPress={handleSubmit}
              android_ripple={{ color: "rgba(0,0,0,0.1)" }}
              disabled={isSubmitting}
            >
              <Text className="text-black text-sm font-medium">
                {isSubmitting ? "Submitting…" : "Submit Ticket"}
              </Text>
            </Pressable>
          </View>
        </View>
      </View>

      {/* Inline edit form — shown below the card when editing */}
      {isEditing ? (
        <EditSheet
          editData={editData}
          onSave={handleSave}
          onClose={() => setIsEditing(false)}
        />
      ) : null}
    </>
  );
}
