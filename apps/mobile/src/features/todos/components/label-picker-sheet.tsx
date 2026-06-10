import {
  BottomSheetScrollView,
  BottomSheetTextInput,
} from "@gorhom/bottom-sheet";
import { forwardRef, useCallback, useImperativeHandle, useState } from "react";
import { Pressable, View } from "react-native";
import { Add01Icon, AppIcon, Tick02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
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
            backgroundStyle={{ backgroundColor: "#18181b" }}
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
              <View className="flex-row items-center justify-between">
                <Text
                  style={{ fontSize: 17, fontWeight: "600", color: "#f4f4f5" }}
                >
                  Labels
                </Text>
                <Pressable
                  onPress={handleDone}
                  style={{
                    paddingHorizontal: 12,
                    paddingVertical: 6,
                    borderRadius: 12,
                    backgroundColor: "#00bbff",
                  }}
                >
                  <Text
                    style={{ fontSize: 13, fontWeight: "600", color: "#000" }}
                  >
                    Done
                  </Text>
                </Pressable>
              </View>

              {/* New label input */}
              <View
                className="flex-row items-center bg-zinc-800/30"
                style={{
                  gap: 10,
                  paddingHorizontal: 12,
                  paddingVertical: 10,
                  borderRadius: 16,
                }}
              >
                <BottomSheetTextInput
                  value={newLabel}
                  onChangeText={setNewLabel}
                  placeholder="New label…"
                  placeholderTextColor="#52525b"
                  style={{ flex: 1, fontSize: 14, color: "#f4f4f5" }}
                  onSubmitEditing={handleAddNew}
                  returnKeyType="done"
                  autoCapitalize="none"
                />
                <Pressable onPress={handleAddNew} hitSlop={8}>
                  <AppIcon icon={Add01Icon} size={18} color="#00bbff" />
                </Pressable>
              </View>

              {/* Label list */}
              {allLabels.length === 0 ? (
                <Text
                  className="text-center italic text-zinc-500"
                  style={{ fontSize: 14, paddingVertical: 16 }}
                >
                  No labels yet. Create one above.
                </Text>
              ) : (
                <View className="bg-zinc-800/30 rounded-2xl">
                  {allLabels.map((label) => {
                    const isActive = selected.includes(label);
                    return (
                      <Pressable
                        key={label}
                        onPress={() => toggleLabel(label)}
                        className="flex-row items-center"
                        style={{
                          paddingHorizontal: 14,
                          paddingVertical: 12,
                          gap: 10,
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
                            borderColor: isActive ? "#00bbff" : "#52525b",
                            backgroundColor: isActive
                              ? "#00bbff"
                              : "transparent",
                            alignItems: "center",
                            justifyContent: "center",
                          }}
                        >
                          {isActive ? (
                            <AppIcon icon={Tick02Icon} size={13} color="#000" />
                          ) : null}
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

LabelPickerSheet.displayName = "LabelPickerSheet";
