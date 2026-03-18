import { BottomSheetScrollView } from "@gorhom/bottom-sheet";
import { useRouter } from "expo-router";
import { forwardRef, useCallback, useImperativeHandle, useState } from "react";
import { Alert, Pressable, View } from "react-native";
import {
  Add01Icon,
  AppIcon,
  Delete02Icon,
  Folder02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";
import type { Project } from "../types/todo-types";
import { CreateProjectModal } from "./create-project-modal";

export interface ProjectListSheetRef {
  open: () => void;
  close: () => void;
}

interface ProjectListSheetProps {
  projects: Project[];
  onCreateProject: (data: { name: string; color?: string }) => Promise<void>;
  onDeleteProject: (id: string) => Promise<void>;
}

export const ProjectListSheet = forwardRef<
  ProjectListSheetRef,
  ProjectListSheetProps
>(({ projects, onCreateProject, onDeleteProject }, ref) => {
  const [isOpen, setIsOpen] = useState(false);
  const router = useRouter();
  const { spacing, fontSize } = useResponsive();
  const [showCreateModal, setShowCreateModal] = useState(false);

  useImperativeHandle(ref, () => ({
    open: () => setIsOpen(true),
    close: () => setIsOpen(false),
  }));

  const handleProjectPress = useCallback(
    (project: Project) => {
      setIsOpen(false);
      router.push(`/todos/project/${project.id}`);
    },
    [router],
  );

  const handleDeletePress = useCallback(
    (project: Project) => {
      Alert.alert(
        "Delete Project",
        `Are you sure you want to delete "${project.name}"? Todos in this project will not be deleted.`,
        [
          { text: "Cancel", style: "cancel" },
          {
            text: "Delete",
            style: "destructive",
            onPress: () => void onDeleteProject(project.id),
          },
        ],
      );
    },
    [onDeleteProject],
  );

  const handleCreated = useCallback(
    async (data: { name: string; color?: string }) => {
      await onCreateProject(data);
      setShowCreateModal(false);
    },
    [onCreateProject],
  );

  return (
    <>
      <BottomSheet isOpen={isOpen} onOpenChange={setIsOpen}>
        <BottomSheet.Portal>
          <BottomSheet.Overlay />
          <BottomSheet.Content
            snapPoints={["50%", "85%"]}
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
              {/* Sheet header */}
              <View
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  justifyContent: "space-between",
                  paddingVertical: spacing.md,
                  borderBottomWidth: 1,
                  borderBottomColor: "rgba(255,255,255,0.07)",
                  marginBottom: spacing.sm,
                }}
              >
                <Text
                  style={{
                    fontSize: fontSize.lg,
                    fontWeight: "600",
                    color: "#f4f4f5",
                  }}
                >
                  Projects
                </Text>
                <Pressable
                  onPress={() => setShowCreateModal(true)}
                  style={{
                    width: 32,
                    height: 32,
                    borderRadius: 999,
                    alignItems: "center",
                    justifyContent: "center",
                    backgroundColor: "rgba(22,193,255,0.15)",
                  }}
                >
                  <AppIcon icon={Add01Icon} size={16} color="#16c1ff" />
                </Pressable>
              </View>

              {/* Empty state */}
              {projects.length === 0 && (
                <View
                  style={{
                    alignItems: "center",
                    paddingVertical: spacing.xl,
                    gap: spacing.sm,
                  }}
                >
                  <AppIcon icon={Folder02Icon} size={36} color="#3f3f46" />
                  <Text
                    style={{
                      fontSize: fontSize.sm,
                      color: "#52525b",
                      textAlign: "center",
                    }}
                  >
                    No projects yet.{"\n"}Tap + to create your first project.
                  </Text>
                </View>
              )}

              {/* Project rows */}
              {projects.map((project) => {
                const color = project.color ?? "#71717a";
                return (
                  <Pressable
                    key={project.id}
                    onPress={() => handleProjectPress(project)}
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
                    {/* Color dot */}
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

                    {/* Name + count */}
                    <View style={{ flex: 1, gap: 2 }}>
                      <Text
                        style={{
                          fontSize: fontSize.base,
                          fontWeight: "500",
                          color: "#f4f4f5",
                        }}
                      >
                        {project.name}
                      </Text>
                      <Text style={{ fontSize: fontSize.xs, color: "#71717a" }}>
                        {project.todo_count}{" "}
                        {project.todo_count === 1 ? "task" : "tasks"}
                      </Text>
                    </View>

                    {/* Delete */}
                    {!project.is_default && (
                      <Pressable
                        onPress={() => handleDeletePress(project)}
                        hitSlop={8}
                        style={{
                          padding: spacing.xs,
                        }}
                      >
                        <AppIcon
                          icon={Delete02Icon}
                          size={16}
                          color="#52525b"
                        />
                      </Pressable>
                    )}
                  </Pressable>
                );
              })}
            </BottomSheetScrollView>
          </BottomSheet.Content>
        </BottomSheet.Portal>
      </BottomSheet>

      <CreateProjectModal
        visible={showCreateModal}
        onClose={() => setShowCreateModal(false)}
        onCreated={handleCreated}
      />
    </>
  );
});
