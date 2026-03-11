import BottomSheet, {
  BottomSheetBackdrop,
  BottomSheetView,
} from "@gorhom/bottom-sheet";
import { type Ref, useCallback } from "react";
import { Pressable, View } from "react-native";
import { Text } from "@/components/ui/text";
import { SORT_OPTIONS, type SortOption } from "../types";

interface SortPickerSheetProps {
  sheetRef: Ref<BottomSheet>;
  activeSort: SortOption | null;
  onSelect: (sort: SortOption) => void;
  onClear: () => void;
}

export function SortPickerSheet({
  sheetRef,
  activeSort,
  onSelect,
  onClear,
}: SortPickerSheetProps) {
  const renderBackdrop = useCallback(
    (props: Parameters<typeof BottomSheetBackdrop>[0]) => (
      <BottomSheetBackdrop
        {...props}
        disappearsOnIndex={-1}
        appearsOnIndex={0}
        opacity={0.5}
      />
    ),
    [],
  );

  const isActive = (option: SortOption) =>
    activeSort?.field === option.field &&
    activeSort?.direction === option.direction;

  return (
    <BottomSheet
      ref={sheetRef}
      index={-1}
      snapPoints={["50%"]}
      enablePanDownToClose
      backdropComponent={renderBackdrop}
      backgroundStyle={{ backgroundColor: "#1c1c1e" }}
      handleIndicatorStyle={{ backgroundColor: "#4b5563" }}
    >
      <BottomSheetView style={{ paddingHorizontal: 16, paddingBottom: 32 }}>
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
            style={{ fontSize: 17, fontWeight: "600", color: "#f1f5f9" }}
          >
            Sort by
          </Text>
          {activeSort && (
            <Pressable onPress={onClear} hitSlop={8}>
              <Text style={{ fontSize: 14, color: "#6b7280" }}>Clear</Text>
            </Pressable>
          )}
        </View>

        {SORT_OPTIONS.map((option) => {
          const active = isActive(option);
          return (
            <Pressable
              key={`${option.field}-${option.direction}`}
              onPress={() => onSelect(option)}
              style={({ pressed }) => ({
                flexDirection: "row",
                alignItems: "center",
                justifyContent: "space-between",
                paddingVertical: 13,
                paddingHorizontal: 12,
                borderRadius: 8,
                marginBottom: 2,
                backgroundColor: active
                  ? "rgba(99,102,241,0.15)"
                  : pressed
                    ? "rgba(255,255,255,0.05)"
                    : "transparent",
              })}
            >
              <Text
                style={{
                  fontSize: 15,
                  color: active ? "#a5b4fc" : "#d1d5db",
                }}
              >
                {option.label}
              </Text>
              {active && (
                <View
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: 4,
                    backgroundColor: "#a5b4fc",
                  }}
                />
              )}
            </Pressable>
          );
        })}
      </BottomSheetView>
    </BottomSheet>
  );
}
