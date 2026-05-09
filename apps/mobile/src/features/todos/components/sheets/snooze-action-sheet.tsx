import DateTimePicker, {
  type DateTimePickerEvent,
} from "@react-native-community/datetimepicker";
import { forwardRef, useCallback, useImperativeHandle, useState } from "react";
import { Platform, Pressable, View } from "react-native";
import {
  AppIcon,
  Calendar03Icon,
  CheckmarkCircle02Icon,
  Timer02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { selectionHaptic } from "@/lib/haptics";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";

export interface SnoozeActionSheetRef {
  open: () => void;
  close: () => void;
}

interface SnoozeActionSheetProps {
  /**
   * Called with an ISO datetime string when the user picks an option.
   */
  onPick: (isoDate: string) => void;
}

function startOfDay(d: Date): Date {
  const next = new Date(d);
  next.setHours(9, 0, 0, 0);
  return next;
}

const OPTIONS: {
  key: "tomorrow" | "next-week" | "pick";
  label: string;
  icon: React.ComponentProps<typeof AppIcon>["icon"];
}[] = [
  { key: "tomorrow", label: "Tomorrow", icon: Timer02Icon },
  { key: "next-week", label: "Next week", icon: CheckmarkCircle02Icon },
  { key: "pick", label: "Pick date…", icon: Calendar03Icon },
];

export const SnoozeActionSheet = forwardRef<
  SnoozeActionSheetRef,
  SnoozeActionSheetProps
>(({ onPick }, ref) => {
  const [isOpen, setIsOpen] = useState(false);
  const [showPicker, setShowPicker] = useState(false);

  useImperativeHandle(ref, () => ({
    open: () => {
      setIsOpen(true);
      setShowPicker(false);
    },
    close: () => setIsOpen(false),
  }));

  const handleOption = useCallback(
    (key: "tomorrow" | "next-week" | "pick") => {
      selectionHaptic();
      const now = new Date();
      if (key === "tomorrow") {
        const t = new Date(now);
        t.setDate(t.getDate() + 1);
        onPick(startOfDay(t).toISOString());
        setIsOpen(false);
        return;
      }
      if (key === "next-week") {
        const t = new Date(now);
        t.setDate(t.getDate() + 7);
        onPick(startOfDay(t).toISOString());
        setIsOpen(false);
        return;
      }
      setShowPicker(true);
    },
    [onPick],
  );

  const handleDateChange = useCallback(
    (_event: DateTimePickerEvent, selected?: Date) => {
      if (Platform.OS !== "ios") setShowPicker(false);
      if (!selected) return;
      onPick(selected.toISOString());
      setIsOpen(false);
    },
    [onPick],
  );

  return (
    <BottomSheet isOpen={isOpen} onOpenChange={setIsOpen}>
      <BottomSheet.Portal>
        <BottomSheet.Overlay />
        <BottomSheet.Content
          snapPoints={["40%"]}
          enableDynamicSizing={false}
          enablePanDownToClose
          backgroundStyle={{ backgroundColor: "#1c1c1e" }}
          handleIndicatorStyle={{ backgroundColor: "#3f3f46", width: 40 }}
        >
          <View style={{ paddingHorizontal: 16, paddingBottom: 32 }}>
            <Text
              style={{
                fontSize: 17,
                fontWeight: "600",
                color: "#f4f4f5",
                paddingVertical: 12,
              }}
            >
              Snooze until
            </Text>
            {OPTIONS.map((opt) => (
              <Pressable
                key={opt.key}
                onPress={() => handleOption(opt.key)}
                style={({ pressed }) => ({
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 12,
                  paddingVertical: 14,
                  paddingHorizontal: 12,
                  borderRadius: 12,
                  backgroundColor: pressed
                    ? "rgba(63,63,70,0.6)"
                    : "rgba(39,39,42,0.30)",
                  marginBottom: 8,
                })}
              >
                <AppIcon icon={opt.icon} size={18} color="#a1a1aa" />
                <Text
                  style={{ fontSize: 15, color: "#e4e4e7", fontWeight: "500" }}
                >
                  {opt.label}
                </Text>
              </Pressable>
            ))}
            {showPicker ? (
              <View style={{ marginTop: 8 }}>
                <DateTimePicker
                  value={new Date()}
                  mode="date"
                  display={Platform.OS === "ios" ? "inline" : "default"}
                  themeVariant="dark"
                  onChange={handleDateChange}
                />
              </View>
            ) : null}
          </View>
        </BottomSheet.Content>
      </BottomSheet.Portal>
    </BottomSheet>
  );
});

SnoozeActionSheet.displayName = "SnoozeActionSheet";
