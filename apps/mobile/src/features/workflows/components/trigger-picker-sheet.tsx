import {
  BottomSheetFlatList,
  BottomSheetTextInput,
} from "@gorhom/bottom-sheet";
import { forwardRef, useImperativeHandle, useState } from "react";
import { Image, Pressable, View } from "react-native";
import { AppIcon, Clock01Icon, PlayIcon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";

export interface TriggerOption {
  id: string;
  label: string;
  description: string;
  category: "basic" | "integration";
  iconUrl?: string;
  requiresIntegration?: string;
}

const TRIGGER_OPTIONS: TriggerOption[] = [
  {
    id: "manual",
    label: "Manual",
    description: "Run on demand from chat or app",
    category: "basic",
  },
  {
    id: "scheduled",
    label: "Scheduled",
    description: "Run on a time-based schedule",
    category: "basic",
  },
  {
    id: "gmail_new_email",
    label: "New Gmail Email",
    description: "Triggers when a new email arrives",
    category: "integration",
    requiresIntegration: "gmail",
    iconUrl:
      "https://upload.wikimedia.org/wikipedia/commons/thumb/7/7e/Gmail_icon_%282020%29.svg/120px-Gmail_icon_%282020%29.svg.png",
  },
  {
    id: "calendar_new_event",
    label: "New Calendar Event",
    description: "Triggers on a new calendar event",
    category: "integration",
    requiresIntegration: "google_calendar",
    iconUrl:
      "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a5/Google_Calendar_icon_%282020%29.svg/120px-Google_Calendar_icon_%282020%29.svg.png",
  },
  {
    id: "github_push",
    label: "GitHub Push",
    description: "Triggers on a new git push",
    category: "integration",
    requiresIntegration: "github",
    iconUrl:
      "https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png",
  },
  {
    id: "slack_message",
    label: "Slack Message",
    description: "Triggers on a new Slack message",
    category: "integration",
    requiresIntegration: "slack",
    iconUrl:
      "https://a.slack-edge.com/80588/marketing/img/meta/slack_hash_128.png",
  },
  {
    id: "notion_page",
    label: "Notion Page Updated",
    description: "Triggers when a Notion page changes",
    category: "integration",
    requiresIntegration: "notion",
    iconUrl:
      "https://upload.wikimedia.org/wikipedia/commons/4/45/Notion_app_logo.png",
  },
  {
    id: "linear_issue",
    label: "Linear Issue",
    description: "Triggers on a new Linear issue",
    category: "integration",
    requiresIntegration: "linear",
  },
  {
    id: "todoist_task",
    label: "Todoist Task",
    description: "Triggers when a Todoist task is created",
    category: "integration",
    requiresIntegration: "todoist",
  },
  {
    id: "google_sheets_row",
    label: "Google Sheets Row",
    description: "Triggers when a new row is added",
    category: "integration",
    requiresIntegration: "google_sheets",
    iconUrl:
      "https://upload.wikimedia.org/wikipedia/commons/thumb/3/30/Google_Sheets_logo_%282014-2020%29.svg/120px-Google_Sheets_logo_%282014-2020%29.svg.png",
  },
  {
    id: "asana_task",
    label: "Asana Task",
    description: "Triggers on a new Asana task",
    category: "integration",
    requiresIntegration: "asana",
  },
];

export { TRIGGER_OPTIONS };

export interface TriggerPickerSheetRef {
  open: () => void;
  close: () => void;
}

interface TriggerPickerSheetProps {
  onSelect: (trigger: TriggerOption) => void;
}

export const TriggerPickerSheet = forwardRef<
  TriggerPickerSheetRef,
  TriggerPickerSheetProps
>(({ onSelect }, ref) => {
  const [isOpen, setIsOpen] = useState(false);
  const [search, setSearch] = useState("");
  const { spacing, fontSize } = useResponsive();

  useImperativeHandle(ref, () => ({
    open: () => {
      setSearch("");
      setIsOpen(true);
    },
    close: () => setIsOpen(false),
  }));

  const filtered = TRIGGER_OPTIONS.filter(
    (t) =>
      t.label.toLowerCase().includes(search.toLowerCase()) ||
      t.description.toLowerCase().includes(search.toLowerCase()),
  );

  const renderItem = ({ item }: { item: TriggerOption }) => (
    <Pressable
      onPress={() => {
        onSelect(item);
        setIsOpen(false);
      }}
      style={({ pressed }) => ({
        flexDirection: "row",
        alignItems: "center",
        gap: spacing.md,
        paddingHorizontal: spacing.md,
        paddingVertical: spacing.sm + 4,
        backgroundColor: pressed ? "rgba(255,255,255,0.04)" : "transparent",
      })}
    >
      <View
        style={{
          width: 36,
          height: 36,
          borderRadius: 10,
          backgroundColor: "#2c2c2e",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        {item.iconUrl ? (
          <Image
            source={{ uri: item.iconUrl }}
            style={{ width: 22, height: 22 }}
            resizeMode="contain"
          />
        ) : item.id === "scheduled" ? (
          <AppIcon icon={Clock01Icon} size={18} color="#a1a1aa" />
        ) : (
          <AppIcon icon={PlayIcon} size={18} color="#a1a1aa" />
        )}
      </View>
      <View style={{ flex: 1 }}>
        <Text
          style={{ fontSize: fontSize.sm, fontWeight: "500", color: "#fff" }}
        >
          {item.label}
        </Text>
        <Text
          style={{ fontSize: fontSize.xs, color: "#71717a" }}
          numberOfLines={1}
        >
          {item.description}
        </Text>
      </View>
      {item.requiresIntegration ? (
        <View
          style={{
            paddingHorizontal: spacing.sm,
            paddingVertical: 2,
            backgroundColor: "#2c2c2e",
            borderRadius: 6,
          }}
        >
          <Text style={{ fontSize: fontSize.xs - 1, color: "#71717a" }}>
            Integration
          </Text>
        </View>
      ) : null}
    </Pressable>
  );

  return (
    <BottomSheet isOpen={isOpen} onOpenChange={setIsOpen}>
      <BottomSheet.Portal>
        <BottomSheet.Overlay />
        <BottomSheet.Content
          snapPoints={["60%", "90%"]}
          enablePanDownToClose
          backgroundStyle={{ backgroundColor: "#1c1c1e" }}
          handleIndicatorStyle={{ backgroundColor: "#3f3f46" }}
          keyboardBehavior="interactive"
        >
          <View
            style={{
              paddingHorizontal: spacing.md,
              paddingBottom: spacing.sm,
            }}
          >
            <BottomSheetTextInput
              value={search}
              onChangeText={setSearch}
              placeholder="Search triggers..."
              placeholderTextColor="#52525b"
              style={{
                backgroundColor: "#2c2c2e",
                borderRadius: 10,
                paddingHorizontal: spacing.md,
                paddingVertical: spacing.sm,
                color: "#fff",
                fontSize: fontSize.sm,
              }}
            />
          </View>
          <BottomSheetFlatList
            data={filtered}
            keyExtractor={(i: TriggerOption) => i.id}
            renderItem={renderItem}
            contentContainerStyle={{ paddingBottom: spacing.xl }}
          />
        </BottomSheet.Content>
      </BottomSheet.Portal>
    </BottomSheet>
  );
});

TriggerPickerSheet.displayName = "TriggerPickerSheet";
