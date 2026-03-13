import { useQueries } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { Button, Divider, Skeleton, SkeletonGroup } from "heroui-native";
import { useCallback } from "react";
import { RefreshControl, ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import {
  AlarmClockIcon,
  BubbleChatIcon,
  CheckListIcon,
  Notification01Icon,
  ZapIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useAuth } from "@/features/auth/hooks/use-auth";
import { useResponsive } from "@/lib/responsive";
import { dashboardApi } from "../api/dashboard-api";
import { DashboardCard } from "./DashboardCard";
import { DashboardTodoItem } from "./DashboardTodoItem";

const ACCENT = "#00bbff";

function getGreeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

function formatDate(): string {
  return new Date().toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
  });
}

function formatReminderTime(nextRunAt: string | undefined): string {
  if (!nextRunAt) return "Scheduled";
  const date = new Date(nextRunAt);
  const now = new Date();
  const diffMs = date.getTime() - now.getTime();
  const diffMins = Math.round(diffMs / 60000);

  if (diffMins < 0) return "Overdue";
  if (diffMins < 60) return `In ${diffMins}m`;
  const diffHours = Math.round(diffMins / 60);
  if (diffHours < 24) return `In ${diffHours}h`;
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

const QUERY_KEYS = {
  todayTodos: ["dashboard", "today-todos"] as const,
  recentConversations: ["dashboard", "recent-conversations"] as const,
  unreadCount: ["dashboard", "unread-count"] as const,
  upcomingReminders: ["dashboard", "upcoming-reminders"] as const,
  activeWorkflows: ["dashboard", "active-workflows"] as const,
};

export function DashboardScreen() {
  const { spacing, fontSize } = useResponsive();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { user } = useAuth();

  const firstName = user?.name?.split(" ")[0] ?? "there";

  const [
    todosQuery,
    conversationsQuery,
    unreadQuery,
    remindersQuery,
    workflowsQuery,
  ] = useQueries({
    queries: [
      {
        queryKey: QUERY_KEYS.todayTodos,
        queryFn: dashboardApi.getTodayTodos,
        staleTime: 2 * 60 * 1000,
      },
      {
        queryKey: QUERY_KEYS.recentConversations,
        queryFn: dashboardApi.getRecentConversations,
        staleTime: 2 * 60 * 1000,
      },
      {
        queryKey: QUERY_KEYS.unreadCount,
        queryFn: dashboardApi.getUnreadNotificationsCount,
        staleTime: 60 * 1000,
      },
      {
        queryKey: QUERY_KEYS.upcomingReminders,
        queryFn: dashboardApi.getUpcomingReminders,
        staleTime: 5 * 60 * 1000,
      },
      {
        queryKey: QUERY_KEYS.activeWorkflows,
        queryFn: dashboardApi.getActiveWorkflowsCount,
        staleTime: 5 * 60 * 1000,
      },
    ],
  });

  const isRefreshing =
    todosQuery.isRefetching ||
    conversationsQuery.isRefetching ||
    unreadQuery.isRefetching ||
    remindersQuery.isRefetching ||
    workflowsQuery.isRefetching;

  const handleRefresh = useCallback(() => {
    void todosQuery.refetch();
    void conversationsQuery.refetch();
    void unreadQuery.refetch();
    void remindersQuery.refetch();
    void workflowsQuery.refetch();
  }, [
    todosQuery,
    conversationsQuery,
    unreadQuery,
    remindersQuery,
    workflowsQuery,
  ]);

  const todayTodos = todosQuery.data ?? [];
  const conversations = conversationsQuery.data ?? [];
  const unreadCount = unreadQuery.data ?? 0;
  const reminders = remindersQuery.data ?? [];
  const activeWorkflowCount = workflowsQuery.data ?? 0;

  return (
    <View style={{ flex: 1, backgroundColor: "#0b0c0f" }}>
      <ScrollView
        contentContainerStyle={{
          paddingTop: insets.top + spacing.md,
          paddingBottom: insets.bottom + spacing.xl,
          paddingHorizontal: spacing.md,
        }}
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl
            refreshing={isRefreshing}
            onRefresh={handleRefresh}
            tintColor={ACCENT}
            colors={[ACCENT]}
          />
        }
      >
        {/* Greeting header */}
        <View style={{ marginBottom: spacing.lg }}>
          <Text
            style={{
              fontSize: fontSize["2xl"],
              fontWeight: "700",
              color: "#f4f4f5",
            }}
          >
            {getGreeting()}, {firstName}!
          </Text>
          <Text
            style={{
              fontSize: fontSize.sm,
              color: "#71717a",
              marginTop: 4,
            }}
          >
            {formatDate()}
          </Text>
        </View>

        {/* Today's Todos */}
        <DashboardCard
          title="Today's Tasks"
          icon={CheckListIcon}
          iconColor="#22c55e"
          badge={todosQuery.data?.length}
          subtitle={
            todayTodos.length === 0 && !todosQuery.isLoading
              ? "No tasks due today"
              : undefined
          }
          onPress={() => {
            router.push("/(app)/(tabs)/todos");
          }}
        >
          {todosQuery.isLoading ? (
            <SkeletonGroup
              isLoading
              style={{ padding: spacing.md, gap: spacing.sm }}
            >
              <SkeletonGroup.Item
                className="h-8 w-full rounded-lg"
                style={{ marginBottom: spacing.xs }}
              />
              <SkeletonGroup.Item
                className="h-8 w-4/5 rounded-lg"
                style={{ marginBottom: spacing.xs }}
              />
              <SkeletonGroup.Item className="h-8 w-3/4 rounded-lg" />
            </SkeletonGroup>
          ) : todayTodos.length > 0 ? (
            <>
              {todayTodos.map((todo) => (
                <DashboardTodoItem key={todo.id} todo={todo} />
              ))}
              <Divider style={{ marginHorizontal: spacing.md }} />
              <Button
                variant="ghost"
                size="sm"
                onPress={() => {
                  router.push("/(app)/(tabs)/todos");
                }}
                style={{
                  alignSelf: "flex-start",
                  paddingHorizontal: spacing.md,
                  paddingVertical: spacing.sm,
                }}
              >
                <Button.Label
                  style={{
                    fontSize: fontSize.xs,
                    color: ACCENT,
                    fontWeight: "500",
                  }}
                >
                  View all tasks
                </Button.Label>
              </Button>
            </>
          ) : null}
        </DashboardCard>

        {/* Upcoming Reminders */}
        <DashboardCard
          title="Upcoming Reminders"
          icon={AlarmClockIcon}
          iconColor="#f59e0b"
          badge={reminders.length > 0 ? reminders.length : undefined}
          subtitle={
            reminders.length === 0 && !remindersQuery.isLoading
              ? "No upcoming reminders"
              : undefined
          }
          onPress={undefined}
        >
          {remindersQuery.isLoading ? (
            <SkeletonGroup
              isLoading
              style={{ padding: spacing.md, gap: spacing.sm }}
            >
              <SkeletonGroup.Item
                className="h-10 w-full rounded-lg"
                style={{ marginBottom: spacing.xs }}
              />
              <SkeletonGroup.Item className="h-10 w-4/5 rounded-lg" />
            </SkeletonGroup>
          ) : reminders.length > 0 ? (
            reminders.map((reminder, index) => (
              <View key={reminder.id}>
                <View
                  style={{
                    flexDirection: "row",
                    alignItems: "center",
                    paddingHorizontal: spacing.md,
                    paddingVertical: spacing.sm + 2,
                    gap: spacing.sm,
                  }}
                >
                  <View style={{ flex: 1 }}>
                    <Text
                      numberOfLines={1}
                      style={{
                        fontSize: fontSize.sm,
                        fontWeight: "500",
                        color: "#e4e4e7",
                      }}
                    >
                      {reminder.title}
                    </Text>
                    {reminder.description ? (
                      <Text
                        numberOfLines={1}
                        style={{
                          fontSize: fontSize.xs,
                          color: "#71717a",
                          marginTop: 2,
                        }}
                      >
                        {reminder.description}
                      </Text>
                    ) : null}
                  </View>
                  <View
                    style={{
                      backgroundColor: "rgba(245,158,11,0.12)",
                      borderRadius: 8,
                      paddingHorizontal: 8,
                      paddingVertical: 3,
                    }}
                  >
                    <Text
                      style={{
                        fontSize: fontSize.xs,
                        color: "#f59e0b",
                        fontWeight: "500",
                      }}
                    >
                      {formatReminderTime(reminder.nextRunAt)}
                    </Text>
                  </View>
                </View>
                {index < reminders.length - 1 && (
                  <Divider style={{ marginHorizontal: spacing.md }} />
                )}
              </View>
            ))
          ) : null}
        </DashboardCard>

        {/* Recent Conversations */}
        <DashboardCard
          title="Recent Chats"
          icon={BubbleChatIcon}
          iconColor={ACCENT}
          subtitle={
            conversations.length === 0 && !conversationsQuery.isLoading
              ? "No recent conversations"
              : undefined
          }
          onPress={() => {
            router.push("/(app)/(tabs)");
          }}
        >
          {conversationsQuery.isLoading ? (
            <SkeletonGroup
              isLoading
              style={{ padding: spacing.md, gap: spacing.sm }}
            >
              <SkeletonGroup.Item
                className="h-8 w-full rounded-lg"
                style={{ marginBottom: spacing.xs }}
              />
              <SkeletonGroup.Item
                className="h-8 w-3/4 rounded-lg"
                style={{ marginBottom: spacing.xs }}
              />
              <SkeletonGroup.Item className="h-8 w-4/5 rounded-lg" />
            </SkeletonGroup>
          ) : conversations.length > 0 ? (
            conversations.map((conv, index) => (
              <View key={conv.id}>
                <View
                  style={{
                    flexDirection: "row",
                    alignItems: "center",
                    paddingHorizontal: spacing.md,
                    paddingVertical: spacing.sm + 2,
                    gap: spacing.sm,
                  }}
                >
                  <View
                    style={{
                      width: 8,
                      height: 8,
                      borderRadius: 4,
                      backgroundColor: conv.is_unread
                        ? ACCENT
                        : "rgba(255,255,255,0.15)",
                      flexShrink: 0,
                    }}
                  />
                  <Text
                    numberOfLines={1}
                    style={{
                      flex: 1,
                      fontSize: fontSize.sm,
                      fontWeight: conv.is_unread ? "600" : "400",
                      color: conv.is_unread ? "#f4f4f5" : "#a1a1aa",
                    }}
                  >
                    {conv.title}
                  </Text>
                </View>
                {index < conversations.length - 1 && (
                  <Divider style={{ marginHorizontal: spacing.md }} />
                )}
              </View>
            ))
          ) : null}
        </DashboardCard>

        {/* Active Workflows + Unread Notifications — side by side */}
        <View style={{ flexDirection: "row", gap: spacing.sm }}>
          {/* Active Workflows */}
          <View style={{ flex: 1 }}>
            <DashboardCard
              title="Workflows"
              icon={ZapIcon}
              iconColor="#a78bfa"
              badge={activeWorkflowCount > 0 ? activeWorkflowCount : undefined}
              subtitle={
                workflowsQuery.isLoading ? (
                  <Skeleton
                    isLoading
                    className="h-3 w-16 rounded"
                    style={{ marginTop: 2 }}
                  />
                ) : (
                  <Text style={{ fontSize: fontSize.xs, color: "#71717a" }}>
                    {`${activeWorkflowCount} active`}
                  </Text>
                )
              }
              onPress={() => {
                router.push("/(app)/(tabs)/workflows");
              }}
            />
          </View>

          {/* Unread Notifications */}
          <View style={{ flex: 1 }}>
            <DashboardCard
              title="Alerts"
              icon={Notification01Icon}
              iconColor="#f43f5e"
              badge={unreadCount > 0 ? unreadCount : undefined}
              subtitle={
                unreadQuery.isLoading ? (
                  <Skeleton
                    isLoading
                    className="h-3 w-16 rounded"
                    style={{ marginTop: 2 }}
                  />
                ) : (
                  <Text style={{ fontSize: fontSize.xs, color: "#71717a" }}>
                    {unreadCount > 0
                      ? `${unreadCount} unread`
                      : "All caught up"}
                  </Text>
                )
              }
              onPress={() => {
                router.push("/(app)/(tabs)/notifications");
              }}
            />
          </View>
        </View>
      </ScrollView>
    </View>
  );
}
