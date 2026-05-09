import { BottomSheetScrollView } from "@gorhom/bottom-sheet";
import { Button, Chip } from "heroui-native";
import { useState } from "react";
import { ActivityIndicator, ScrollView, TextInput, View } from "react-native";
import {
  AppIcon,
  Comment01Icon,
  HelpCircleIcon,
  PencilEdit01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { apiService } from "@/lib/api";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";

// ---------------------------------------------------------------------------
// Types — mirror apps/web/src/types/features/supportTypes.ts
// ---------------------------------------------------------------------------

export type SupportTicketType = "support" | "feature";

export interface SupportTicketData {
  type: SupportTicketType;
  title: string;
  description: string;
  user_name?: string;
  user_email?: string;
}

interface SupportResponse {
  success: boolean;
  message: string;
  ticket_id?: string;
}

// ---------------------------------------------------------------------------
// Divider — mirrors web's <Separator className="my-1.5 bg-zinc-700" />
// ---------------------------------------------------------------------------

function Divider() {
  return <View className="h-px bg-zinc-700 my-1.5" />;
}

// ---------------------------------------------------------------------------
// EditTicketSheet — bottom-sheet equivalent of web's EditTicketModal
// ---------------------------------------------------------------------------

interface EditTicketSheetProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  editData: SupportTicketData;
  onSave: (next: SupportTicketData) => void;
}

function EditTicketSheet({
  isOpen,
  onOpenChange,
  editData,
  onSave,
}: EditTicketSheetProps) {
  const [draft, setDraft] = useState<SupportTicketData>(editData);
  const [errors, setErrors] = useState<Record<string, string>>({});

  // Reset draft each time the sheet opens so cancelled edits don't persist.
  const handleOpenChange = (open: boolean) => {
    if (open) {
      setDraft(editData);
      setErrors({});
    }
    onOpenChange(open);
  };

  const validate = (): boolean => {
    const next: Record<string, string> = {};
    if (!draft.title || draft.title.trim().length === 0) {
      next.title = "Title is required";
    } else if (draft.title.length > 200) {
      next.title = "Title must be under 200 characters";
    }
    if (!draft.description || draft.description.trim().length < 10) {
      next.description = "Description must be at least 10 characters";
    } else if (draft.description.length > 5000) {
      next.description = "Description must be under 5,000 characters";
    }
    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const handleSave = () => {
    if (!validate()) return;
    onSave(draft);
    onOpenChange(false);
  };

  return (
    <BottomSheet isOpen={isOpen} onOpenChange={handleOpenChange}>
      <BottomSheet.Portal>
        <BottomSheet.Overlay />
        <BottomSheet.Content
          snapPoints={["75%", "95%"]}
          enableDynamicSizing={false}
          enablePanDownToClose
          backgroundStyle={{ backgroundColor: "#27272a" }}
          handleIndicatorStyle={{ backgroundColor: "#52525b", width: 40 }}
        >
          <View className="px-4 pt-1 pb-3">
            <Text className="text-zinc-100 text-base font-semibold">
              Edit Support Ticket
            </Text>
          </View>

          <BottomSheetScrollView
            contentContainerStyle={{ paddingHorizontal: 16, paddingBottom: 24 }}
            showsVerticalScrollIndicator={false}
          >
            {/* Type selection */}
            <Text className="text-zinc-200 text-sm font-medium mb-2">Type</Text>
            <View className="flex-row gap-2 mb-4">
              <Chip
                size="md"
                variant={draft.type === "support" ? "primary" : "tertiary"}
                onPress={() => setDraft({ ...draft, type: "support" })}
                animation="disable-all"
              >
                <Chip.Label>Support</Chip.Label>
              </Chip>
              <Chip
                size="md"
                variant={draft.type === "feature" ? "primary" : "tertiary"}
                onPress={() => setDraft({ ...draft, type: "feature" })}
                animation="disable-all"
              >
                <Chip.Label>Feature Request</Chip.Label>
              </Chip>
            </View>

            {/* Title */}
            <Text className="text-zinc-200 text-sm font-medium mb-2">
              Title
            </Text>
            <View
              className={`rounded-xl bg-zinc-900 px-3 py-3 mb-1 ${
                errors.title ? "border border-red-500/60" : ""
              }`}
            >
              <TextInput
                value={draft.title ?? ""}
                onChangeText={(v) => setDraft({ ...draft, title: v })}
                placeholder="Brief description of your issue or request"
                placeholderTextColor="#71717a"
                style={{ color: "#f4f4f5", fontSize: 14, paddingVertical: 0 }}
              />
            </View>
            {errors.title ? (
              <Text className="text-red-400 text-xs mb-3">{errors.title}</Text>
            ) : (
              <View className="mb-3" />
            )}

            {/* Description */}
            <Text className="text-zinc-200 text-sm font-medium mb-2">
              Description
            </Text>
            <View
              className={`rounded-xl bg-zinc-900 px-3 py-3 mb-1 ${
                errors.description ? "border border-red-500/60" : ""
              }`}
            >
              <TextInput
                value={draft.description ?? ""}
                onChangeText={(v) => setDraft({ ...draft, description: v })}
                placeholder="Please provide detailed information about your issue or feature request"
                placeholderTextColor="#71717a"
                multiline
                numberOfLines={6}
                textAlignVertical="top"
                style={{
                  color: "#f4f4f5",
                  fontSize: 14,
                  paddingVertical: 0,
                  minHeight: 120,
                }}
              />
            </View>
            {errors.description ? (
              <Text className="text-red-400 text-xs mb-4">
                {errors.description}
              </Text>
            ) : (
              <View className="mb-4" />
            )}

            {/* Footer actions */}
            <View className="flex-row justify-end gap-2">
              <Button
                size="md"
                variant="tertiary"
                onPress={() => onOpenChange(false)}
              >
                <Button.Label>Cancel</Button.Label>
              </Button>
              <Button size="md" variant="primary" onPress={handleSave}>
                <Button.Label>Save Changes</Button.Label>
              </Button>
            </View>
          </BottomSheetScrollView>
        </BottomSheet.Content>
      </BottomSheet.Portal>
    </BottomSheet>
  );
}

// ---------------------------------------------------------------------------
// SupportTicketCard — port of apps/web/src/features/support/components/SupportTicketCard.tsx
// ---------------------------------------------------------------------------

interface SupportTicketCardProps {
  data: SupportTicketData;
  onSubmitted?: () => void;
}

export function SupportTicketCard({
  data,
  onSubmitted,
}: SupportTicketCardProps) {
  const [editData, setEditData] = useState<SupportTicketData>(data);
  const [isEditOpen, setIsEditOpen] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const isFeature = editData.type === "feature";
  const typeLabel = isFeature ? "Feature Request" : "Support Ticket";

  const handleSave = (next: SupportTicketData) => {
    setEditData(next);
  };

  const handleSubmit = async () => {
    if (isSubmitting) return;
    setIsSubmitting(true);
    try {
      await apiService.post<SupportResponse>("/support/requests", {
        type: editData.type,
        title: editData.title,
        description: editData.description,
      });
      onSubmitted?.();
    } catch (error) {
      console.error("Failed to submit support ticket:", error);
    } finally {
      setIsSubmitting(false);
    }
  };

  const showFromRow = !!(editData.user_name || editData.user_email);

  return (
    <>
      {/* Outer card — matches web's `rounded-3xl bg-zinc-800 overflow-hidden`.
          Mobile uses mx-4/my-1 for the chat bubble gutter. */}
      <View className="rounded-3xl bg-zinc-800 mx-4 my-1 overflow-hidden">
        {/* Header — type icon + chip */}
        <View className="flex-row items-center justify-between px-6 py-1">
          <View className="flex-row items-center gap-2 pt-3 pb-2">
            <AppIcon
              icon={isFeature ? Comment01Icon : HelpCircleIcon}
              size={18}
              color={isFeature ? "#34d399" : "#00bbff"}
            />
            <Chip
              size="sm"
              variant="soft"
              color={isFeature ? "success" : "default"}
              animation="disable-all"
            >
              <Chip.Label>{typeLabel}</Chip.Label>
            </Chip>
          </View>
        </View>

        <View className="px-6 flex-col gap-1">
          {/* Title row + edit button */}
          <View className="flex-row items-center justify-between">
            <Text className="text-zinc-100 text-lg font-semibold flex-1">
              {editData.title}
            </Text>
            <Button
              size="sm"
              variant="tertiary"
              isIconOnly
              onPress={() => setIsEditOpen(true)}
            >
              <AppIcon icon={PencilEdit01Icon} size={16} color="#71717a" />
            </Button>
          </View>

          <Divider />

          {/* From row — only when user info is present */}
          {showFromRow ? (
            <>
              <View className="flex-row items-center gap-2">
                <Text className="text-sm text-zinc-400">From:</Text>
                <Text className="text-sm font-medium text-zinc-200">
                  {editData.user_name ?? editData.user_email}
                  {editData.user_name && editData.user_email ? (
                    <Text className="text-sm font-normal text-zinc-400">
                      {" "}
                      ({editData.user_email})
                    </Text>
                  ) : null}
                </Text>
              </View>
              <Divider />
            </>
          ) : null}

          {/* Description — scrollable, mirrors web's ScrollShadow */}
          <ScrollView
            className="pb-5"
            style={{ maxHeight: 240 }}
            showsVerticalScrollIndicator={false}
            nestedScrollEnabled
          >
            <Text className="text-sm leading-relaxed text-zinc-200">
              {editData.description}
            </Text>
          </ScrollView>
        </View>

        {/* Submit button — right-aligned, rounded-full primary */}
        <View className="flex-row justify-end px-6 pb-5">
          <Button
            size="md"
            variant="primary"
            onPress={() => void handleSubmit()}
            isDisabled={isSubmitting}
          >
            {isSubmitting ? (
              <View className="flex-row items-center gap-2">
                <ActivityIndicator size="small" color="#000" />
                <Button.Label>Submitting...</Button.Label>
              </View>
            ) : (
              <Button.Label>Submit Ticket</Button.Label>
            )}
          </Button>
        </View>
      </View>

      <EditTicketSheet
        isOpen={isEditOpen}
        onOpenChange={setIsEditOpen}
        editData={editData}
        onSave={handleSave}
      />
    </>
  );
}
