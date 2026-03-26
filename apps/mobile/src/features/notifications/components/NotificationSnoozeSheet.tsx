import DateTimePicker, {
  type DateTimePickerEvent,
} from "@react-native-community/datetimepicker";
import * as Haptics from "expo-haptics";
import {
  forwardRef,
  useCallback,
  useImperativeHandle,
  useMemo,
  useState,
} from "react";
import { Platform, Pressable, View } from "react-native";
import { AlarmClockIcon, AppIcon, Cancel01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";
import { inAppNotificationsApi } from "../api/inapp-notifications-api";

export interface NotificationSnoozeSheetRef {
  open: (notificationId: string) => void;
  close: () => void;
}

interface SnoozeOption {
  label: string;
  description: string;
  getDate: () => Date;
}

function buildSnoozeOptions(): SnoozeOption[] {
  return [
    {
      label: "1 hour",
      description: "Remind me in 1 hour",
      getDate: () => {
        const d = new Date();
        d.setHours(d.getHours() + 1);
        return d;
      },
    },
    {
      label: "3 hours",
      description: "Remind me in 3 hours",
      getDate: () => {
        const d = new Date();
        d.setHours(d.getHours() + 3);
        return d;
      },
    },
    {
      label: "Tomorrow morning",
      description: "9:00 AM tomorrow",
      getDate: () => {
        const d = new Date();
        d.setDate(d.getDate() + 1);
        d.setHours(9, 0, 0, 0);
        return d;
      },
    },
    {
      label: "Tomorrow evening",
      description: "6:00 PM tomorrow",
      getDate: () => {
        const d = new Date();
        d.setDate(d.getDate() + 1);
        d.setHours(18, 0, 0, 0);
        return d;
      },
    },
  ];
}

export const NotificationSnoozeSheet = forwardRef<NotificationSnoozeSheetRef>(
  function NotificationSnoozeSheet(_props, ref) {
    const { spacing, fontSize, moderateScale } = useResponsive();
    const [isOpen, setIsOpen] = useState(false);
    const snapPoints = useMemo(() => ["55%"], []);

    const [notificationId, setNotificationId] = useState<string | null>(null);
    const [showCustomPicker, setShowCustomPicker] = useState(false);
    const [customDate, setCustomDate] = useState<Date>(() => {
      const d = new Date();
      d.setHours(d.getHours() + 1);
      return d;
    });
    const [isSnoozin, setIsSnoozin] = useState(false);

    useImperativeHandle(ref, () => ({
      open: (id: string) => {
        setNotificationId(id);
        setShowCustomPicker(false);
        setCustomDate(() => {
          const d = new Date();
          d.setHours(d.getHours() + 1);
          return d;
        });
        setIsOpen(true);
      },
      close: () => {
        setIsOpen(false);
      },
    }));

    const handleSnooze = useCallback(
      async (snoozeUntil: Date) => {
        if (!notificationId || isSnoozin) return;
        setIsSnoozin(true);
        void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
        try {
          await inAppNotificationsApi.snoozeNotification(
            notificationId,
            snoozeUntil,
          );
        } finally {
          setIsSnoozin(false);
          setIsOpen(false);
        }
      },
      [notificationId, isSnoozin],
    );

    const handleCustomDateChange = useCallback(
      (_event: DateTimePickerEvent, selected?: Date) => {
        if (selected) {
          setCustomDate(selected);
        }
      },
      [],
    );

    const snoozeOptions = useMemo(() => buildSnoozeOptions(), []);

    return (
      <BottomSheet isOpen={isOpen} onOpenChange={setIsOpen}>
        <BottomSheet.Portal>
          <BottomSheet.Overlay />
          <BottomSheet.Content
            snapPoints={snapPoints}
            enableDynamicSizing={false}
            enablePanDownToClose
            backgroundStyle={{ backgroundColor: "#131416" }}
            handleIndicatorStyle={{ backgroundColor: "#48484a", width: 40 }}
          >
            <View
              style={{
                paddingHorizontal: spacing.md,
                paddingBottom: spacing.xl,
              }}
            >
              {/* Header */}
              <View
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  gap: spacing.sm,
                  paddingVertical: spacing.md,
                  marginBottom: spacing.sm,
                }}
              >
                <AppIcon icon={AlarmClockIcon} size={18} color="#fbbf24" />
                <Text
                  style={{
                    fontSize: fontSize.base,
                    fontWeight: "600",
                    color: "#e8ebef",
                    flex: 1,
                  }}
                >
                  Snooze Notification
                </Text>
                <Pressable
                  onPress={() => setIsOpen(false)}
                  hitSlop={8}
                  style={{ opacity: 0.6 }}
                >
                  <AppIcon icon={Cancel01Icon} size={18} color="#8e8e93" />
                </Pressable>
              </View>

              {/* Preset options */}
              <View style={{ gap: spacing.sm }}>
                {snoozeOptions.map((option) => (
                  <Pressable
                    key={option.label}
                    disabled={isSnoozin}
                    onPress={() => void handleSnooze(option.getDate())}
                    style={{
                      flexDirection: "row",
                      alignItems: "center",
                      backgroundColor: "#1c1f26",
                      borderRadius: moderateScale(12, 0.5),
                      paddingHorizontal: spacing.md,
                      paddingVertical: spacing.sm + 2,
                      gap: spacing.sm,
                      opacity: isSnoozin ? 0.5 : 1,
                    }}
                  >
                    <View style={{ flex: 1 }}>
                      <Text
                        style={{
                          fontSize: fontSize.sm,
                          fontWeight: "500",
                          color: "#e8ebef",
                        }}
                      >
                        {option.label}
                      </Text>
                      <Text
                        style={{
                          fontSize: fontSize.xs,
                          color: "#8e8e93",
                          marginTop: 2,
                        }}
                      >
                        {option.description}
                      </Text>
                    </View>
                    <AppIcon icon={AlarmClockIcon} size={16} color="#fbbf24" />
                  </Pressable>
                ))}

                {/* Custom time option */}
                <Pressable
                  onPress={() => setShowCustomPicker((prev) => !prev)}
                  style={{
                    flexDirection: "row",
                    alignItems: "center",
                    backgroundColor: showCustomPicker
                      ? "rgba(251,191,36,0.12)"
                      : "#1c1f26",
                    borderRadius: moderateScale(12, 0.5),
                    paddingHorizontal: spacing.md,
                    paddingVertical: spacing.sm + 2,
                    gap: spacing.sm,
                    borderWidth: showCustomPicker ? 1 : 0,
                    borderColor: showCustomPicker
                      ? "rgba(251,191,36,0.4)"
                      : "transparent",
                  }}
                >
                  <View style={{ flex: 1 }}>
                    <Text
                      style={{
                        fontSize: fontSize.sm,
                        fontWeight: "500",
                        color: showCustomPicker ? "#fbbf24" : "#e8ebef",
                      }}
                    >
                      Custom time
                    </Text>
                    <Text
                      style={{
                        fontSize: fontSize.xs,
                        color: "#8e8e93",
                        marginTop: 2,
                      }}
                    >
                      Pick a specific date and time
                    </Text>
                  </View>
                  <AppIcon icon={AlarmClockIcon} size={16} color="#8e8e93" />
                </Pressable>

                {/* Inline date/time picker for custom option */}
                {showCustomPicker && (
                  <View
                    style={{
                      backgroundColor: "#1c1f26",
                      borderRadius: moderateScale(12, 0.5),
                      padding: spacing.sm,
                      gap: spacing.sm,
                    }}
                  >
                    <DateTimePicker
                      value={customDate}
                      mode="datetime"
                      display={Platform.OS === "ios" ? "spinner" : "default"}
                      minimumDate={new Date()}
                      onChange={handleCustomDateChange}
                      themeVariant="dark"
                      style={{ flex: 1 }}
                      textColor="#e8ebef"
                    />
                    <Pressable
                      disabled={isSnoozin}
                      onPress={() => void handleSnooze(customDate)}
                      style={{
                        backgroundColor: "rgba(251,191,36,0.15)",
                        borderRadius: 10,
                        paddingVertical: spacing.sm + 2,
                        alignItems: "center",
                        opacity: isSnoozin ? 0.5 : 1,
                      }}
                    >
                      <Text
                        style={{
                          fontSize: fontSize.sm,
                          fontWeight: "600",
                          color: "#fbbf24",
                        }}
                      >
                        {isSnoozin ? "Snoozing..." : "Snooze until this time"}
                      </Text>
                    </Pressable>
                  </View>
                )}
              </View>
            </View>
          </BottomSheet.Content>
        </BottomSheet.Portal>
      </BottomSheet>
    );
  },
);
