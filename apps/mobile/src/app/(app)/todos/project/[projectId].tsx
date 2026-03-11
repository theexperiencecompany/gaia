import { useLocalSearchParams } from "expo-router";
import { useMemo } from "react";
import { ActivityIndicator, View } from "react-native";
import { Text } from "@/components/ui/text";
import { ProjectDetailView } from "@/features/todos/components/project-detail-view";
import { useProjects } from "@/features/todos/hooks/use-projects";

function normalizeParam(raw: string | string[] | undefined): string | null {
  if (!raw) return null;
  const value = Array.isArray(raw) ? raw[0] : raw;
  const normalized = value.trim();
  return normalized.length > 0 ? normalized : null;
}

export default function ProjectDetailPage() {
  const { projectId } = useLocalSearchParams<{
    projectId?: string | string[];
  }>();
  const id = useMemo(() => normalizeParam(projectId), [projectId]);

  const { projects, isLoading } = useProjects();

  const project = useMemo(
    () => (id ? projects.find((p) => p.id === id) : null),
    [id, projects],
  );

  if (isLoading) {
    return (
      <View
        style={{
          flex: 1,
          backgroundColor: "#131416",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <ActivityIndicator color="#16c1ff" />
      </View>
    );
  }

  if (!project) {
    return (
      <View
        style={{
          flex: 1,
          backgroundColor: "#131416",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <Text style={{ color: "#71717a" }}>Project not found.</Text>
      </View>
    );
  }

  return <ProjectDetailView project={project} allProjects={projects} />;
}
