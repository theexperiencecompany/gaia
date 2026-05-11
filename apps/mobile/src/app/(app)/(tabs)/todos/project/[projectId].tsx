import { useLocalSearchParams } from "expo-router";
import { ActivityIndicator, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Text } from "@/components/ui/text";
import { ProjectDetailView } from "@/features/todos/components/project-detail-view";
import { useProjects } from "@/features/todos/hooks/use-projects";
import { useResponsive } from "@/lib/responsive";
import { BackButton } from "@/shared/components/ui/back-button";

export default function ProjectDetailPage() {
  const { projectId } = useLocalSearchParams<{ projectId: string }>();
  const insets = useSafeAreaInsets();
  const { spacing, fontSize } = useResponsive();
  const { projects, isLoading } = useProjects();

  const project = projects.find((p) => p.id === projectId);

  if (isLoading && !project) {
    return (
      <View style={{ flex: 1, backgroundColor: "#131416" }}>
        <View
          style={{
            paddingTop: insets.top + spacing.sm,
            paddingHorizontal: spacing.md,
            paddingBottom: spacing.md,
            flexDirection: "row",
            alignItems: "center",
            gap: spacing.sm,
          }}
        >
          <BackButton />
        </View>
        <View
          style={{ flex: 1, alignItems: "center", justifyContent: "center" }}
        >
          <ActivityIndicator color="#16c1ff" />
        </View>
      </View>
    );
  }

  if (!project) {
    return (
      <View style={{ flex: 1, backgroundColor: "#131416" }}>
        <View
          style={{
            paddingTop: insets.top + spacing.sm,
            paddingHorizontal: spacing.md,
            paddingBottom: spacing.md,
            flexDirection: "row",
            alignItems: "center",
            gap: spacing.sm,
          }}
        >
          <BackButton />
          <Text
            style={{
              fontSize: fontSize.lg,
              fontWeight: "600",
              color: "#f4f4f5",
            }}
          >
            Project
          </Text>
        </View>
        <View
          style={{
            flex: 1,
            alignItems: "center",
            justifyContent: "center",
            paddingHorizontal: 32,
            gap: 8,
          }}
        >
          <Text
            style={{
              fontSize: fontSize.base,
              fontWeight: "600",
              color: "#71717a",
              textAlign: "center",
            }}
          >
            Project not found
          </Text>
          <Text
            style={{
              fontSize: fontSize.sm,
              color: "#52525b",
              textAlign: "center",
            }}
          >
            This project may have been deleted.
          </Text>
        </View>
      </View>
    );
  }

  return <ProjectDetailView project={project} allProjects={projects} />;
}
