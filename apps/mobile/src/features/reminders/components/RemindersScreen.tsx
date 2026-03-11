import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  RefreshControl,
  ScrollView,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import {
  Add01Icon,
  ArrowLeft01Icon,
  Notification01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { useReminders } from "../hooks/use-reminders";
import { CreateReminderSheet } from "./CreateReminderSheet";
import { ReminderCard } from "./ReminderCard";

function EmptyState() {
  const { spacing, fontSize } = useResponsive();
  return (
    <View
      style={{
        flex: 1,
        alignItems: "center",
        justifyContent: "center",
        paddingHorizontal: spacing.xl,
        gap: spacing.md,
        paddingVertical: spacing.xl * 2,
      }}
    >
      <View
        style={{
          width: 64,
          height: 64,
          borderRadius: 32,
          backgroundColor: "rgba(22,193,255,0.08)",
          alignItems: "center",
          justifyContent: "center",
          marginBottom: spacing.sm,
        }}
      >
        <Notification01Icon size={28} color="#16c1ff" />
      </View>
      <Text
        style={{
          fontSize: fontSize.lg,
          fontWeight: "600",
          color: "#e8ebef",
          textAlign: "center",
        }}
      >
        No reminders yet
      </Text>
      <Text
        style={{
          fontSize: fontSize.sm,
          color: "#52525b",
          textAlign: "center",
          lineHeight: fontSize.sm * 1.5,
        }}
      >
        Create a reminder to get notified on a recurring schedule.
      </Text>
    </View>
  );
}

export function RemindersScreen() {
  const router = useRouter();
  const { spacing, fontSize } = useResponsive();
  const insets = useSafeAreaInsets();
  const [showCreate, setShowCreate] = useState(false);

  const {
    activeReminders,
    pausedReminders,
    reminders,
    isLoading,
    isRefreshing,
    error,
    refetch,
    createReminder,
    pauseReminder,
    resumeReminder,
    deleteReminder,
    isCreating,
  } = useReminders();

  useFocusEffect(
    useCallback(() => {
      void refetch();
    }, [refetch]),
  );

  const handlePause = useCallback(
    (id: string) => {
      pauseReminder(id).catch(() => {
        Alert.alert("Error", "Failed to pause reminder.");
      });
    },
    [pauseReminder],
  );

  const handleResume = useCallback(
    (id: string) => {
      resumeReminder(id).catch(() => {
        Alert.alert("Error", "Failed to resume reminder.");
      });
    },
    [resumeReminder],
  );

  const handleDelete = useCallback(
    (id: string) => {
      deleteReminder(id).catch(() => {
        Alert.alert("Error", "Failed to delete reminder.");
      });
    },
    [deleteReminder],
  );

  return (
    <View style={{ flex: 1, backgroundColor: "#0a0a0a" }}>
      {/* Header */}
      <View
        style={{
          paddingTop: insets.top + spacing.sm,
          paddingHorizontal: spacing.md,
          paddingBottom: spacing.md,
          borderBottomWidth: 1,
          borderBottomColor: "rgba(255,255,255,0.06)",
          flexDirection: "row",
          alignItems: "center",
        }}
      >
        <Pressable
          onPress={() => router.back()}
          hitSlop={10}
          style={{
            width: 36,
            height: 36,
            borderRadius: 18,
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: "rgba(255,255,255,0.05)",
          }}
        >
          <ArrowLeft01Icon size={18} color="#e8ebef" />
        </Pressable>

        <Text
          style={{
            marginLeft: spacing.md,
            fontSize: fontSize.lg,
            fontWeight: "700",
            color: "#e8ebef",
            flex: 1,
          }}
        >
          Reminders
        </Text>

        <Pressable
          onPress={() => setShowCreate(true)}
          style={{
            width: 36,
            height: 36,
            borderRadius: 18,
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: "rgba(22,193,255,0.15)",
          }}
        >
          <Add01Icon size={18} color="#16c1ff" />
        </Pressable>
      </View>

      {/* Loading state */}
      {isLoading && (
        <View
          style={{ flex: 1, alignItems: "center", justifyContent: "center" }}
        >
          <ActivityIndicator size="large" color="#16c1ff" />
        </View>
      )}

      {/* Error state */}
      {!isLoading && error && (
        <View
          style={{
            flex: 1,
            alignItems: "center",
            justifyContent: "center",
            paddingHorizontal: spacing.xl,
            gap: spacing.md,
          }}
        >
          <Text
            style={{
              fontSize: fontSize.sm,
              color: "#ef4444",
              textAlign: "center",
            }}
          >
            {error}
          </Text>
          <Pressable
            onPress={() => {
              void refetch();
            }}
            style={{
              borderRadius: 8,
              paddingHorizontal: spacing.md,
              paddingVertical: spacing.sm,
              backgroundColor: "rgba(22,193,255,0.1)",
            }}
          >
            <Text style={{ fontSize: fontSize.sm, color: "#16c1ff" }}>
              Try again
            </Text>
          </Pressable>
        </View>
      )}

      {/* Content */}
      {!isLoading && !error && (
        <ScrollView
          contentContainerStyle={{
            paddingHorizontal: spacing.md,
            paddingVertical: spacing.md,
            gap: spacing.md,
            flexGrow: 1,
          }}
          showsVerticalScrollIndicator={false}
          refreshControl={
            <RefreshControl
              refreshing={isRefreshing}
              onRefresh={() => {
                void refetch();
              }}
              tintColor="#16c1ff"
            />
          }
        >
          {reminders.length === 0 ? (
            <EmptyState />
          ) : (
            <>
              {/* Active section */}
              {activeReminders.length > 0 && (
                <View style={{ gap: spacing.sm }}>
                  <View
                    style={{
                      flexDirection: "row",
                      alignItems: "center",
                      gap: spacing.xs,
                    }}
                  >
                    <View
                      style={{
                        width: 8,
                        height: 8,
                        borderRadius: 4,
                        backgroundColor: "#22c55e",
                      }}
                    />
                    <Text
                      style={{
                        fontSize: fontSize.sm,
                        fontWeight: "600",
                        color: "#a1a1aa",
                        textTransform: "uppercase",
                        letterSpacing: 0.5,
                      }}
                    >
                      Active ({activeReminders.length})
                    </Text>
                  </View>
                  {activeReminders.map((reminder) => (
                    <ReminderCard
                      key={reminder.id}
                      reminder={reminder}
                      onPause={handlePause}
                      onResume={handleResume}
                      onDelete={handleDelete}
                    />
                  ))}
                </View>
              )}

              {/* Paused section */}
              {pausedReminders.length > 0 && (
                <View
                  style={{
                    gap: spacing.sm,
                    marginTop: activeReminders.length > 0 ? spacing.md : 0,
                  }}
                >
                  <View
                    style={{
                      flexDirection: "row",
                      alignItems: "center",
                      gap: spacing.xs,
                    }}
                  >
                    <View
                      style={{
                        width: 8,
                        height: 8,
                        borderRadius: 4,
                        backgroundColor: "#52525b",
                      }}
                    />
                    <Text
                      style={{
                        fontSize: fontSize.sm,
                        fontWeight: "600",
                        color: "#52525b",
                        textTransform: "uppercase",
                        letterSpacing: 0.5,
                      }}
                    >
                      Paused ({pausedReminders.length})
                    </Text>
                  </View>
                  {pausedReminders.map((reminder) => (
                    <ReminderCard
                      key={reminder.id}
                      reminder={reminder}
                      onPause={handlePause}
                      onResume={handleResume}
                      onDelete={handleDelete}
                    />
                  ))}
                </View>
              )}
            </>
          )}
        </ScrollView>
      )}

      {/* FAB */}
      {!isLoading && !error && (
        <Pressable
          onPress={() => setShowCreate(true)}
          style={{
            position: "absolute",
            bottom: insets.bottom + spacing.lg,
            right: spacing.md,
            width: 56,
            height: 56,
            borderRadius: 28,
            backgroundColor: "#16c1ff",
            alignItems: "center",
            justifyContent: "center",
            shadowColor: "#16c1ff",
            shadowOffset: { width: 0, height: 4 },
            shadowOpacity: 0.4,
            shadowRadius: 12,
            elevation: 8,
          }}
        >
          <Add01Icon size={24} color="#000" />
        </Pressable>
      )}

      <CreateReminderSheet
        visible={showCreate}
        onClose={() => setShowCreate(false)}
        onCreated={createReminder}
        isSubmitting={isCreating}
      />
    </View>
  );
}
