import {
  BottomSheetFlatList,
  BottomSheetTextInput,
} from "@gorhom/bottom-sheet";
import {
  forwardRef,
  useCallback,
  useImperativeHandle,
  useMemo,
  useState,
} from "react";
import { ActivityIndicator, Pressable, View } from "react-native";
import {
  AppIcon,
  Cancel01Icon,
  Search01Icon,
  WorkflowSquare10Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useWorkflows } from "@/features/workflows/hooks/use-workflows";
import type { Workflow } from "@/features/workflows/types/workflow-types";
import { useResponsive } from "@/lib/responsive";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";

export interface WorkflowPickerSheetRef {
  open: () => void;
  close: () => void;
}

interface WorkflowPickerSheetProps {
  onSelectWorkflow: (workflow: { id: string; title: string }) => void;
}

export const WorkflowPickerSheet = forwardRef<
  WorkflowPickerSheetRef,
  WorkflowPickerSheetProps
>(({ onSelectWorkflow }, ref) => {
  const [isOpen, setIsOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const { spacing, fontSize, iconSize } = useResponsive();

  const { workflows, isLoading } = useWorkflows();

  useImperativeHandle(ref, () => ({
    open: () => setIsOpen(true),
    close: () => setIsOpen(false),
  }));

  const filteredWorkflows = useMemo(() => {
    if (!searchQuery.trim()) return workflows;
    const query = searchQuery.toLowerCase();
    return workflows.filter(
      (workflow) =>
        workflow.title.toLowerCase().includes(query) ||
        workflow.description?.toLowerCase().includes(query),
    );
  }, [workflows, searchQuery]);

  const handleSelect = useCallback(
    (workflow: Workflow) => {
      onSelectWorkflow({ id: workflow.id, title: workflow.title });
      setIsOpen(false);
      setSearchQuery("");
    },
    [onSelectWorkflow],
  );

  const renderWorkflowItem = useCallback(
    ({ item }: { item: Workflow }) => (
      <Pressable
        onPress={() => handleSelect(item)}
        style={{
          flexDirection: "row",
          alignItems: "center",
          paddingHorizontal: spacing.md,
          paddingVertical: spacing.sm + 2,
          marginHorizontal: spacing.sm,
          borderRadius: 12,
        }}
        android_ripple={{ color: "rgba(255,255,255,0.08)" }}
      >
        <View
          style={{
            width: 32,
            height: 32,
            borderRadius: 8,
            backgroundColor: "#27272a",
            alignItems: "center",
            justifyContent: "center",
            marginRight: spacing.sm,
          }}
        >
          <AppIcon
            icon={WorkflowSquare10Icon}
            size={iconSize.sm}
            color="#a1a1aa"
          />
        </View>

        <View style={{ flex: 1, marginRight: spacing.sm }}>
          <Text
            style={{
              fontSize: fontSize.sm,
              color: "#e4e4e7",
              fontWeight: "400",
            }}
            numberOfLines={1}
          >
            {item.title}
          </Text>
          {!!item.description && (
            <Text
              style={{
                fontSize: fontSize.xs,
                color: "#71717a",
                marginTop: 2,
              }}
              numberOfLines={1}
            >
              {item.description}
            </Text>
          )}
        </View>

        {item.activated && (
          <View
            style={{
              backgroundColor: "#27272a",
              paddingHorizontal: spacing.sm,
              paddingVertical: 2,
              borderRadius: 10,
              borderWidth: 1,
              borderColor: "rgba(255,255,255,0.06)",
            }}
          >
            <Text
              style={{
                fontSize: fontSize.xs,
                color: "#71717a",
              }}
            >
              Active
            </Text>
          </View>
        )}
      </Pressable>
    ),
    [handleSelect, spacing, fontSize, iconSize],
  );

  return (
    <BottomSheet isOpen={isOpen} onOpenChange={setIsOpen}>
      <BottomSheet.Portal>
        <BottomSheet.Overlay />
        <BottomSheet.Content
          snapPoints={["60%", "85%"]}
          enableDynamicSizing={false}
          enablePanDownToClose
          backgroundStyle={{ backgroundColor: "#141414" }}
          handleIndicatorStyle={{ backgroundColor: "#3a3a3c", width: 40 }}
          keyboardBehavior="interactive"
          keyboardBlurBehavior="restore"
        >
          {/* Header */}
          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "space-between",
              paddingHorizontal: spacing.md,
              paddingBottom: spacing.sm,
            }}
          >
            <Text
              style={{
                fontSize: fontSize.lg,
                fontWeight: "600",
                color: "#ffffff",
              }}
            >
              Workflows
            </Text>
            <Pressable
              onPress={() => setIsOpen(false)}
              style={{
                width: 32,
                height: 32,
                borderRadius: 16,
                backgroundColor: "rgba(142,142,147,0.1)",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <AppIcon icon={Cancel01Icon} size={18} color="#8e8e93" />
            </Pressable>
          </View>

          {/* Search */}
          <View
            style={{
              paddingHorizontal: spacing.md,
              paddingBottom: spacing.sm,
            }}
          >
            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                borderRadius: 12,
                paddingHorizontal: spacing.sm + 2,
                paddingVertical: spacing.sm,
                backgroundColor: "rgba(142,142,147,0.1)",
              }}
            >
              <AppIcon icon={Search01Icon} size={18} color="#8e8e93" />
              <BottomSheetTextInput
                style={{
                  flex: 1,
                  marginLeft: spacing.sm,
                  color: "#ffffff",
                  fontSize: fontSize.sm,
                  padding: 0,
                }}
                placeholder="Search workflows..."
                placeholderTextColor="#6b6b6b"
                value={searchQuery}
                onChangeText={setSearchQuery}
              />
            </View>
          </View>

          {/* Workflow list */}
          {isLoading ? (
            <View
              style={{
                flex: 1,
                alignItems: "center",
                justifyContent: "center",
                paddingVertical: 32,
              }}
            >
              <ActivityIndicator size="large" color="#8e8e93" />
              <Text
                style={{
                  color: "#6b6b6b",
                  fontSize: fontSize.sm,
                  marginTop: spacing.sm,
                }}
              >
                Loading workflows...
              </Text>
            </View>
          ) : (
            <BottomSheetFlatList
              data={filteredWorkflows}
              keyExtractor={(item: Workflow) => item.id}
              renderItem={renderWorkflowItem}
              contentContainerStyle={{
                paddingBottom: 24,
                paddingTop: spacing.xs,
              }}
              showsVerticalScrollIndicator={false}
              ListEmptyComponent={
                <View
                  style={{
                    alignItems: "center",
                    justifyContent: "center",
                    paddingVertical: 32,
                  }}
                >
                  <Text
                    style={{
                      color: "#6b6b6b",
                      fontSize: fontSize.sm,
                    }}
                  >
                    No workflows found
                  </Text>
                </View>
              }
            />
          )}
        </BottomSheet.Content>
      </BottomSheet.Portal>
    </BottomSheet>
  );
});

WorkflowPickerSheet.displayName = "WorkflowPickerSheet";
