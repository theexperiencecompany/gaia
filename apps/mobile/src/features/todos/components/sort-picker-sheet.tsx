import { forwardRef, useImperativeHandle, useState } from "react";
import { Pressable, View } from "react-native";
import { AppIcon, Tick02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { selectionHaptic } from "@/lib/haptics";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";
import { SORT_OPTIONS, type SortOption } from "../types/todo-types";

interface SortPickerSheetProps {
  activeSort: SortOption | null;
  onSelect: (sort: SortOption) => void;
  onClear: () => void;
}

export interface SortPickerSheetRef {
  open: () => void;
  close: () => void;
}

export const SortPickerSheet = forwardRef<
  SortPickerSheetRef,
  SortPickerSheetProps
>(({ activeSort, onSelect, onClear }, ref) => {
  const [isOpen, setIsOpen] = useState(false);

  useImperativeHandle(ref, () => ({
    open: () => setIsOpen(true),
    close: () => setIsOpen(false),
  }));

  const isActive = (option: SortOption) =>
    activeSort?.field === option.field &&
    activeSort?.direction === option.direction;

  const handleSelect = (option: SortOption) => {
    selectionHaptic();
    onSelect(option);
    setIsOpen(false);
  };

  return (
    <BottomSheet isOpen={isOpen} onOpenChange={setIsOpen}>
      <BottomSheet.Portal>
        <BottomSheet.Overlay />
        <BottomSheet.Content
          snapPoints={["55%"]}
          enableDynamicSizing={false}
          enablePanDownToClose
          backgroundStyle={{ backgroundColor: "#1c1c1e" }}
          handleIndicatorStyle={{ backgroundColor: "#3f3f46", width: 40 }}
        >
          <View style={{ paddingHorizontal: 16, paddingBottom: 32 }}>
            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                justifyContent: "space-between",
                paddingVertical: 12,
                marginBottom: 4,
              }}
            >
              <Text
                style={{ fontSize: 17, fontWeight: "600", color: "#f4f4f5" }}
              >
                Sort by
              </Text>
              {activeSort && (
                <Pressable
                  onPress={() => {
                    selectionHaptic();
                    onClear();
                    setIsOpen(false);
                  }}
                  hitSlop={8}
                >
                  <Text style={{ fontSize: 14, color: "#71717a" }}>Clear</Text>
                </Pressable>
              )}
            </View>

            {SORT_OPTIONS.map((option: SortOption) => {
              const active = isActive(option);
              return (
                <Pressable
                  key={`${option.field}-${option.direction}`}
                  onPress={() => handleSelect(option)}
                  style={({ pressed }) => ({
                    flexDirection: "row",
                    alignItems: "center",
                    justifyContent: "space-between",
                    paddingVertical: 14,
                    paddingHorizontal: 14,
                    borderRadius: 12,
                    marginBottom: 4,
                    backgroundColor: active
                      ? "rgba(0,187,255,0.12)"
                      : pressed
                        ? "rgba(63,63,70,0.40)"
                        : "rgba(39,39,42,0.30)",
                  })}
                >
                  <Text
                    style={{
                      fontSize: 15,
                      color: active ? "#00bbff" : "#e4e4e7",
                      fontWeight: active ? "600" : "500",
                    }}
                  >
                    {option.label}
                  </Text>
                  {active && (
                    <AppIcon icon={Tick02Icon} size={16} color="#00bbff" />
                  )}
                </Pressable>
              );
            })}
          </View>
        </BottomSheet.Content>
      </BottomSheet.Portal>
    </BottomSheet>
  );
});

SortPickerSheet.displayName = "SortPickerSheet";
