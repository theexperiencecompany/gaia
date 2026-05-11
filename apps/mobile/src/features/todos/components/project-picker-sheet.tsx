import { BottomSheetScrollView } from "@gorhom/bottom-sheet";
import { forwardRef, useImperativeHandle, useState } from "react";
import { Pressable, View } from "react-native";
import { AppIcon, Folder02Icon, Tick02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
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
          backgroundStyle={{ backgroundColor: "#18181b" }}
          handleIndicatorStyle={{ backgroundColor: "#3f3f46", width: 40 }}
        >
          <BottomSheetScrollView
            contentContainerStyle={{
              paddingHorizontal: 16,
              paddingBottom: 40,
            }}
          >
            <View
              style={{
                paddingVertical: 14,
                marginBottom: 6,
              }}
            >
              <Text
                style={{
                  fontSize: 17,
                  fontWeight: "600",
                  color: "#f4f4f5",
                  textAlign: "center",
                }}
              >
                Select project
              </Text>
            </View>

            <View
              className="bg-zinc-800/30 rounded-2xl"
              style={{ paddingHorizontal: 6, paddingVertical: 4 }}
            >
              <Pressable
                onPress={() => handleSelect(undefined)}
                style={({ pressed }) => ({
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 12,
                  paddingVertical: 12,
                  paddingHorizontal: 8,
                  borderRadius: 12,
                  backgroundColor: pressed
                    ? "rgba(63,63,70,0.5)"
                    : "transparent",
                })}
              >
                <View
                  className="bg-zinc-800/60"
                  style={{
                    width: 32,
                    height: 32,
                    borderRadius: 10,
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  <AppIcon icon={Folder02Icon} size={14} color="#71717a" />
                </View>
                <Text
                  style={{
                    flex: 1,
                    fontSize: 15,
                    color:
                      selectedProjectId === undefined ? "#00bbff" : "#d4d4d8",
                    fontWeight: selectedProjectId === undefined ? "600" : "400",
                  }}
                >
                  No project
                </Text>
                {selectedProjectId === undefined ? (
                  <AppIcon icon={Tick02Icon} size={16} color="#00bbff" />
                ) : null}
              </Pressable>

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
                      gap: 12,
                      paddingVertical: 12,
                      paddingHorizontal: 8,
                      borderRadius: 12,
                      backgroundColor: pressed
                        ? "rgba(63,63,70,0.5)"
                        : "transparent",
                    })}
                  >
                    <View
                      className="bg-zinc-800/60"
                      style={{
                        width: 32,
                        height: 32,
                        borderRadius: 10,
                        alignItems: "center",
                        justifyContent: "center",
                      }}
                    >
                      <AppIcon icon={Folder02Icon} size={14} color={color} />
                    </View>
                    <Text
                      style={{
                        flex: 1,
                        fontSize: 15,
                        color: isSelected ? color : "#e4e4e7",
                        fontWeight: isSelected ? "600" : "400",
                      }}
                    >
                      {project.name}
                    </Text>
                    {isSelected ? (
                      <AppIcon icon={Tick02Icon} size={16} color={color} />
                    ) : null}
                  </Pressable>
                );
              })}
            </View>
          </BottomSheetScrollView>
        </BottomSheet.Content>
      </BottomSheet.Portal>
    </BottomSheet>
  );
});

ProjectPickerSheet.displayName = "ProjectPickerSheet";
