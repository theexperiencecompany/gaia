import { Pressable, ScrollView, View } from "react-native";
import {
  AppIcon,
  Calendar03Icon,
  Cancel01Icon,
  Flag02Icon,
  Folder02Icon,
  Tag01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { Priority } from "../../types/todo-types";

export interface InferenceChip {
  /** Stable key — usually `kind:value`. */
  key: string;
  kind: "date" | "priority" | "project" | "label";
  label: string;
  color: string;
}

interface TodoCreateInferencesProps {
  chips: InferenceChip[];
  onRemove: (chip: InferenceChip) => void;
}

const PRIORITY_ICON = Flag02Icon;
const KIND_ICON: Record<InferenceChip["kind"], typeof PRIORITY_ICON> = {
  date: Calendar03Icon,
  priority: Flag02Icon,
  project: Folder02Icon,
  label: Tag01Icon,
};

export function TodoCreateInferences({
  chips,
  onRemove,
}: TodoCreateInferencesProps) {
  if (chips.length === 0) return null;
  return (
    <View className="px-4" style={{ paddingTop: 8, paddingBottom: 4 }}>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={{ gap: 6, paddingRight: 12 }}
      >
        {chips.map((chip) => (
          <Pressable
            key={chip.key}
            onPress={() => onRemove(chip)}
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: 6,
              paddingHorizontal: 10,
              paddingVertical: 6,
              borderRadius: 999,
              backgroundColor: "rgba(63,63,70,0.5)",
            }}
          >
            <AppIcon icon={KIND_ICON[chip.kind]} size={11} color={chip.color} />
            <Text
              style={{
                fontSize: 12,
                fontWeight: "500",
                color: chip.color,
              }}
            >
              {chip.label}
            </Text>
            <AppIcon icon={Cancel01Icon} size={10} color="#a1a1aa" />
          </Pressable>
        ))}
      </ScrollView>
    </View>
  );
}

export function priorityChipColor(priority: Priority): string {
  switch (priority) {
    case Priority.HIGH:
      return "#f87171";
    case Priority.MEDIUM:
      return "#facc15";
    case Priority.LOW:
      return "#60a5fa";
    default:
      return "#a1a1aa";
  }
}
