import { BottomSheetScrollView } from "@gorhom/bottom-sheet";
import DateTimePicker, {
  type DateTimePickerEvent,
} from "@react-native-community/datetimepicker";
import {
  type QueryClient,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useRouter } from "expo-router";
import {
  forwardRef,
  useCallback,
  useImperativeHandle,
  useMemo,
  useState,
} from "react";
import {
  ActivityIndicator,
  Alert,
  Platform,
  Pressable,
  Switch,
  View,
} from "react-native";
import type { AnyIcon } from "@/components/icons";
import {
  AppIcon,
  DiscordIcon,
  Moon02Icon,
  Settings01Icon,
  SlackIcon,
  TelegramIcon,
  WhatsappIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";
import { inAppNotificationsApi } from "../api/inapp-notifications-api";
import type {
  ChannelPlatform,
  ChannelPreferences,
  NotificationCategoryPreferences,
  NotificationPreferences,
  PlatformLink,
  PlatformLinksResponse,
  QuietHours,
} from "../types/inapp-notification-types";

const SNAP_POINTS: Array<string | number> = ["90%"];

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
  in_app: "In-App",
};

interface PlatformChannelMeta {
  id: ChannelPlatform;
  name: string;
  icon: AnyIcon;
  iconColor: string;
  iconBg: string;
}

const PLATFORM_CHANNELS: PlatformChannelMeta[] = [
  {
    id: "telegram",
    name: "Telegram",
    icon: TelegramIcon,
    iconColor: "#2AABEE",
    iconBg: "rgba(42,171,238,0.15)",
  },
  {
    id: "discord",
    name: "Discord",
    icon: DiscordIcon,
    iconColor: "#5865F2",
    iconBg: "rgba(88,101,242,0.15)",
  },
  {
    id: "whatsapp",
    name: "WhatsApp",
    icon: WhatsappIcon,
    iconColor: "#25D366",
    iconBg: "rgba(37,211,102,0.15)",
  },
  {
    id: "slack",
    name: "Slack",
    icon: SlackIcon,
    iconColor: "#E01E5A",
    iconBg: "rgba(224,30,90,0.15)",
  },
];

const DEFAULT_QUIET_HOURS: QuietHours = { from: "22:00", to: "08:00" };

const PREFERENCES_QUERY_KEY = ["notification-preferences"] as const;
const CHANNEL_PREFERENCES_QUERY_KEY = [
  "notification-channel-preferences",
] as const;
const PLATFORM_LINKS_QUERY_KEY = ["platform-links"] as const;

const DEFAULT_PREFERENCES: NotificationPreferences = {
  global: { push: true, in_app: true },
  categories: {},
  quiet_hours: null,
};

function isHttpStatus(err: unknown, status: number): boolean {
  if (typeof err !== "object" || err === null) return false;
  const candidate = (err as { status?: unknown }).status;
  return typeof candidate === "number" && candidate === status;
}

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
        thumbColor={value ? "#00bbff" : "#71717a"}
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
          color: "#71717a",
          marginBottom: spacing.xs,
        }}
      >
        {label}
      </Text>
      {channels.map((channel, idx) => (
        <View key={channel}>
          <ToggleRow
            label={CHANNEL_LABELS[channel] ?? channel}
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

interface ChannelRowProps {
  meta: PlatformChannelMeta;
  enabled: boolean;
  isConnected: boolean;
  link?: PlatformLink;
  onToggle: (val: boolean) => void;
  onConnect: () => void;
  isLast: boolean;
  isUpdating: boolean;
}

function ChannelRow({
  meta,
  enabled,
  isConnected,
  link,
  onToggle,
  onConnect,
  isLast,
  isUpdating,
}: ChannelRowProps) {
  const handle = link?.username ?? link?.displayName ?? "";
  const helper = isConnected
    ? handle
      ? `Connected as @${handle}`
      : "Connected"
    : "Connect in Linked Accounts to enable";

  return (
    <View>
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          paddingVertical: 12,
          gap: 12,
        }}
      >
        <View
          style={{
            width: 36,
            height: 36,
            borderRadius: 10,
            backgroundColor: meta.iconBg,
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
          }}
        >
          <AppIcon icon={meta.icon} size={18} color={meta.iconColor} />
        </View>

        <View style={{ flex: 1, minWidth: 0, gap: 2 }}>
          <Text
            style={{
              fontSize: 15,
              fontWeight: "600",
              color: "#ffffff",
            }}
            numberOfLines={1}
          >
            {meta.name}
          </Text>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <Text
              style={{
                fontSize: 12,
                color: "#71717a",
                flexShrink: 1,
              }}
              numberOfLines={1}
            >
              {helper}
            </Text>
            {!isConnected && (
              <Pressable onPress={onConnect} hitSlop={6}>
                <Text
                  style={{ fontSize: 12, color: "#00bbff", fontWeight: "600" }}
                >
                  Connect
                </Text>
              </Pressable>
            )}
          </View>
        </View>

        <Switch
          value={isConnected ? enabled : false}
          onValueChange={onToggle}
          disabled={!isConnected || isUpdating}
          trackColor={{ false: "#3a3a3c", true: "rgba(0,187,255,0.6)" }}
          thumbColor={isConnected && enabled ? "#00bbff" : "#71717a"}
        />
      </View>
      {!isLast && (
        <View
          style={{
            height: 1,
            backgroundColor: "rgba(255,255,255,0.06)",
            marginLeft: 48,
          }}
        />
      )}
    </View>
  );
}

interface SectionShellProps {
  title: string;
  children: React.ReactNode;
}

function SectionShell({ title, children }: SectionShellProps) {
  const { spacing, fontSize, moderateScale } = useResponsive();
  return (
    <View
      style={{
        backgroundColor: "#1c1f26",
        borderRadius: moderateScale(14, 0.5),
        paddingHorizontal: spacing.md,
        paddingTop: spacing.sm,
        paddingBottom: spacing.xs,
        marginBottom: spacing.sm,
      }}
    >
      <Text
        style={{
          fontSize: fontSize.xs,
          fontWeight: "600",
          letterSpacing: 0.6,
          textTransform: "uppercase",
          color: "#71717a",
          marginBottom: spacing.xs,
        }}
      >
        {title}
      </Text>
      {children}
    </View>
  );
}

function parseTimeToDate(value: string): Date {
  const [h, m] = value.split(":").map((s) => Number.parseInt(s, 10));
  const d = new Date();
  d.setHours(Number.isFinite(h) ? h : 0, Number.isFinite(m) ? m : 0, 0, 0);
  return d;
}

function formatDateToHHMM(date: Date): string {
  const h = String(date.getHours()).padStart(2, "0");
  const m = String(date.getMinutes()).padStart(2, "0");
  return `${h}:${m}`;
}

function formatTimeLabel(value: string): string {
  const d = parseTimeToDate(value);
  return d.toLocaleString(undefined, {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

interface QuietHoursSectionProps {
  prefs: NotificationPreferences;
  onChange: (next: NotificationPreferences) => void;
  disabled: boolean;
}

function QuietHoursSection({
  prefs,
  onChange,
  disabled,
}: QuietHoursSectionProps) {
  const { spacing, fontSize } = useResponsive();
  const enabled = !!prefs.quiet_hours;
  const quiet = prefs.quiet_hours ?? DEFAULT_QUIET_HOURS;
  const [picker, setPicker] = useState<null | "from" | "to">(null);

  const handleToggle = useCallback(
    (val: boolean) => {
      onChange({
        ...prefs,
        quiet_hours: val ? quiet : null,
      });
    },
    [onChange, prefs, quiet],
  );

  const handleTimeChange = useCallback(
    (which: "from" | "to", _evt: DateTimePickerEvent, date?: Date) => {
      if (Platform.OS === "android") {
        setPicker(null);
      }
      if (!date) return;
      const next: QuietHours = {
        ...quiet,
        [which]: formatDateToHHMM(date),
      };
      onChange({ ...prefs, quiet_hours: next });
    },
    [onChange, prefs, quiet],
  );

  return (
    <SectionShell title="Quiet Hours">
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          paddingVertical: spacing.sm,
          gap: spacing.sm,
        }}
      >
        <AppIcon icon={Moon02Icon} size={16} color="#71717a" />
        <View style={{ flex: 1 }}>
          <Text style={{ fontSize: fontSize.sm, color: "#c5cad2" }}>
            Enable quiet hours
          </Text>
          <Text style={{ fontSize: 12, color: "#71717a", marginTop: 2 }}>
            Pause notifications during a daily window
          </Text>
        </View>
        <Switch
          value={enabled}
          onValueChange={handleToggle}
          disabled={disabled}
          trackColor={{ false: "#3a3a3c", true: "rgba(0,187,255,0.6)" }}
          thumbColor={enabled ? "#00bbff" : "#71717a"}
        />
      </View>

      {enabled && (
        <View style={{ paddingBottom: spacing.xs }}>
          <View
            style={{
              height: 1,
              backgroundColor: "rgba(255,255,255,0.06)",
            }}
          />
          <Pressable
            onPress={() => setPicker("from")}
            disabled={disabled}
            style={{
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "space-between",
              paddingVertical: spacing.sm,
            }}
          >
            <Text style={{ fontSize: fontSize.sm, color: "#c5cad2" }}>
              From
            </Text>
            <Text
              style={{
                fontSize: fontSize.sm,
                color: "#00bbff",
                fontWeight: "600",
              }}
            >
              {formatTimeLabel(quiet.from)}
            </Text>
          </Pressable>
          <View
            style={{
              height: 1,
              backgroundColor: "rgba(255,255,255,0.06)",
            }}
          />
          <Pressable
            onPress={() => setPicker("to")}
            disabled={disabled}
            style={{
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "space-between",
              paddingVertical: spacing.sm,
            }}
          >
            <Text style={{ fontSize: fontSize.sm, color: "#c5cad2" }}>To</Text>
            <Text
              style={{
                fontSize: fontSize.sm,
                color: "#00bbff",
                fontWeight: "600",
              }}
            >
              {formatTimeLabel(quiet.to)}
            </Text>
          </Pressable>

          {picker !== null && (
            <DateTimePicker
              value={parseTimeToDate(picker === "from" ? quiet.from : quiet.to)}
              mode="time"
              is24Hour={false}
              display={Platform.OS === "ios" ? "spinner" : "default"}
              onChange={(evt, d) => handleTimeChange(picker, evt, d)}
              themeVariant="dark"
            />
          )}
          {Platform.OS === "ios" && picker !== null && (
            <Pressable
              onPress={() => setPicker(null)}
              style={{ alignSelf: "flex-end", paddingVertical: spacing.xs }}
            >
              <Text style={{ color: "#00bbff", fontSize: fontSize.sm }}>
                Done
              </Text>
            </Pressable>
          )}
        </View>
      )}
    </SectionShell>
  );
}

interface ChannelsSectionProps {
  links: Record<string, PlatformLink>;
  channels: ChannelPreferences;
  onChannelToggle: (channel: ChannelPlatform, value: boolean) => void;
  onConnect: () => void;
  updatingChannel: ChannelPlatform | null;
}

function ChannelsSection({
  links,
  channels,
  onChannelToggle,
  onConnect,
  updatingChannel,
}: ChannelsSectionProps) {
  return (
    <SectionShell title="Channels">
      {PLATFORM_CHANNELS.map((meta, idx) => {
        const link = links[meta.id];
        const isConnected = !!link?.platformUserId;
        return (
          <ChannelRow
            key={meta.id}
            meta={meta}
            enabled={channels[meta.id]}
            isConnected={isConnected}
            link={link}
            onToggle={(val) => onChannelToggle(meta.id, val)}
            onConnect={onConnect}
            isLast={idx === PLATFORM_CHANNELS.length - 1}
            isUpdating={updatingChannel === meta.id}
          />
        );
      })}
    </SectionShell>
  );
}

export interface NotificationPreferencesSheetRef {
  open: () => void;
  close: () => void;
}

function usePreferencesQuery(enabled: boolean) {
  return useQuery<NotificationPreferences, Error>({
    queryKey: PREFERENCES_QUERY_KEY,
    enabled,
    queryFn: async () => {
      try {
        return await inAppNotificationsApi.getNotificationPreferences();
      } catch (err) {
        // Backend may not have the endpoint persisted yet (404) or may be
        // unreachable. In either case, fall back to defaults so the sheet
        // remains usable rather than rendering an "unavailable" message.
        if (isHttpStatus(err, 404)) return DEFAULT_PREFERENCES;
        console.warn(
          "[notifications] prefs fetch failed, using defaults:",
          err,
        );
        return DEFAULT_PREFERENCES;
      }
    },
    staleTime: 30_000,
  });
}

function useChannelsQuery(enabled: boolean) {
  return useQuery<ChannelPreferences, Error>({
    queryKey: CHANNEL_PREFERENCES_QUERY_KEY,
    enabled,
    queryFn: () => inAppNotificationsApi.getChannelPreferences(),
    staleTime: 30_000,
  });
}

function usePlatformLinksQuery(enabled: boolean) {
  return useQuery<PlatformLinksResponse, Error>({
    queryKey: PLATFORM_LINKS_QUERY_KEY,
    enabled,
    queryFn: () => inAppNotificationsApi.getPlatformLinks(),
    staleTime: 30_000,
  });
}

interface OptimisticChannelContext {
  previous: ChannelPreferences | undefined;
}

function useChannelMutation(queryClient: QueryClient) {
  return useMutation<
    ChannelPreferences,
    Error,
    { channel: ChannelPlatform; enabled: boolean },
    OptimisticChannelContext
  >({
    mutationFn: ({ channel, enabled }) =>
      inAppNotificationsApi.updateChannelPreference(channel, enabled),
    onMutate: async ({ channel, enabled }) => {
      await queryClient.cancelQueries({
        queryKey: CHANNEL_PREFERENCES_QUERY_KEY,
      });
      const previous = queryClient.getQueryData<ChannelPreferences>(
        CHANNEL_PREFERENCES_QUERY_KEY,
      );
      if (previous) {
        queryClient.setQueryData<ChannelPreferences>(
          CHANNEL_PREFERENCES_QUERY_KEY,
          { ...previous, [channel]: enabled },
        );
      }
      return { previous };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.previous) {
        queryClient.setQueryData(CHANNEL_PREFERENCES_QUERY_KEY, ctx.previous);
      }
      Alert.alert("Error", "Failed to update channel preference.");
    },
    onSettled: () => {
      void queryClient.invalidateQueries({
        queryKey: CHANNEL_PREFERENCES_QUERY_KEY,
      });
    },
  });
}

export const NotificationPreferencesSheet =
  forwardRef<NotificationPreferencesSheetRef>(
    function NotificationPreferencesSheet(_props, ref) {
      const router = useRouter();
      const { spacing, fontSize } = useResponsive();
      const queryClient = useQueryClient();
      const [isOpen, setIsOpen] = useState(false);
      const [updatingPrefKey, setUpdatingPrefKey] = useState<string | null>(
        null,
      );

      useImperativeHandle(ref, () => ({
        open: () => setIsOpen(true),
        close: () => setIsOpen(false),
      }));

      const prefsQuery = usePreferencesQuery(isOpen);
      const channelsQuery = useChannelsQuery(isOpen);
      const platformLinksQuery = usePlatformLinksQuery(isOpen);
      const channelMutation = useChannelMutation(queryClient);

      const prefs = prefsQuery.data ?? null;
      const channels = channelsQuery.data ?? {
        telegram: false,
        discord: false,
        whatsapp: false,
        slack: false,
      };
      const platformLinks = platformLinksQuery.data?.platform_links ?? {};

      const isLoading =
        prefsQuery.isLoading ||
        channelsQuery.isLoading ||
        platformLinksQuery.isLoading;

      const handlePersistPrefs = useCallback(
        async (next: NotificationPreferences, key: string) => {
          const previous = queryClient.getQueryData<NotificationPreferences>(
            PREFERENCES_QUERY_KEY,
          );
          queryClient.setQueryData(PREFERENCES_QUERY_KEY, next);
          setUpdatingPrefKey(key);
          try {
            await inAppNotificationsApi.updateNotificationPreferences(next);
          } catch {
            if (previous) {
              queryClient.setQueryData(PREFERENCES_QUERY_KEY, previous);
            }
            Alert.alert("Error", "Failed to update preference.");
          } finally {
            setUpdatingPrefKey(null);
          }
        },
        [queryClient],
      );

      const handleCategoryToggle = useCallback(
        async (
          category: string,
          channel: keyof NotificationCategoryPreferences,
          value: boolean,
        ) => {
          if (!prefs) return;

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

          await handlePersistPrefs(updatedPrefs, `${category}.${channel}`);
        },
        [prefs, handlePersistPrefs],
      );

      const handleQuietHoursChange = useCallback(
        async (next: NotificationPreferences) => {
          await handlePersistPrefs(next, "quiet_hours");
        },
        [handlePersistPrefs],
      );

      const handleChannelToggle = useCallback(
        (channel: ChannelPlatform, value: boolean) => {
          channelMutation.mutate({ channel, enabled: value });
        },
        [channelMutation],
      );

      const handleConnect = useCallback(() => {
        setIsOpen(false);
        router.push("/integrations");
      }, [router]);

      const categoryEntries = useMemo(
        () => (prefs ? Object.entries(prefs.categories) : []),
        [prefs],
      );

      const updatingChannel: ChannelPlatform | null = channelMutation.isPending
        ? (channelMutation.variables?.channel ?? null)
        : null;

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
                  <AppIcon icon={Settings01Icon} size={18} color="#71717a" />
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
                    <QuietHoursSection
                      prefs={prefs}
                      onChange={(next) => {
                        void handleQuietHoursChange(next);
                      }}
                      disabled={updatingPrefKey === "quiet_hours"}
                    />

                    <ChannelsSection
                      links={platformLinks}
                      channels={channels}
                      onChannelToggle={handleChannelToggle}
                      onConnect={handleConnect}
                      updatingChannel={updatingChannel}
                    />

                    {/* Global category section */}
                    <CategorySection
                      category="global"
                      prefs={prefs.global}
                      onToggle={(cat, ch, val) => {
                        void handleCategoryToggle(cat, ch, val);
                      }}
                      disabled={updatingPrefKey !== null}
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
                              void handleCategoryToggle(c, ch, val);
                            }}
                            disabled={updatingPrefKey !== null}
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
                    <Text style={{ color: "#71717a", fontSize: fontSize.sm }}>
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
                  <Text style={{ color: "#71717a", fontSize: fontSize.sm }}>
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
