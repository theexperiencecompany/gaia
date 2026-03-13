import { Button, Card } from "heroui-native";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

type ButtonProps = React.ComponentProps<typeof Button>;
type CardProps = React.ComponentProps<typeof Card>;

export interface AppEmptyStateAction {
  label: string;
  onPress?: ButtonProps["onPress"];
  variant?: ButtonProps["variant"];
  size?: ButtonProps["size"];
  isDisabled?: boolean;
  icon?: ReactNode;
  className?: string;
}

export interface AppEmptyStateCardProps
  extends Omit<CardProps, "children" | "className"> {
  title: string;
  description?: string;
  icon?: ReactNode;
  action?: AppEmptyStateAction;
  children?: ReactNode;
  className?: string;
  bodyClassName?: string;
}

export function AppEmptyStateCard({
  title,
  description,
  icon,
  action,
  children,
  className,
  bodyClassName,
  variant = "secondary",
  animation = "disable-all",
  ...cardProps
}: AppEmptyStateCardProps) {
  return (
    <Card
      {...cardProps}
      variant={variant}
      animation={animation}
      className={cn("rounded-3xl", className)}
    >
      <Card.Body
        className={cn(
          "items-center justify-center gap-3 px-5 py-8",
          bodyClassName,
        )}
      >
        {icon}
        <Card.Title className="text-center">{title}</Card.Title>
        {description ? (
          <Card.Description className="text-center">
            {description}
          </Card.Description>
        ) : null}
        {children}
        {action ? (
          <Button
            size={action.size ?? "sm"}
            variant={action.variant ?? "secondary"}
            onPress={action.onPress}
            isDisabled={action.isDisabled}
            className={action.className}
          >
            {action.icon}
            <Button.Label>{action.label}</Button.Label>
          </Button>
        ) : null}
      </Card.Body>
    </Card>
  );
}
