import { Button, Card, Chip } from "heroui-native";
import { useState } from "react";
import { ScrollView, View } from "react-native";
import {
  AppIcon,
  Calendar03Icon,
  Cancel01Icon,
  CheckmarkCircle01Icon,
  Delete02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";

// -- Types --------------------------------------------------------------------

export interface CalendarDeleteOption {
  event_id?: string;
  title?: string;
  start?: { dateTime?: string; date?: string };
  end?: { dateTime?: string; date?: string };
  background_color?: string;
  calendar_name?: string;
  description?: string;
}

type EventStatus = "idle" | "loading" | "completed";

interface CalendarDeleteCardProps {
  data: CalendarDeleteOption[];
  onDelete?: (event: CalendarDeleteOption) => Promise<void>;
  onDeleteAll?: (events: CalendarDeleteOption[]) => Promise<void>;
}

// -- Helpers ------------------------------------------------------------------

function formatDeletedTime(dt?: { dateTime?: string; date?: string }): string {
  if (!dt) return "";
  const raw = dt.dateTime || dt.date;
  if (!raw) return "";
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return raw;
  if (dt.date && !dt.dateTime) {
    return date.toLocaleDateString([], {
      weekday: "short",
      month: "short",
      day: "numeric",
    });
  }
  return date.toLocaleString([], {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function groupByDate(
  events: CalendarDeleteOption[],
): Record<string, CalendarDeleteOption[]> {
  const groups: Record<string, CalendarDeleteOption[]> = {};
  for (const event of events) {
    const raw =
      event.start?.dateTime || event.start?.date || new Date().toISOString();
    const dateKey = new Date(raw).toISOString().slice(0, 10);
    if (!groups[dateKey]) groups[dateKey] = [];
    groups[dateKey].push(event);
  }
  return groups;
}

function formatDateHeader(dateKey: string): string {
  const date = new Date(`${dateKey}T12:00:00`);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = new Date(date);
  target.setHours(0, 0, 0, 0);
  const diff = target.getTime() - today.getTime();
  const dayMs = 86400000;
  const base = date.toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
  });
  if (diff === 0) return `${base} (Today)`;
  if (diff === dayMs) return `${base} (Tomorrow)`;
  if (diff === -dayMs) return `${base} (Yesterday)`;
  return base;
}

// -- Event row ----------------------------------------------------------------

interface EventRowProps {
  event: CalendarDeleteOption;
  status: EventStatus;
  onDelete: () => void;
}

function EventRow({ event, status, onDelete }: EventRowProps) {
  const timeStr = formatDeletedTime(event.start);
  const eventColor = event.background_color ?? "#ef4444";
  const isCompleted = status === "completed";
  const isLoading = status === "loading";

  return (
    <View
      className="flex-row items-center gap-3 py-3 px-4"
      style={{ opacity: isCompleted ? 0.5 : 1 }}
    >
      {/* Color bar + icon */}
      <View className="items-center gap-1.5">
        <View
          className="w-8 h-8 rounded-xl items-center justify-center"
          style={{ backgroundColor: `${eventColor}20` }}
        >
          <AppIcon
            icon={isCompleted ? CheckmarkCircle01Icon : Calendar03Icon}
            size={16}
            color={isCompleted ? "#22c55e" : eventColor}
          />
        </View>
      </View>

      {/* Event info */}
      <View className="flex-1 min-w-0">
        <Text
          className={`text-sm font-medium mb-0.5 ${isCompleted ? "line-through text-foreground/50" : "text-foreground"}`}
          numberOfLines={1}
        >
          {event.title ?? "Untitled Event"}
        </Text>
        {timeStr ? <Text className="text-muted text-xs">{timeStr}</Text> : null}
        {event.calendar_name ? (
          <Chip
            size="sm"
            variant="soft"
            className="mt-1 self-start"
            animation="disable-all"
          >
            <Chip.Label>{event.calendar_name}</Chip.Label>
          </Chip>
        ) : null}
      </View>

      {/* Action button */}
      <Button
        size="sm"
        variant={isCompleted ? "secondary" : "danger"}
        isDisabled={isCompleted || isLoading}
        onPress={onDelete}
        className="flex-shrink-0 rounded-xl"
      >
        {isCompleted ? (
          <AppIcon icon={CheckmarkCircle01Icon} size={14} color="#22c55e" />
        ) : (
          <AppIcon icon={Delete02Icon} size={14} color="#fff" />
        )}
        <Button.Label>{isCompleted ? "Deleted" : "Delete"}</Button.Label>
      </Button>
    </View>
  );
}

// -- Calendar delete card -----------------------------------------------------

export function CalendarDeleteCard({
  data,
  onDelete,
  onDeleteAll,
}: CalendarDeleteCardProps) {
  const [statuses, setStatuses] = useState<Record<string, EventStatus>>({});
  const [isDeletingAll, setIsDeletingAll] = useState(false);

  const getKey = (event: CalendarDeleteOption, index: number): string =>
    event.event_id ?? `delete-${index}`;

  const handleDelete = async (
    event: CalendarDeleteOption,
    key: string,
  ): Promise<void> => {
    if (!onDelete) return;
    setStatuses((prev) => ({ ...prev, [key]: "loading" }));
    try {
      await onDelete(event);
      setStatuses((prev) => ({ ...prev, [key]: "completed" }));
    } catch {
      setStatuses((prev) => ({ ...prev, [key]: "idle" }));
    }
  };

  const handleDeleteAll = async (): Promise<void> => {
    if (!onDeleteAll) return;
    setIsDeletingAll(true);
    const pending = data.filter((ev, i) => {
      const key = getKey(ev, i);
      return statuses[key] !== "completed";
    });
    try {
      await onDeleteAll(pending);
      const next: Record<string, EventStatus> = {};
      data.forEach((ev, i) => {
        next[getKey(ev, i)] = "completed";
      });
      setStatuses(next);
    } catch {
      // no-op: individual errors are handled by the caller
    } finally {
      setIsDeletingAll(false);
    }
  };

  const allCompleted = data.every(
    (ev, i) => statuses[getKey(ev, i)] === "completed",
  );
  const someCompleted = data.some(
    (ev, i) => statuses[getKey(ev, i)] === "completed",
  );

  const eventsByDate = groupByDate(data);

  return (
    <Card
      variant="secondary"
      className="mx-4 my-2 rounded-2xl bg-[#171920] overflow-hidden"
      animation="disable-all"
    >
      {/* Header */}
      <Card.Header className="px-4 py-3 pb-0">
        <View className="flex-row items-center gap-2">
          <View className="w-7 h-7 rounded-xl bg-danger/15 items-center justify-center">
            <AppIcon icon={Cancel01Icon} size={14} color="#ef4444" />
          </View>
          <View className="flex-1 min-w-0">
            <Card.Title>
              Event{data.length !== 1 ? "s" : ""} to Delete
            </Card.Title>
          </View>
          <Chip size="sm" variant="soft" color="danger" animation="disable-all">
            <Chip.Label>
              {data.length} event{data.length !== 1 ? "s" : ""}
            </Chip.Label>
          </Chip>
        </View>
      </Card.Header>

      <Card.Body className="p-0">
        <View
          style={{
            height: 1,
            backgroundColor: "rgba(255,255,255,0.07)",
            marginTop: 12,
          }}
        />

        {data.length === 0 ? (
          <View className="px-4 py-3">
            <Text className="text-muted text-sm">No events to delete</Text>
          </View>
        ) : (
          <ScrollView
            style={{ maxHeight: 360 }}
            nestedScrollEnabled
            showsVerticalScrollIndicator={false}
          >
            {Object.entries(eventsByDate).map(([dateKey, events]) => (
              <View key={dateKey}>
                {/* Date header */}
                <View className="flex-row items-center gap-3 px-4 py-2">
                  <View className="flex-1 h-px bg-white/8" />
                  <Text className="text-muted text-xs">
                    {formatDateHeader(dateKey)}
                  </Text>
                  <View className="flex-1 h-px bg-white/8" />
                </View>

                {events.map((event, localIdx) => {
                  const globalIdx = data.indexOf(event);
                  const key = getKey(event, globalIdx);
                  const status = statuses[key] ?? "idle";
                  return (
                    <View key={key}>
                      {localIdx > 0 && (
                        <View
                          style={{
                            height: 1,
                            backgroundColor: "rgba(255,255,255,0.07)",
                            marginHorizontal: 16,
                          }}
                        />
                      )}
                      <EventRow
                        event={event}
                        status={status}
                        onDelete={() => void handleDelete(event, key)}
                      />
                    </View>
                  );
                })}
              </View>
            ))}
          </ScrollView>
        )}

        {/* Bulk delete footer */}
        {data.length > 1 && onDeleteAll ? (
          <>
            <View
              style={{ height: 1, backgroundColor: "rgba(255,255,255,0.07)" }}
            />
            <View className="px-4 py-3">
              <Button
                variant={allCompleted ? "secondary" : "danger"}
                isDisabled={allCompleted || isDeletingAll}
                onPress={() => void handleDeleteAll()}
                className="w-full rounded-xl"
              >
                {allCompleted ? (
                  <AppIcon
                    icon={CheckmarkCircle01Icon}
                    size={16}
                    color="#22c55e"
                  />
                ) : (
                  <AppIcon icon={Delete02Icon} size={16} color="#fff" />
                )}
                <Button.Label>
                  {allCompleted
                    ? "All Deleted"
                    : someCompleted
                      ? "Delete Remaining"
                      : "Delete All Events"}
                </Button.Label>
              </Button>
            </View>
          </>
        ) : null}
      </Card.Body>
    </Card>
  );
}
