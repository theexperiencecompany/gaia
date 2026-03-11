import { useCallback, useState } from "react";
import { FlatList, RefreshControl, View } from "react-native";
import { EmptyState } from "@/components/EmptyState";
import { CheckmarkCircle02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  type RealtimeNotification,
  useRealtimeNotifications,
} from "../hooks/use-realtime-notifications";

interface NotificationItemProps {
  notification: RealtimeNotification;
  isUnread: boolean;
  onPress: (id: string) => void;
}

function NotificationItem({
  notification,
  isUnread,
  onPress,
}: NotificationItemProps) {
  const timeLabel = formatRelativeTime(notification.receivedAt);

  return (
    <View
      className="flex-row items-start px-4 py-3 border-b border-muted/10"
      style={isUnread ? { backgroundColor: "rgba(22,193,255,0.05)" } : {}}
    >
      {isUnread && (
        <View
          style={{
            width: 7,
            height: 7,
            borderRadius: 3.5,
            backgroundColor: "#16c1ff",
            marginTop: 6,
            marginRight: 10,
          }}
        />
      )}
      {!isUnread && <View style={{ width: 17 }} />}
      <View className="flex-1">
        <Text
          className={isUnread ? "text-sm font-semibold" : "text-sm"}
          numberOfLines={1}
          onPress={() => onPress(notification.id)}
        >
          {notification.title}
        </Text>
        {notification.body.length > 0 && (
          <Text className="text-xs text-muted mt-0.5" numberOfLines={2}>
            {notification.body}
          </Text>
        )}
        <Text className="text-xs text-muted mt-1">{timeLabel}</Text>
      </View>
    </View>
  );
}

function formatRelativeTime(date: Date): string {
  const diffMs = Date.now() - date.getTime();
  const diffSecs = Math.floor(diffMs / 1000);

  if (diffSecs < 60) return "just now";
  if (diffSecs < 3600) return `${Math.floor(diffSecs / 60)}m ago`;
  if (diffSecs < 86400) return `${Math.floor(diffSecs / 3600)}h ago`;
  return `${Math.floor(diffSecs / 86400)}d ago`;
}

export function RealtimeNotificationsList() {
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [readIds, setReadIds] = useState<Set<string>>(new Set());

  const { recentNotifications, clearRecent, connect } =
    useRealtimeNotifications({
      showLocalNotification: false,
    });

  const handleRefresh = useCallback(async () => {
    setIsRefreshing(true);
    clearRecent();
    setReadIds(new Set());
    try {
      await connect();
    } catch {
      // Ignore reconnect errors; the hook manages state
    }
    setIsRefreshing(false);
  }, [clearRecent, connect]);

  const handlePress = useCallback((id: string) => {
    setReadIds((prev) => new Set(prev).add(id));
  }, []);

  const renderItem = useCallback(
    ({ item }: { item: RealtimeNotification }) => (
      <NotificationItem
        notification={item}
        isUnread={!readIds.has(item.id)}
        onPress={handlePress}
      />
    ),
    [readIds, handlePress],
  );

  const keyExtractor = useCallback((item: RealtimeNotification) => item.id, []);

  return (
    <View className="flex-1 bg-background">
      <FlatList
        data={recentNotifications}
        keyExtractor={keyExtractor}
        renderItem={renderItem}
        refreshControl={
          <RefreshControl
            refreshing={isRefreshing}
            onRefresh={handleRefresh}
            tintColor="#8e8e93"
            colors={["#16c1ff"]}
          />
        }
        ListEmptyComponent={
          <EmptyState
            icon={CheckmarkCircle02Icon}
            iconColor="#22c55e"
            title="You're all caught up"
            description="No new notifications in this session"
          />
        }
        contentContainerStyle={
          recentNotifications.length === 0 ? { flex: 1 } : { paddingBottom: 24 }
        }
        showsVerticalScrollIndicator={false}
      />
    </View>
  );
}
