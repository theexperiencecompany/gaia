import { View } from "react-native";
import { AppIcon, Brain02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { colors } from "@/lib/design-tokens";
import { useResponsive } from "@/lib/responsive";

// Gap scale tokens (decisions §5): 2/4/8/12/16/24.
const GAP_SM = 4;
const GAP_MD = 8;
const GAP_LG = 12;
const GAP_XL = 16;

type MemoryDataShape = {
  type?: string;
  operation?: string;
  status?: string;
  count?: number;
  content?: string;
} | null;

function getMemoryLabel(memoryData: MemoryDataShape): string | null {
  if (!memoryData) return null;

  if (memoryData.type === "memory_stored") return "Memory stored";

  if (memoryData.status === "success") {
    switch (memoryData.operation) {
      case "create":
        return "Memory created";
      case "search":
        if (memoryData.count === 0) return "No memories found";
        if (memoryData.count === 1) return "Found 1 memory";
        return `Found ${memoryData.count} memories`;
      case "list":
        if (memoryData.count === 0) return "No memories";
        return `Retrieved ${memoryData.count} memories`;
      default:
        return "Memory updated";
    }
  }

  if (memoryData.status === "storing") return "Storing memory...";
  if (memoryData.status === "searching") return "Searching memories...";
  if (memoryData.status === "retrieving") return "Retrieving memories...";

  return null;
}

/** Muted pill noting a memory side-effect of the turn. */
export function MemoryIndicator({
  memoryData,
}: {
  memoryData: MemoryDataShape;
}) {
  const { fontSize, moderateScale } = useResponsive();
  const label = getMemoryLabel(memoryData);
  if (!label) return null;

  return (
    <View
      style={{
        marginTop: GAP_MD,
        paddingHorizontal: GAP_XL,
      }}
    >
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          alignSelf: "flex-start",
          gap: GAP_SM,
          backgroundColor: "rgba(63, 63, 70, 0.5)",
          borderRadius: moderateScale(12, 0.5),
          paddingHorizontal: GAP_LG,
          paddingVertical: GAP_SM,
        }}
      >
        <AppIcon
          icon={Brain02Icon}
          size={moderateScale(11, 0.5)}
          color={colors.zinc400}
        />
        <Text
          style={{
            fontSize: fontSize.xs,
            color: colors.zinc400,
            fontWeight: "500",
          }}
        >
          {label}
        </Text>
      </View>
    </View>
  );
}
