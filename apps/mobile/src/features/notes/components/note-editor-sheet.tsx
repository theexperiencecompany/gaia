import {
  BottomSheetScrollView,
  BottomSheetTextInput,
} from "@gorhom/bottom-sheet";
import { forwardRef, useCallback, useImperativeHandle, useState } from "react";
import { Pressable, View } from "react-native";
import { AppIcon, Cancel01Icon, Tick02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { impactHaptic, notificationHaptic } from "@/lib/haptics";
import { useResponsive } from "@/lib/responsive";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";
import type { Note, NoteCreate, NoteUpdate } from "../api/notes-api";

export interface NoteEditorSheetRef {
  openCreate: () => void;
  openEdit: (note: Note) => void;
  close: () => void;
}

interface NoteEditorSheetProps {
  onSaveCreate: (data: NoteCreate) => Promise<void>;
  onSaveUpdate: (id: string, data: NoteUpdate) => Promise<void>;
}

export const NoteEditorSheet = forwardRef<
  NoteEditorSheetRef,
  NoteEditorSheetProps
>(({ onSaveCreate, onSaveUpdate }, ref) => {
  const [isOpen, setIsOpen] = useState(false);
  const [editingNote, setEditingNote] = useState<Note | null>(null);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const { spacing, fontSize } = useResponsive();

  const reset = useCallback(() => {
    setEditingNote(null);
    setTitle("");
    setContent("");
    setIsSaving(false);
  }, []);

  useImperativeHandle(ref, () => ({
    openCreate: () => {
      reset();
      setIsOpen(true);
    },
    openEdit: (note: Note) => {
      setEditingNote(note);
      setTitle(note.title);
      setContent(note.content);
      setIsSaving(false);
      setIsOpen(true);
    },
    close: () => setIsOpen(false),
  }));

  const handleSave = useCallback(async () => {
    if (isSaving) return;
    impactHaptic("medium");
    setIsSaving(true);
    try {
      if (editingNote) {
        await onSaveUpdate(editingNote.id, { title, content });
      } else {
        await onSaveCreate({ title, content });
      }
      notificationHaptic("success");
      setIsOpen(false);
      reset();
    } finally {
      setIsSaving(false);
    }
  }, [
    isSaving,
    editingNote,
    title,
    content,
    onSaveCreate,
    onSaveUpdate,
    reset,
  ]);

  const handleCancel = useCallback(() => {
    setIsOpen(false);
    reset();
  }, [reset]);

  return (
    <BottomSheet
      isOpen={isOpen}
      onOpenChange={(open) => {
        setIsOpen(open);
        if (!open) reset();
      }}
    >
      <BottomSheet.Portal>
        <BottomSheet.Overlay />
        <BottomSheet.Content
          snapPoints={["60%", "95%"]}
          enableDynamicSizing={false}
          enablePanDownToClose
          backgroundStyle={{ backgroundColor: "#1c1c1e" }}
          handleIndicatorStyle={{ backgroundColor: "#3f3f46", width: 40 }}
        >
          <BottomSheetScrollView
            contentContainerStyle={{
              padding: spacing.md,
              gap: spacing.md,
              paddingBottom: 48,
            }}
            keyboardShouldPersistTaps="handled"
          >
            {/* Header row */}
            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                justifyContent: "space-between",
              }}
            >
              <Text
                style={{
                  fontSize: fontSize.lg,
                  fontWeight: "600",
                  color: "#f4f4f5",
                }}
              >
                {editingNote ? "Edit Note" : "New Note"}
              </Text>
              <View style={{ flexDirection: "row", gap: 8 }}>
                <Pressable
                  onPress={handleCancel}
                  style={{
                    width: 32,
                    height: 32,
                    borderRadius: 8,
                    alignItems: "center",
                    justifyContent: "center",
                    backgroundColor: "rgba(255,255,255,0.06)",
                  }}
                >
                  <AppIcon icon={Cancel01Icon} size={16} color="#a1a1aa" />
                </Pressable>
                <Pressable
                  onPress={() => {
                    void handleSave();
                  }}
                  disabled={isSaving}
                  style={{
                    width: 32,
                    height: 32,
                    borderRadius: 8,
                    alignItems: "center",
                    justifyContent: "center",
                    backgroundColor: isSaving
                      ? "rgba(22,193,255,0.06)"
                      : "rgba(22,193,255,0.15)",
                  }}
                >
                  <AppIcon
                    icon={Tick02Icon}
                    size={16}
                    color={isSaving ? "#52525b" : "#16c1ff"}
                  />
                </Pressable>
              </View>
            </View>

            {/* Title input */}
            <BottomSheetTextInput
              value={title}
              onChangeText={setTitle}
              placeholder="Note title"
              placeholderTextColor="#52525b"
              style={{
                fontSize: fontSize.xl,
                fontWeight: "600",
                color: "#f4f4f5",
                borderBottomWidth: 1,
                borderBottomColor: "#3f3f46",
                paddingVertical: 8,
              }}
              returnKeyType="next"
            />

            {/* Content input */}
            <BottomSheetTextInput
              value={content}
              onChangeText={setContent}
              placeholder="Start writing..."
              placeholderTextColor="#52525b"
              multiline
              style={{
                fontSize: fontSize.base,
                color: "#e4e4e7",
                minHeight: 180,
                textAlignVertical: "top",
                lineHeight: fontSize.base * 1.6,
              }}
            />

            {/* Save button */}
            <Pressable
              onPress={() => {
                void handleSave();
              }}
              disabled={isSaving}
              style={{
                alignItems: "center",
                justifyContent: "center",
                paddingVertical: spacing.md,
                borderRadius: 12,
                backgroundColor: isSaving
                  ? "rgba(22,193,255,0.06)"
                  : "rgba(22,193,255,0.12)",
                borderWidth: 1,
                borderColor: isSaving
                  ? "rgba(22,193,255,0.1)"
                  : "rgba(22,193,255,0.25)",
              }}
            >
              <Text
                style={{
                  fontSize: fontSize.base,
                  fontWeight: "600",
                  color: isSaving ? "#52525b" : "#16c1ff",
                }}
              >
                {isSaving ? "Saving..." : "Save"}
              </Text>
            </Pressable>
          </BottomSheetScrollView>
        </BottomSheet.Content>
      </BottomSheet.Portal>
    </BottomSheet>
  );
});
