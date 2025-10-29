import { Button } from "@heroui/button";
import { ReactNode } from "react";

import { Tick02Icon } from "@/components/shared/icons";

export type EventStatus = "idle" | "loading" | "completed";
export type EventVariant = "display" | "action";

interface EventCardProps {
  eventColor: string;
  status?: EventStatus;
  label?: string;
  children: ReactNode;
  variant?: EventVariant;
  buttonColor?: "primary" | "danger";
  completedLabel?: string;
  icon?: React.ComponentType<{ width: number; color: undefined }>;
  onAction?: () => void;
  isDotted?: boolean;
  opacity?: number;
}

export const EventCard = ({
  eventColor,
  status = "idle",
  label,
  children,
  variant = "display",
  buttonColor = "primary",
  completedLabel = "Completed",
  icon: Icon,
  onAction,
  isDotted = false,
  opacity = 1,
}: EventCardProps) => {
  const hasAction = variant === "action" && onAction;
  const finalOpacity = status === "completed" ? 0.5 : opacity;

  return (
    <div
      className={`relative flex ${hasAction ? "items-end" : "items-start"} gap-2 rounded-lg p-3 pr-2 pl-5 transition-colors ${
        isDotted ? "border-2 border-dashed" : ""
      }`}
      style={{
        ...(isDotted
          ? {
              borderColor: `${eventColor}80`,
              backgroundColor: `${eventColor}10`,
            }
          : {
              backgroundColor: `${eventColor}20`,
            }),
        opacity: finalOpacity,
      }}
    >
      <div className="absolute top-0 left-1 flex h-full items-center">
        <div
          className="h-[80%] w-1 flex-shrink-0 rounded-full"
          style={{
            backgroundColor: eventColor,
          }}
        />
      </div>

      <div className="min-w-0 flex-1">
        {label && (
          <div
            className={`mb-1 text-xs font-medium ${
              isDotted ? "text-primary" : "text-zinc-500"
            }`}
          >
            {label}
          </div>
        )}
        {children}
      </div>

      {hasAction && (
        <Button
          color={buttonColor}
          size="sm"
          isDisabled={status === "completed"}
          isLoading={status === "loading"}
          onPress={onAction}
        >
          {status === "loading" ? (
            "Confirm"
          ) : status === "completed" ? (
            <>
              {Icon && <Tick02Icon width={18} color={undefined} />}
              {completedLabel}
            </>
          ) : (
            <>Confirm</>
          )}
        </Button>
      )}
    </div>
  );
};
