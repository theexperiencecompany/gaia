import { Chip } from "heroui-native";
import { View, type ViewProps } from "react-native";
import { cn } from "@/lib/utils";

type ChipProps = React.ComponentProps<typeof Chip>;

export interface AppFilterChipOption {
  key: string;
  label: string;
  count?: number;
  icon?: React.ReactNode;
  isDisabled?: boolean;
  testID?: string;
}

export interface AppFilterChipGroupProps extends ViewProps {
  options: readonly AppFilterChipOption[];
  selectedKey?: string | null;
  onSelect?: (key: string | undefined) => void;
  allowsEmptySelection?: boolean;
  className?: string;
  chipClassName?: string;
  size?: ChipProps["size"];
  selectedVariant?: ChipProps["variant"];
  unselectedVariant?: ChipProps["variant"];
  selectedColor?: ChipProps["color"];
  unselectedColor?: ChipProps["color"];
}

export function AppFilterChipGroup({
  options,
  selectedKey,
  onSelect,
  allowsEmptySelection = false,
  className,
  chipClassName,
  size = "sm",
  selectedVariant = "primary",
  unselectedVariant = "secondary",
  selectedColor = "accent",
  unselectedColor = "default",
  ...viewProps
}: AppFilterChipGroupProps) {
  return (
    <View className={cn("flex-row flex-wrap gap-2", className)} {...viewProps}>
      {options.map((option) => {
        const isSelected = option.key === selectedKey;

        const handlePress = () => {
          if (option.isDisabled) return;

          if (allowsEmptySelection && isSelected) {
            onSelect?.(undefined);
            return;
          }

          onSelect?.(option.key);
        };

        return (
          <Chip
            key={option.key}
            size={size}
            onPress={handlePress}
            disabled={option.isDisabled}
            testID={option.testID}
            animation="disable-all"
            variant={isSelected ? selectedVariant : unselectedVariant}
            color={isSelected ? selectedColor : unselectedColor}
            className={chipClassName}
          >
            {option.icon}
            <Chip.Label>
              {typeof option.count === "number"
                ? `${option.label} (${option.count})`
                : option.label}
            </Chip.Label>
          </Chip>
        );
      })}
    </View>
  );
}
