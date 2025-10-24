import { ReactNode } from "react";

interface EventDisplayCardProps {
  eventColor: string;
  label?: string;
  children: ReactNode;
  opacity?: number;
}

export const EventDisplayCard = ({
  eventColor,
  label,
  children,
  opacity = 1,
}: EventDisplayCardProps) => {
  return (
    <div
      className="relative flex items-start gap-2 rounded-lg p-3 pr-2 pl-5 transition-colors"
      style={{
        backgroundColor: `${eventColor}20`,
        opacity,
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
          <div className="mb-1 text-xs font-medium text-zinc-500">{label}</div>
        )}
        {children}
      </div>
    </div>
  );
};
