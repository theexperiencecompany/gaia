import { Button, Card, Chip } from "heroui-native";
import { useState } from "react";
import { ScrollView, View } from "react-native";
import {
  AppIcon,
  Calendar03Icon,
  CheckmarkCircle01Icon,
  Edit02Icon,
  PencilEdit01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";

// -- Types --------------------------------------------------------------------

export interface CalendarEditOption {
  event_id?: string;
  title?: string;
  changes?: Record<string, unknown>;
  original_title?: string;
  start?: { dateTime?: string; date?: string };
  background_color?: string;
  calendar_name?: string;
}

type EventStatus = "idle" | "loading" | "completed";

interface CalendarEditCardProps {
  data: CalendarEditOption[];
  onEdit?: (event: CalendarEditOption) => Promise<void>;
  onEditAll?: (events: CalendarEditOption[]) => Promise<void>;
}

// -- Helpers ------------------------------------------------------------------

const CHANGE_LABELS: Record<string, string> = {
  summary: "title",
  title: "title",
  start: "start time",
  end: "end time",
  location: "location",
  description: "description",
  attendees: "attendees",
  is_all_day: "all-day",
  timezone: "timezone",
};

function describeChanges(changes?: Record<string, unknown>): string {
  if (!changes) return "";
  const keys = Object.keys(changes);
  if (keys.length === 0) return "";
  return keys.map((k) => CHANGE_LABELS[k] ?? k).join(", ");
}

function formatEventTime(dt?: { dateTime?: string; date?: string }): string {
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
  events: CalendarEditOption[],
): Record<string, CalendarEditOption[]> {
  const groups: Record<string, CalendarEditOption[]> = {};
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
  event: CalendarEditOption;
  status: EventStatus;
  onEdit: () => void;
}

function EventRow({ event, status, onEdit }: EventRowProps) {
  const timeStr = formatEventTime(event.start);
  const changesStr = describeChanges(event.changes);
  const eventColor = event.background_color ?? "#00bbff";
  const isCompleted = status === "completed";
  const isLoading = status === "loading";
  const hasChanges = event.changes && Object.keys(event.changes).length > 0;

  return (
    <View className="py-3 px-4" style={{ opacity: isCompleted ? 0.55 : 1 }}>
      {/* Original → Updated indicator when there are explicit changes */}
      {hasChanges && !isCompleted && event.original_title ? (
        <View
          className="rounded-xl px-3 py-2 mb-2 border border-dashed"
          style={{
            backgroundColor: `${eventColor}10`,
            borderColor: `${eventColor}40`,
          }}
        >
          <Text className="text-xs text-muted mb-0.5">Current</Text>
          <Text
            className="text-sm text-foreground/60 line-through"
            numberOfLines={1}
          >
            {event.original_title}
          </Text>
        </View>
      ) : null}

      {/* Event card */}
      <View
        className="rounded-xl px-3 py-2.5"
        style={{ backgroundColor: `${eventColor}15` }}
      >
        <View className="flex-row items-start gap-3">
          {/* Icon */}
          <View
            className="w-8 h-8 rounded-lg items-center justify-center flex-shrink-0 mt-0.5"
            style={{ backgroundColor: `${eventColor}25` }}
          >
            <AppIcon
              icon={isCompleted ? CheckmarkCircle01Icon : Calendar03Icon}
              size={16}
              color={isCompleted ? "#22c55e" : eventColor}
            />
          </View>

          {/* Info */}
          <View className="flex-1 min-w-0">
            <Text
              className="text-sm font-medium text-foreground mb-0.5"
              numberOfLines={1}
            >
              {event.title ?? "Untitled Event"}
            </Text>
            {timeStr ? (
              <Text className="text-muted text-xs mb-1">{timeStr}</Text>
            ) : null}
            {changesStr ? (
              <Text className="text-xs text-primary/80">
                Updating: {changesStr}
              </Text>
            ) : null}
            {event.calendar_name ? (
              <Chip
                size="sm"
                variant="soft"
                className="mt-1.5 self-start"
                animation="disable-all"
              >
                <Chip.Label>{event.calendar_name}</Chip.Label>
              </Chip>
            ) : null}
          </View>

          {/* Action button */}
          <Button
            size="sm"
            variant={isCompleted ? "secondary" : "primary"}
            isDisabled={isCompleted || isLoading}
            onPress={onEdit}
            className="flex-shrink-0 rounded-xl"
          >
            {isCompleted ? (
              <AppIcon icon={CheckmarkCircle01Icon} size={14} color="#22c55e" />
            ) : (
              <AppIcon icon={Edit02Icon} size={14} color="#fff" />
            )}
            <Button.Label>{isCompleted ? "Updated" : "Confirm"}</Button.Label>
          </Button>
        </View>
      </View>
    </View>
  );
}

// -- Calendar edit card -------------------------------------------------------

export function CalendarEditCard({
  data,
  onEdit,
  onEditAll,
}: CalendarEditCardProps) {
  const [statuses, setStatuses] = useState<Record<string, EventStatus>>({});
  const [isUpdatingAll, setIsUpdatingAll] = useState(false);

  const getKey = (event: CalendarEditOption, index: number): string =>
    event.event_id ?? `edit-${index}`;

  const handleEdit = async (
    event: CalendarEditOption,
    key: string,
  ): Promise<void> => {
    if (!onEdit) return;
    setStatuses((prev) => ({ ...prev, [key]: "loading" }));
    try {
      await onEdit(event);
      setStatuses((prev) => ({ ...prev, [key]: "completed" }));
    } catch {
      setStatuses((prev) => ({ ...prev, [key]: "idle" }));
    }
  };

  const handleEditAll = async (): Promise<void> => {
    if (!onEditAll) return;
    setIsUpdatingAll(true);
    const pending = data.filter((ev, i) => {
      const key = getKey(ev, i);
      return statuses[key] !== "completed";
    });
    try {
      await onEditAll(pending);
      const next: Record<string, EventStatus> = {};
      data.forEach((ev, i) => {
        next[getKey(ev, i)] = "completed";
      });
      setStatuses(next);
    } catch {
      // no-op
    } finally {
      setIsUpdatingAll(false);
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
          <View className="w-7 h-7 rounded-xl bg-primary/15 items-center justify-center">
            <AppIcon icon={PencilEdit01Icon} size={14} color="#00bbff" />
          </View>
          <View className="flex-1 min-w-0">
            <Card.Title>
              Event{data.length !== 1 ? "s" : ""} to Update
            </Card.Title>
          </View>
          <Chip size="sm" variant="soft" color="accent" animation="disable-all">
            <Chip.Label>
              {data.length} edit{data.length !== 1 ? "s" : ""}
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
            <Text className="text-muted text-sm">No events to update</Text>
          </View>
        ) : (
          <ScrollView
            style={{ maxHeight: 400 }}
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
                        onEdit={() => void handleEdit(event, key)}
                      />
                    </View>
                  );
                })}
              </View>
            ))}
          </ScrollView>
        )}

        {/* Bulk update footer */}
        {data.length > 1 && onEditAll ? (
          <>
            <View
              style={{ height: 1, backgroundColor: "rgba(255,255,255,0.07)" }}
            />
            <View className="px-4 py-3">
              <Button
                variant={allCompleted ? "secondary" : "primary"}
                isDisabled={allCompleted || isUpdatingAll}
                onPress={() => void handleEditAll()}
                className="w-full rounded-xl"
              >
                {allCompleted ? (
                  <AppIcon
                    icon={CheckmarkCircle01Icon}
                    size={16}
                    color="#22c55e"
                  />
                ) : (
                  <AppIcon icon={Edit02Icon} size={16} color="#fff" />
                )}
                <Button.Label>
                  {allCompleted
                    ? "All Updated"
                    : someCompleted
                      ? "Update Remaining"
                      : "Update All Events"}
                </Button.Label>
              </Button>
            </View>
          </>
        ) : null}
      </Card.Body>
    </Card>
  );
}
