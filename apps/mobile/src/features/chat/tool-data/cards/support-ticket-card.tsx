import { BottomSheetTextInput } from "@gorhom/bottom-sheet";
import { useState } from "react";
import { Alert, Pressable, ScrollView, View } from "react-native";
import {
  AppIcon,
  CheckmarkCircle01Icon,
  Comment01Icon,
  HelpCircleIcon,
  PencilEdit01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";
import { apiService } from "@/lib/api";

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

interface SupportApiResponse {
  success: boolean;
  message: string;
  ticket_id?: string;
}

async function submitSupportRequest(
  payload: Pick<SupportTicketData, "type" | "title" | "description">,
): Promise<SupportApiResponse> {
  try {
    return await apiService.post<SupportApiResponse>(
      "support/requests",
      payload,
    );
  } catch (_error) {
    return {
      success: false,
      message: "Failed to submit support request",
    };
  }
}

function validate(data: SupportTicketData): string | null {
  if (!data.type) return "Type is required";
  if (!data.title || data.title.trim().length === 0)
    return "Title is required";
  if (data.title.length > 200) return "Title must be under 200 characters";
  if (!data.description || data.description.trim().length < 10)
    return "Description must be at least 10 characters";
  if (data.description.length > 5000)
    return "Description must be under 5,000 characters";
  return null;
}

export function SupportTicketCard({ data }: { data: SupportTicketData }) {
  const [ticket, setTicket] = useState<SupportTicketData>({
    type: data.type ?? "support",
    title: data.title ?? "",
    description: data.description ?? "",
    user_name: data.user_name,
    user_email: data.user_email,
  });
  const [draft, setDraft] = useState<SupportTicketData>(ticket);
  const [isSheetOpen, setIsSheetOpen] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSubmitted, setIsSubmitted] = useState(false);

  const isFeature = ticket.type === "feature";
  const typeLabel = isFeature ? "Feature Request" : "Support Ticket";
  const accentColor = isFeature ? "#22c55e" : "#00bbff";
  const chipBg = isFeature ? "rgba(34,197,94,0.15)" : "rgba(0,187,255,0.15)";

  const openEdit = () => {
    setDraft(ticket);
    setIsSheetOpen(true);
  };

  const saveDraft = () => {
    const error = validate(draft);
    if (error) {
      Alert.alert("Invalid ticket", error);
      return;
    }
    setTicket({ ...ticket, ...draft });
    setIsSheetOpen(false);
  };

  const handleSubmit = async () => {
    const error = validate(ticket);
    if (error) {
      Alert.alert("Invalid ticket", error);
      return;
    }
    setIsSubmitting(true);
    try {
      const result = await submitSupportRequest({
        type: ticket.type,
        title: ticket.title,
        description: ticket.description,
      });
      if (result.success) {
        setIsSubmitted(true);
        Alert.alert(
          "Ticket submitted",
          result.ticket_id
            ? `Ticket ID: ${result.ticket_id}`
            : "Your ticket has been submitted.",
        );
      } else {
        Alert.alert(
          "Submission failed",
          result.message || "Failed to submit support ticket.",
        );
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <>
      <View className="mx-4 my-2 w-full max-w-xl rounded-3xl bg-zinc-800 overflow-hidden">
        {/* Header */}
        <View className="flex-row items-center gap-2 px-6 pt-4 pb-2">
          <AppIcon
            icon={isFeature ? Comment01Icon : HelpCircleIcon}
            size={18}
            color={accentColor}
          />
          <View
            className="rounded-full px-2.5 py-0.5"
            style={{ backgroundColor: chipBg }}
          >
            <Text
              className="text-xs font-medium"
              style={{ color: accentColor }}
            >
              {typeLabel}
            </Text>
          </View>
        </View>

        {/* Title + edit */}
        <View className="flex-row items-center justify-between px-6">
          <Text
            className="flex-1 text-lg font-semibold text-zinc-100"
            numberOfLines={2}
          >
            {ticket.title || "Untitled Ticket"}
          </Text>
          <Pressable
            onPress={openEdit}
            hitSlop={8}
            className="h-8 w-8 items-center justify-center rounded-full"
          >
            <AppIcon icon={PencilEdit01Icon} size={16} color="#a1a1aa" />
          </Pressable>
        </View>

        {/* Separator */}
        <View className="mx-6 my-2 h-px bg-zinc-700" />

        {/* User info */}
        {(ticket.user_name || ticket.user_email) && (
          <>
            <View className="flex-row items-center gap-2 px-6">
              <Text className="text-sm text-zinc-400">From:</Text>
              <Text
                className="flex-1 text-sm font-medium text-zinc-200"
                numberOfLines={1}
              >
                {ticket.user_name || ticket.user_email}
                {ticket.user_name && ticket.user_email ? (
                  <Text className="font-normal text-zinc-400">
                    {` (${ticket.user_email})`}
                  </Text>
                ) : null}
              </Text>
            </View>
            <View className="mx-6 my-2 h-px bg-zinc-700" />
          </>
        )}

        {/* Description */}
        {ticket.description ? (
          <ScrollView
            style={{ maxHeight: 180 }}
            className="px-6"
            nestedScrollEnabled
            showsVerticalScrollIndicator={false}
          >
            <Text className="pb-4 text-sm leading-5 text-zinc-200">
              {ticket.description}
            </Text>
          </ScrollView>
        ) : null}

        {/* Submit */}
        <View className="flex-row justify-end px-6 pb-5 pt-1">
          <Pressable
            onPress={handleSubmit}
            disabled={isSubmitting || isSubmitted}
            style={({ pressed }) => ({
              flexDirection: "row",
              alignItems: "center",
              gap: 6,
              borderRadius: 999,
              paddingHorizontal: 16,
              paddingVertical: 8,
              backgroundColor: isSubmitted
                ? "rgba(34,197,94,0.2)"
                : pressed
                  ? "rgba(0,187,255,0.8)"
                  : "#00bbff",
              opacity: isSubmitting ? 0.6 : 1,
            })}
          >
            {isSubmitted ? (
              <AppIcon
                icon={CheckmarkCircle01Icon}
                size={14}
                color="#22c55e"
              />
            ) : null}
            <Text
              className="text-sm font-medium"
              style={{ color: isSubmitted ? "#22c55e" : "#0a0a0a" }}
            >
              {isSubmitted
                ? "Submitted"
                : isSubmitting
                  ? "Submitting..."
                  : "Submit Ticket"}
            </Text>
          </Pressable>
        </View>
      </View>

      {/* Edit sheet */}
      <BottomSheet isOpen={isSheetOpen} onOpenChange={setIsSheetOpen}>
        <BottomSheet.Portal>
          <BottomSheet.Overlay />
          <BottomSheet.Content
            enableDynamicSizing
            backgroundStyle={{ backgroundColor: "#18181b" }}
          >
            <View className="px-6 pt-2 pb-8">
              <Text className="mb-4 text-lg font-semibold text-zinc-100">
                Edit Support Ticket
              </Text>

              {/* Type toggle */}
              <Text className="mb-2 text-sm font-medium text-zinc-200">
                Type
              </Text>
              <View className="flex-row gap-2 mb-4">
                {(["support", "feature"] as const).map((t) => {
                  const active = draft.type === t;
                  return (
                    <Pressable
                      key={t}
                      onPress={() => setDraft({ ...draft, type: t })}
                      style={({ pressed }) => ({
                        flexDirection: "row",
                        alignItems: "center",
                        gap: 6,
                        borderRadius: 999,
                        paddingHorizontal: 14,
                        paddingVertical: 8,
                        backgroundColor: active
                          ? "#00bbff"
                          : pressed
                            ? "rgba(255,255,255,0.08)"
                            : "rgba(255,255,255,0.04)",
                      })}
                    >
                      <AppIcon
                        icon={t === "feature" ? Comment01Icon : HelpCircleIcon}
                        size={14}
                        color={active ? "#0a0a0a" : "#a1a1aa"}
                      />
                      <Text
                        className="text-sm font-medium"
                        style={{ color: active ? "#0a0a0a" : "#a1a1aa" }}
                      >
                        {t === "feature" ? "Feature Request" : "Support"}
                      </Text>
                    </Pressable>
                  );
                })}
              </View>

              {/* Title */}
              <Text className="mb-2 text-sm font-medium text-zinc-200">
                Title
              </Text>
              <BottomSheetTextInput
                value={draft.title ?? ""}
                onChangeText={(text) => setDraft({ ...draft, title: text })}
                placeholder="Brief description of your issue or request"
                placeholderTextColor="#52525b"
                maxLength={200}
                className="mb-4 rounded-xl bg-zinc-900 px-3 py-3 text-sm text-zinc-100"
                style={{ color: "#f4f4f5" }}
              />

              {/* Description */}
              <Text className="mb-2 text-sm font-medium text-zinc-200">
                Description
              </Text>
              <BottomSheetTextInput
                value={draft.description ?? ""}
                onChangeText={(text) =>
                  setDraft({ ...draft, description: text })
                }
                placeholder="Please provide detailed information about your issue or feature request"
                placeholderTextColor="#52525b"
                multiline
                numberOfLines={6}
                maxLength={5000}
                textAlignVertical="top"
                className="mb-6 rounded-xl bg-zinc-900 px-3 py-3 text-sm text-zinc-100"
                style={{ minHeight: 120, color: "#f4f4f5" }}
              />

              {/* Actions */}
              <View className="flex-row justify-end gap-2">
                <Pressable
                  onPress={() => setIsSheetOpen(false)}
                  style={({ pressed }) => ({
                    borderRadius: 999,
                    paddingHorizontal: 16,
                    paddingVertical: 10,
                    backgroundColor: pressed
                      ? "rgba(255,255,255,0.08)"
                      : "rgba(255,255,255,0.04)",
                  })}
                >
                  <Text className="text-sm font-medium text-zinc-200">
                    Cancel
                  </Text>
                </Pressable>
                <Pressable
                  onPress={saveDraft}
                  style={({ pressed }) => ({
                    borderRadius: 999,
                    paddingHorizontal: 16,
                    paddingVertical: 10,
                    backgroundColor: pressed ? "rgba(0,187,255,0.8)" : "#00bbff",
                  })}
                >
                  <Text
                    className="text-sm font-medium"
                    style={{ color: "#0a0a0a" }}
                  >
                    Save Changes
                  </Text>
                </Pressable>
              </View>
            </View>
          </BottomSheet.Content>
        </BottomSheet.Portal>
      </BottomSheet>
    </>
  );
}
