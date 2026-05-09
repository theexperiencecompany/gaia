import { type Href, usePathname, useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, View } from "react-native";
import { useShallow } from "zustand/react/shallow";
import {
  Add01Icon,
  type AnyIcon,
  AppIcon,
  Flag02Icon,
  Folder02Icon,
  Tag01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useSidebar } from "@/features/chat/hooks/sidebar-context";
import { selectionHaptic } from "@/lib/haptics";
import { useTodoStore } from "../../store/todo-store";
import { Priority } from "../../types/todo-types";
import { CreateProjectModal } from "../create-project-modal";

const SECTION_PADDING = 12;
const ROW_PADDING = 12;
const MAX_PROJECTS = 5;
const MAX_LABELS = 5;

const PRIORITY_TINTS: Record<
  Exclude<Priority, Priority.NONE>,
  { label: string; color: string }
> = {
  [Priority.HIGH]: { label: "High Priority", color: "#f87171" },
  [Priority.MEDIUM]: { label: "Medium Priority", color: "#facc15" },
  [Priority.LOW]: { label: "Low Priority", color: "#60a5fa" },
};

interface SidebarRowProps {
  label: string;
  icon: AnyIcon;
  iconColor?: string;
  count?: number;
  active?: boolean;
  onPress: () => void;
}

function SidebarRow({
  label,
  icon,
  iconColor,
  count,
  active,
  onPress,
}: SidebarRowProps) {
  return (
    <Pressable
      onPress={() => {
        selectionHaptic();
        onPress();
      }}
      style={({ pressed }) => ({
        flexDirection: "row",
        alignItems: "center",
        gap: 12,
        paddingHorizontal: ROW_PADDING,
        paddingVertical: 10,
        borderRadius: 10,
        backgroundColor: active
          ? "rgba(0,187,255,0.10)"
          : pressed
            ? "rgba(255,255,255,0.04)"
            : "transparent",
        overflow: "hidden",
      })}
      accessibilityRole="button"
      accessibilityLabel={label}
    >
      {active ? (
        <View
          style={{
            position: "absolute",
            left: 0,
            top: 0,
            bottom: 0,
            width: 3,
            backgroundColor: "#00bbff",
          }}
        />
      ) : null}
      <View
        style={{
          width: 22,
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <AppIcon icon={icon} size={18} color={iconColor ?? "#a1a1aa"} />
      </View>
      <Text
        style={{
          fontSize: 14,
          fontWeight: active ? "600" : "500",
          color: active ? "#ffffff" : "#e4e4e7",
          flex: 1,
        }}
      >
        {label}
      </Text>
      {typeof count === "number" && count > 0 ? (
        <Text style={{ fontSize: 12, color: "#71717a" }}>{count}</Text>
      ) : null}
    </Pressable>
  );
}

interface SectionHeaderProps {
  title: string;
  action?: { icon: AnyIcon; onPress: () => void; accessibilityLabel: string };
}

function SectionHeader({ title, action }: SectionHeaderProps) {
  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
        paddingHorizontal: ROW_PADDING,
        paddingTop: 14,
        paddingBottom: 4,
      }}
    >
      <Text
        style={{
          fontSize: 11,
          fontWeight: "600",
          color: "#71717a",
          letterSpacing: 0.6,
          textTransform: "uppercase",
        }}
      >
        {title}
      </Text>
      {action ? (
        <Pressable
          onPress={() => {
            selectionHaptic();
            action.onPress();
          }}
          hitSlop={6}
          accessibilityRole="button"
          accessibilityLabel={action.accessibilityLabel}
          style={({ pressed }) => ({
            width: 22,
            height: 22,
            borderRadius: 11,
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: pressed
              ? "rgba(255,255,255,0.10)"
              : "rgba(63,63,70,0.40)",
          })}
        >
          <AppIcon icon={action.icon} size={11} color="#a1a1aa" />
        </Pressable>
      ) : null}
    </View>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <Text
      style={{
        fontSize: 12,
        color: "#52525b",
        fontStyle: "italic",
        paddingHorizontal: ROW_PADDING,
        paddingVertical: 8,
      }}
    >
      {message}
    </Text>
  );
}

/**
 * Todo-context section for the shared sidebar. Rendered between the main
 * nav and the New Chat button when the current pathname starts with
 * `/todos`. Uses the same horizontal padding as every other sidebar
 * section so all items align edge-to-edge. Sized to content (no flex)
 * so it doesn't fight `ChatHistory` for vertical space below.
 */
export function TodoSidebarSection() {
  const router = useRouter();
  const pathname = usePathname();
  const { closeSidebar } = useSidebar();
  const [createOpen, setCreateOpen] = useState(false);

  const { projects, labels, createProject } = useTodoStore(
    useShallow((s) => ({
      projects: s.projects,
      labels: s.labels,
      createProject: s.createProject,
    })),
  );

  const navigate = (href: string) => {
    closeSidebar();
    router.push(href as Href);
  };

  const userProjects = projects
    .filter((p) => !p.is_default)
    .slice(0, MAX_PROJECTS);

  const activeProjectId = pathname.startsWith("/todos/project/")
    ? decodeURIComponent(pathname.replace("/todos/project/", ""))
    : null;
  const activePriority = pathname.startsWith("/todos/priority/")
    ? pathname.replace("/todos/priority/", "")
    : null;
  const activeLabel = pathname.startsWith("/todos/label/")
    ? decodeURIComponent(pathname.replace("/todos/label/", ""))
    : null;

  return (
    <View style={{ paddingHorizontal: SECTION_PADDING, gap: 2 }}>
      <SectionHeader
        title="Projects"
        action={{
          icon: Add01Icon,
          onPress: () => setCreateOpen(true),
          accessibilityLabel: "Add project",
        }}
      />
      {userProjects.length === 0 ? (
        <EmptyState message="No projects yet" />
      ) : (
        userProjects.map((project) => (
          <SidebarRow
            key={project.id}
            label={project.name}
            icon={Folder02Icon}
            iconColor={project.color ?? "#a1a1aa"}
            count={project.todo_count}
            active={activeProjectId === project.id}
            onPress={() => navigate(`/todos/project/${project.id}`)}
          />
        ))
      )}

      <SectionHeader title="Priorities" />
      {(Object.keys(PRIORITY_TINTS) as Array<keyof typeof PRIORITY_TINTS>).map(
        (priority) => {
          const meta = PRIORITY_TINTS[priority];
          return (
            <SidebarRow
              key={priority}
              label={meta.label}
              icon={Flag02Icon}
              iconColor={meta.color}
              active={activePriority === priority}
              onPress={() => navigate(`/todos/priority/${priority}`)}
            />
          );
        },
      )}

      {labels.length > 0 ? (
        <>
          <SectionHeader title="Labels" />
          {labels.slice(0, MAX_LABELS).map((label) => (
            <SidebarRow
              key={label.name}
              label={label.name}
              icon={Tag01Icon}
              count={label.count}
              active={activeLabel === label.name}
              onPress={() =>
                navigate(`/todos/label/${encodeURIComponent(label.name)}`)
              }
            />
          ))}
        </>
      ) : null}

      <CreateProjectModal
        visible={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={async (data) => {
          await createProject(data);
          setCreateOpen(false);
        }}
      />
    </View>
  );
}
