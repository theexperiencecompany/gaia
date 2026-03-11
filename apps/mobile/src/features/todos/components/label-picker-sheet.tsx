import {
  BottomSheetScrollView,
  BottomSheetTextInput,
} from "@gorhom/bottom-sheet";
import { forwardRef, useCallback, useImperativeHandle, useState } from "react";
import { Pressable, View } from "react-native";
import { Add01Icon, AppIcon, Tick02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";
import { LabelChip } from "./label-chip";

export interface LabelPickerSheetRef {
  open: (selected: string[], allLabels: string[]) => void;
  close: () => void;
}

interface Props {
  onDone: (labels: string[]) => void;
}

export const LabelPickerSheet = forwardRef<LabelPickerSheetRef, Props>(
  ({ onDone }, ref) => {
    const [isOpen, setIsOpen] = useState(false);
    const [selected, setSelected] = useState<string[]>([]);
    const [allLabels, setAllLabels] = useState<string[]>([]);
    const [newLabel, setNewLabel] = useState("");
    const { spacing, fontSize } = useResponsive();

    useImperativeHandle(ref, () => ({
      open: (currentSelected: string[], existingLabels: string[]) => {
        setSelected(currentSelected);
        setAllLabels(existingLabels);
        setNewLabel("");
        setIsOpen(true);
      },
      close: () => setIsOpen(false),
    }));

    const toggleLabel = useCallback((label: string) => {
      setSelected((prev) =>
        prev.includes(label)
          ? prev.filter((l) => l !== label)
          : [...prev, label],
      );
    }, []);

    const handleAddNew = useCallback(() => {
      const trimmed = newLabel.trim().toLowerCase();
      if (!trimmed) return;
      if (!allLabels.includes(trimmed)) {
        setAllLabels((prev) => [...prev, trimmed]);
      }
      if (!selected.includes(trimmed)) {
        setSelected((prev) => [...prev, trimmed]);
      }
      setNewLabel("");
    }, [newLabel, allLabels, selected]);

    const handleDone = useCallback(() => {
      onDone(selected);
      setIsOpen(false);
    }, [onDone, selected]);

    return (
      <BottomSheet isOpen={isOpen} onOpenChange={setIsOpen}>
        <BottomSheet.Portal>
          <BottomSheet.Overlay />
          <BottomSheet.Content
            snapPoints={["50%", "80%"]}
            enableDynamicSizing={false}
            enablePanDownToClose
            backgroundStyle={{ backgroundColor: "#1c1c1e" }}
            handleIndicatorStyle={{ backgroundColor: "#3f3f46", width: 40 }}
          >
            <BottomSheetScrollView
              contentContainerStyle={{
                padding: 20,
                gap: 16,
                paddingBottom: 40,
              }}
              keyboardShouldPersistTaps="handled"
            >
              {/* Header */}
              <View
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  justifyContent: "space-between",
                }}
              >
                <Text
                  style={{
                    fontSize: fontSize.base,
                    fontWeight: "600",
                    color: "#f4f4f5",
                  }}
                >
                  Labels
                </Text>
                <Pressable
                  onPress={handleDone}
                  style={{
                    paddingHorizontal: spacing.md,
                    paddingVertical: spacing.sm,
                    borderRadius: 8,
                    backgroundColor: "rgba(22,193,255,0.15)",
                  }}
                >
                  <Text
                    style={{
                      fontSize: fontSize.sm,
                      fontWeight: "600",
                      color: "#16c1ff",
                    }}
                  >
                    Done
                  </Text>
                </Pressable>
              </View>

              {/* New label input */}
              <View
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  gap: spacing.sm,
                  backgroundColor: "#27272a",
                  borderRadius: 10,
                  paddingHorizontal: 12,
                  paddingVertical: 10,
                  borderWidth: 1,
                  borderColor: "#3f3f46",
                }}
              >
                <BottomSheetTextInput
                  value={newLabel}
                  onChangeText={setNewLabel}
                  placeholder="New label..."
                  placeholderTextColor="#52525b"
                  style={{
                    flex: 1,
                    fontSize: fontSize.sm,
                    color: "#f4f4f5",
                  }}
                  onSubmitEditing={handleAddNew}
                  returnKeyType="done"
                  autoCapitalize="none"
                />
                <Pressable onPress={handleAddNew} hitSlop={8}>
                  <AppIcon icon={Add01Icon} size={18} color="#16c1ff" />
                </Pressable>
              </View>

              {/* Label list */}
              {allLabels.length === 0 ? (
                <Text
                  style={{
                    fontSize: fontSize.sm,
                    color: "#52525b",
                    fontStyle: "italic",
                    textAlign: "center",
                    paddingVertical: spacing.md,
                  }}
                >
                  No labels yet. Create one above.
                </Text>
              ) : (
                <View
                  style={{
                    backgroundColor: "#27272a",
                    borderRadius: 12,
                    borderWidth: 1,
                    borderColor: "#3f3f46",
                    overflow: "hidden",
                  }}
                >
                  {allLabels.map((label, idx) => {
                    const isActive = selected.includes(label);
                    return (
                      <Pressable
                        key={label}
                        onPress={() => toggleLabel(label)}
                        style={{
                          flexDirection: "row",
                          alignItems: "center",
                          paddingHorizontal: 14,
                          paddingVertical: 12,
                          gap: 10,
                          borderTopWidth: idx > 0 ? 1 : 0,
                          borderTopColor: "#3f3f46",
                        }}
                      >
                        <LabelChip label={label} size="sm" />
                        <View style={{ flex: 1 }} />
                        <View
                          style={{
                            width: 22,
                            height: 22,
                            borderRadius: 11,
                            borderWidth: 2,
                            borderColor: isActive ? "#16c1ff" : "#52525b",
                            backgroundColor: isActive
                              ? "#16c1ff"
                              : "transparent",
                            alignItems: "center",
                            justifyContent: "center",
                          }}
                        >
                          {isActive && (
                            <AppIcon icon={Tick02Icon} size={13} color="#000" />
                          )}
                        </View>
                      </Pressable>
                    );
                  })}
                </View>
              )}
            </BottomSheetScrollView>
          </BottomSheet.Content>
        </BottomSheet.Portal>
      </BottomSheet>
    );
  },
);
