import { BottomSheetScrollView } from "@gorhom/bottom-sheet";
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useState,
} from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  Switch,
  View,
} from "react-native";
import { AppIcon, Settings01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";
import { inAppNotificationsApi } from "../api/inapp-notifications-api";
import type {
  NotificationCategoryPreferences,
  NotificationPreferences,
} from "../types/inapp-notification-types";

const SNAP_POINTS: Array<string | number> = ["75%"];

const CATEGORY_LABELS: Record<string, string> = {
  global: "All Notifications",
  email: "Email",
  calendar: "Calendar",
  todo: "Tasks & Todos",
  workflow: "Workflows",
  system: "System",
};

const CHANNEL_LABELS: Record<keyof NotificationCategoryPreferences, string> = {
  push: "Push",
  email: "Email",
  in_app: "In-App",
};

interface ToggleRowProps {
  label: string;
  value: boolean;
  onToggle: (val: boolean) => void;
  disabled?: boolean;
}

function ToggleRow({
  label,
  value,
  onToggle,
  disabled = false,
}: ToggleRowProps) {
  const { spacing, fontSize } = useResponsive();

  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        paddingVertical: spacing.sm,
        gap: spacing.sm,
      }}
    >
      <Text
        style={{
          flex: 1,
          fontSize: fontSize.sm,
          color: disabled ? "#636366" : "#c5cad2",
        }}
      >
        {label}
      </Text>
      <Switch
        value={value}
        onValueChange={onToggle}
        disabled={disabled}
        trackColor={{ false: "#3a3a3c", true: "rgba(0,187,255,0.6)" }}
        thumbColor={value ? "#00bbff" : "#8e8e93"}
      />
    </View>
  );
}

interface CategorySectionProps {
  category: string;
  prefs: NotificationCategoryPreferences;
  onToggle: (
    category: string,
    channel: keyof NotificationCategoryPreferences,
    value: boolean,
  ) => void;
  disabled?: boolean;
}

function CategorySection({
  category,
  prefs,
  onToggle,
  disabled = false,
}: CategorySectionProps) {
  const { spacing, fontSize, moderateScale } = useResponsive();
  const label = CATEGORY_LABELS[category] ?? category;
  const channels = Object.keys(CHANNEL_LABELS) as Array<
    keyof NotificationCategoryPreferences
  >;

  return (
    <View
      style={{
        backgroundColor: "#1c1f26",
        borderRadius: moderateScale(14, 0.5),
        paddingHorizontal: spacing.md,
        paddingTop: spacing.sm,
        paddingBottom: 2,
        marginBottom: spacing.sm,
      }}
    >
      <Text
        style={{
          fontSize: fontSize.xs,
          fontWeight: "600",
          letterSpacing: 0.6,
          textTransform: "uppercase",
          color: "#8e8e93",
          marginBottom: spacing.xs,
        }}
      >
        {label}
      </Text>
      {channels.map((channel, idx) => (
        <View key={channel}>
          <ToggleRow
            label={CHANNEL_LABELS[channel]}
            value={prefs[channel]}
            disabled={disabled}
            onToggle={(val) => onToggle(category, channel, val)}
          />
          {idx < channels.length - 1 && (
            <View
              style={{
                height: 1,
                backgroundColor: "rgba(255,255,255,0.06)",
              }}
            />
          )}
        </View>
      ))}
    </View>
  );
}

export interface NotificationPreferencesSheetRef {
  open: () => void;
  close: () => void;
}

export const NotificationPreferencesSheet =
  forwardRef<NotificationPreferencesSheetRef>(
    function NotificationPreferencesSheet(_props, ref) {
      const { spacing, fontSize } = useResponsive();
      const [isOpen, setIsOpen] = useState(false);

      useImperativeHandle(ref, () => ({
        open: () => setIsOpen(true),
        close: () => setIsOpen(false),
      }));

      const [prefs, setPrefs] = useState<NotificationPreferences | null>(null);
      const [isLoading, setIsLoading] = useState(false);
      const [updatingKey, setUpdatingKey] = useState<string | null>(null);

      useEffect(() => {
        let cancelled = false;
        setIsLoading(true);

        inAppNotificationsApi
          .getNotificationPreferences()
          .then((data) => {
            if (!cancelled) setPrefs(data);
          })
          .catch(() => {
            if (!cancelled)
              Alert.alert("Error", "Failed to load notification preferences.");
          })
          .finally(() => {
            if (!cancelled) setIsLoading(false);
          });

        return () => {
          cancelled = true;
        };
      }, []);

      const handleToggle = useCallback(
        async (
          category: string,
          channel: keyof NotificationCategoryPreferences,
          value: boolean,
        ) => {
          if (!prefs) return;

          const key = `${category}.${channel}`;
          setUpdatingKey(key);

          const previousPrefs = prefs;

          const updatedCategoryPrefs: NotificationCategoryPreferences =
            category === "global"
              ? { ...prefs.global, [channel]: value }
              : {
                  ...(prefs.categories[category] ?? prefs.global),
                  [channel]: value,
                };

          const updatedPrefs: NotificationPreferences =
            category === "global"
              ? { ...prefs, global: updatedCategoryPrefs }
              : {
                  ...prefs,
                  categories: {
                    ...prefs.categories,
                    [category]: updatedCategoryPrefs,
                  },
                };

          setPrefs(updatedPrefs);

          try {
            await inAppNotificationsApi.updateNotificationPreferences(
              updatedPrefs,
            );
          } catch {
            setPrefs(previousPrefs);
            Alert.alert("Error", "Failed to update preference.");
          } finally {
            setUpdatingKey(null);
          }
        },
        [prefs],
      );

      const categoryEntries = prefs ? Object.entries(prefs.categories) : [];

      return (
        <BottomSheet isOpen={isOpen} onOpenChange={setIsOpen}>
          <BottomSheet.Portal>
            <BottomSheet.Overlay />
            <BottomSheet.Content
              snapPoints={SNAP_POINTS}
              enableDynamicSizing={false}
              enablePanDownToClose
              backgroundStyle={{ backgroundColor: "#131416" }}
              handleIndicatorStyle={{ backgroundColor: "#48484a", width: 40 }}
            >
              <BottomSheetScrollView
                contentContainerStyle={{
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
                  <AppIcon icon={Settings01Icon} size={18} color="#8e8e93" />
                  <Text
                    style={{
                      fontSize: fontSize.base,
                      fontWeight: "600",
                      color: "#e8ebef",
                    }}
                  >
                    Notification Preferences
                  </Text>
                </View>

                {isLoading ? (
                  <View
                    style={{
                      flex: 1,
                      alignItems: "center",
                      justifyContent: "center",
                      paddingVertical: spacing.xl,
                    }}
                  >
                    <ActivityIndicator color="#00bbff" />
                  </View>
                ) : prefs ? (
                  <>
                    {/* Global section */}
                    <CategorySection
                      category="global"
                      prefs={prefs.global}
                      onToggle={(cat, ch, val) => {
                        void handleToggle(cat, ch, val);
                      }}
                      disabled={updatingKey !== null}
                    />

                    {/* Per-category sections */}
                    {categoryEntries.length > 0 && (
                      <>
                        <Text
                          style={{
                            fontSize: fontSize.xs,
                            color: "#636366",
                            marginBottom: spacing.sm,
                            marginTop: spacing.xs,
                          }}
                        >
                          Override global settings per category
                        </Text>
                        {categoryEntries.map(([cat, catPrefs]) => (
                          <CategorySection
                            key={cat}
                            category={cat}
                            prefs={catPrefs}
                            onToggle={(c, ch, val) => {
                              void handleToggle(c, ch, val);
                            }}
                            disabled={updatingKey !== null}
                          />
                        ))}
                      </>
                    )}
                  </>
                ) : (
                  <View
                    style={{
                      alignItems: "center",
                      paddingVertical: spacing.xl,
                    }}
                  >
                    <Text style={{ color: "#8e8e93", fontSize: fontSize.sm }}>
                      No preferences available.
                    </Text>
                  </View>
                )}

                <Pressable
                  style={{
                    marginTop: spacing.md,
                    alignItems: "center",
                    paddingVertical: spacing.sm,
                  }}
                  onPress={() => setIsOpen(false)}
                >
                  <Text style={{ color: "#8e8e93", fontSize: fontSize.sm }}>
                    Close
                  </Text>
                </Pressable>
              </BottomSheetScrollView>
            </BottomSheet.Content>
          </BottomSheet.Portal>
        </BottomSheet>
      );
    },
  );
