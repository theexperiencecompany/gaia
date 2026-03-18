import { Card } from "heroui-native";
import type { ReactNode } from "react";
import { View } from "react-native";
import { cn } from "@/lib/utils";

type CardProps = React.ComponentProps<typeof Card>;

export interface AppSectionCardProps
  extends Omit<CardProps, "children" | "className"> {
  children?: ReactNode;
  title?: ReactNode;
  description?: ReactNode;
  headerContent?: ReactNode;
  footer?: ReactNode;
  className?: string;
  headerClassName?: string;
  bodyClassName?: string;
  footerClassName?: string;
}

export function AppSectionCard({
  children,
  title,
  description,
  headerContent,
  footer,
  className,
  headerClassName,
  bodyClassName,
  footerClassName,
  variant = "secondary",
  animation = "disable-all",
  ...cardProps
}: AppSectionCardProps) {
  const hasHeader = title || description || headerContent;

  return (
    <Card
      {...cardProps}
      variant={variant}
      animation={animation}
      className={cn("rounded-3xl", className)}
    >
      {hasHeader ? (
        <Card.Header className={cn("pb-0", headerClassName)}>
          <View className="flex-row items-start justify-between gap-3">
            <View className="min-w-0 flex-1 gap-1">
              {title ? <Card.Title>{title}</Card.Title> : null}
              {description ? (
                <Card.Description>{description}</Card.Description>
              ) : null}
            </View>
            {headerContent}
          </View>
        </Card.Header>
      ) : null}

      <Card.Body className={cn("gap-3", bodyClassName)}>{children}</Card.Body>

      {footer ? (
        <Card.Footer className={cn("pt-0", footerClassName)}>
          {footer}
        </Card.Footer>
      ) : null}
    </Card>
  );
}
