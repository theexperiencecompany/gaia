import { BottomSheetScrollView } from "@gorhom/bottom-sheet";
import { forwardRef, useImperativeHandle, useState } from "react";
import { Pressable, View } from "react-native";
import { AppIcon, Folder02Icon, Tick02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";
import type { Project } from "../types/todo-types";

export interface ProjectPickerSheetRef {
  open: () => void;
  close: () => void;
}

interface ProjectPickerSheetProps {
  projects: Project[];
  selectedProjectId: string | undefined;
  onSelect: (projectId: string | undefined) => void;
}

export const ProjectPickerSheet = forwardRef<
  ProjectPickerSheetRef,
  ProjectPickerSheetProps
>(({ projects, selectedProjectId, onSelect }, ref) => {
  const [isOpen, setIsOpen] = useState(false);
  const { spacing, fontSize } = useResponsive();

  useImperativeHandle(ref, () => ({
    open: () => setIsOpen(true),
    close: () => setIsOpen(false),
  }));

  const handleSelect = (projectId: string | undefined) => {
    onSelect(projectId);
    setIsOpen(false);
  };

  return (
    <BottomSheet isOpen={isOpen} onOpenChange={setIsOpen}>
      <BottomSheet.Portal>
        <BottomSheet.Overlay />
        <BottomSheet.Content
          snapPoints={["40%", "70%"]}
          enableDynamicSizing={false}
          enablePanDownToClose
          backgroundStyle={{ backgroundColor: "#1c1c1e" }}
          handleIndicatorStyle={{ backgroundColor: "#3f3f46", width: 40 }}
        >
          <BottomSheetScrollView
            contentContainerStyle={{
              paddingHorizontal: spacing.md,
              paddingBottom: 40,
            }}
          >
            {/* Header */}
            <View
              style={{
                paddingVertical: spacing.md,
                borderBottomWidth: 1,
                borderBottomColor: "rgba(255,255,255,0.07)",
                marginBottom: spacing.xs,
              }}
            >
              <Text
                style={{
                  fontSize: fontSize.lg,
                  fontWeight: "600",
                  color: "#f4f4f5",
                  textAlign: "center",
                }}
              >
                Select Project
              </Text>
            </View>

            {/* No project option */}
            <Pressable
              onPress={() => handleSelect(undefined)}
              style={({ pressed }) => ({
                flexDirection: "row",
                alignItems: "center",
                gap: spacing.md,
                paddingVertical: spacing.md,
                paddingHorizontal: spacing.sm,
                borderRadius: 12,
                backgroundColor: pressed
                  ? "rgba(255,255,255,0.05)"
                  : "transparent",
              })}
            >
              <View
                style={{
                  width: 36,
                  height: 36,
                  borderRadius: 10,
                  backgroundColor: "rgba(255,255,255,0.05)",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <AppIcon icon={Folder02Icon} size={16} color="#52525b" />
              </View>
              <Text
                style={{
                  flex: 1,
                  fontSize: fontSize.base,
                  color:
                    selectedProjectId === undefined ? "#16c1ff" : "#a1a1aa",
                  fontWeight: selectedProjectId === undefined ? "600" : "400",
                }}
              >
                No Project
              </Text>
              {selectedProjectId === undefined && (
                <AppIcon icon={Tick02Icon} size={16} color="#16c1ff" />
              )}
            </Pressable>

            {/* Project list */}
            {projects.map((project) => {
              const color = project.color ?? "#71717a";
              const isSelected = selectedProjectId === project.id;
              return (
                <Pressable
                  key={project.id}
                  onPress={() => handleSelect(project.id)}
                  style={({ pressed }) => ({
                    flexDirection: "row",
                    alignItems: "center",
                    gap: spacing.md,
                    paddingVertical: spacing.md,
                    paddingHorizontal: spacing.sm,
                    borderRadius: 12,
                    backgroundColor: pressed
                      ? "rgba(255,255,255,0.05)"
                      : "transparent",
                  })}
                >
                  <View
                    style={{
                      width: 36,
                      height: 36,
                      borderRadius: 10,
                      backgroundColor: `${color}20`,
                      alignItems: "center",
                      justifyContent: "center",
                      borderWidth: 1,
                      borderColor: `${color}35`,
                    }}
                  >
                    <AppIcon icon={Folder02Icon} size={16} color={color} />
                  </View>
                  <Text
                    style={{
                      flex: 1,
                      fontSize: fontSize.base,
                      color: isSelected ? color : "#e4e4e7",
                      fontWeight: isSelected ? "600" : "400",
                    }}
                  >
                    {project.name}
                  </Text>
                  {isSelected && (
                    <AppIcon icon={Tick02Icon} size={16} color={color} />
                  )}
                </Pressable>
              );
            })}
          </BottomSheetScrollView>
        </BottomSheet.Content>
      </BottomSheet.Portal>
    </BottomSheet>
  );
});
