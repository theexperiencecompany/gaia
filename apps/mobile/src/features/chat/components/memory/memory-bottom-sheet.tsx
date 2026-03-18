import { BottomSheetScrollView } from "@gorhom/bottom-sheet";
import { forwardRef, useImperativeHandle, useState } from "react";
import { View } from "react-native";
import { AppIcon, Brain02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";

type MemoryDataShape = {
  type?: string;
  operation?: string;
  status?: string;
  count?: number;
  content?: string;
  memories?: Array<{ id: string; content: string; created_at?: string }>;
} | null;

export interface MemoryBottomSheetRef {
  open: (data: MemoryDataShape) => void;
  close: () => void;
}

export const MemoryBottomSheet = forwardRef<MemoryBottomSheetRef>((_, ref) => {
  const [isOpen, setIsOpen] = useState(false);
  const [memoryData, setMemoryData] = useState<MemoryDataShape>(null);
  const { spacing, fontSize } = useResponsive();

  useImperativeHandle(ref, () => ({
    open: (data) => {
      setMemoryData(data);
      setIsOpen(true);
    },
    close: () => setIsOpen(false),
  }));

  const memories = memoryData?.memories ?? [];
  const content = memoryData?.content;

  return (
    <BottomSheet isOpen={isOpen} onOpenChange={setIsOpen}>
      <BottomSheet.Portal>
        <BottomSheet.Overlay />
        <BottomSheet.Content
          snapPoints={["40%", "70%"]}
          enablePanDownToClose
          backgroundStyle={{ backgroundColor: "#1c1c1e" }}
          handleIndicatorStyle={{ backgroundColor: "#3f3f46" }}
        >
          <BottomSheetScrollView
            contentContainerStyle={{ padding: spacing.lg, gap: spacing.md }}
          >
            {/* Header */}
            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                gap: spacing.sm,
              }}
            >
              <AppIcon icon={Brain02Icon} size={18} color="#818cf8" />
              <Text
                style={{
                  fontSize: fontSize.base,
                  fontWeight: "600",
                  color: "#fff",
                }}
              >
                Memory
              </Text>
            </View>

            {/* Single content string */}
            {content ? (
              <View
                style={{
                  backgroundColor: "rgba(99,102,241,0.08)",
                  borderRadius: 12,
                  padding: spacing.md,
                  borderWidth: 1,
                  borderColor: "rgba(99,102,241,0.2)",
                }}
              >
                <Text
                  style={{
                    fontSize: fontSize.sm,
                    color: "#e4e4e7",
                    lineHeight: 20,
                  }}
                >
                  {content}
                </Text>
              </View>
            ) : null}

            {/* Memory list */}
            {memories.length > 0 ? (
              <View style={{ gap: spacing.sm }}>
                {memories.map((m, i) => (
                  <View
                    key={m.id ?? i}
                    style={{
                      backgroundColor: "rgba(99,102,241,0.08)",
                      borderRadius: 12,
                      padding: spacing.md,
                      borderWidth: 1,
                      borderColor: "rgba(99,102,241,0.2)",
                    }}
                  >
                    <Text
                      style={{
                        fontSize: fontSize.sm,
                        color: "#e4e4e7",
                        lineHeight: 20,
                      }}
                    >
                      {m.content}
                    </Text>
                    {m.created_at ? (
                      <Text
                        style={{
                          fontSize: fontSize.xs,
                          color: "#71717a",
                          marginTop: spacing.xs,
                        }}
                      >
                        {new Date(m.created_at).toLocaleDateString()}
                      </Text>
                    ) : null}
                  </View>
                ))}
              </View>
            ) : null}

            {/* Empty state */}
            {!content && memories.length === 0 ? (
              <Text
                style={{
                  fontSize: fontSize.sm,
                  color: "#71717a",
                  textAlign: "center",
                  paddingVertical: spacing.lg,
                }}
              >
                No memory details available
              </Text>
            ) : null}
          </BottomSheetScrollView>
        </BottomSheet.Content>
      </BottomSheet.Portal>
    </BottomSheet>
  );
});

MemoryBottomSheet.displayName = "MemoryBottomSheet";
