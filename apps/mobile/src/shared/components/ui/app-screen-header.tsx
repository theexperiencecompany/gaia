import { Button } from "heroui-native";
import type { ReactNode } from "react";
import { View, type ViewProps } from "react-native";
import { Text } from "@/components/ui/text";
import { cn } from "@/lib/utils";

type ButtonProps = React.ComponentProps<typeof Button>;

export interface AppScreenHeaderAction {
  label: string;
  onPress?: ButtonProps["onPress"];
  icon?: ReactNode;
  variant?: ButtonProps["variant"];
  size?: ButtonProps["size"];
  isDisabled?: boolean;
  className?: string;
  testID?: string;
}

export interface AppScreenHeaderProps extends ViewProps {
  title: string;
  subtitle?: string;
  leadingAction?: AppScreenHeaderAction;
  trailingAction?: AppScreenHeaderAction;
  className?: string;
  titleClassName?: string;
  subtitleClassName?: string;
}

function HeaderActionSlot({
  action,
  align,
  fallbackVariant,
}: {
  action?: AppScreenHeaderAction;
  align: "start" | "end";
  fallbackVariant: ButtonProps["variant"];
}) {
  return (
    <View
      className={cn(
        "min-w-[88px] flex-1",
        align === "start" ? "items-start" : "items-end",
      )}
    >
      {action ? (
        <Button
          size={action.size ?? "sm"}
          variant={action.variant ?? fallbackVariant}
          onPress={action.onPress}
          isDisabled={action.isDisabled}
          testID={action.testID}
          className={action.className}
        >
          {action.icon}
          <Button.Label>{action.label}</Button.Label>
        </Button>
      ) : null}
    </View>
  );
}

export function AppScreenHeader({
  title,
  subtitle,
  leadingAction,
  trailingAction,
  className,
  titleClassName,
  subtitleClassName,
  ...viewProps
}: AppScreenHeaderProps) {
  return (
    <View
      className={cn(
        "flex-row items-center gap-3 border-b border-border/10 bg-background px-4 py-3",
        className,
      )}
      {...viewProps}
    >
      <HeaderActionSlot
        action={leadingAction}
        align="start"
        fallbackVariant="ghost"
      />

      <View className="min-w-0 flex-[2] items-center">
        <Text
          className={cn("text-center text-base font-semibold", titleClassName)}
          numberOfLines={1}
        >
          {title}
        </Text>
        {subtitle ? (
          <Text
            className={cn(
              "mt-0.5 text-center text-sm text-muted",
              subtitleClassName,
            )}
            numberOfLines={1}
          >
            {subtitle}
          </Text>
        ) : null}
      </View>

      <HeaderActionSlot
        action={trailingAction}
        align="end"
        fallbackVariant="secondary"
      />
    </View>
  );
}
