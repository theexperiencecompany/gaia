import { cn } from "@/lib";

export function BentoItem({
  title,
  description,
  children,
  childrenClassName,
}: {
  title: string;
  description: string;
  children?: React.ReactNode;
  childrenClassName?: string;
}) {
  return (
    <div className="flex aspect-square flex-col gap-2 sm:gap-3">
      <div
        className={cn(
          "flex h-[90%] w-full min-w-full items-center justify-center rounded-2xl bg-zinc-800/70 p-3 sm:rounded-3xl sm:p-4",
          childrenClassName,
        )}
      >
        {children}
      </div>
      <div className="flex flex-col text-base text-foreground-400 sm:text-lg lg:text-xl">
        <span className="text-foreground">{title}</span>
        <span className="text-sm font-light sm:text-base lg:text-lg">
          {description}
        </span>
      </div>
    </div>
  );
}

export default function TodosBentoContent() {
  return (
    <div className="px-2 sm:px-4">
      <div className="grid w-full grid-cols-1 grid-rows-1 justify-between gap-4 p-2 sm:grid-cols-2 sm:gap-6 sm:p-4 lg:grid-cols-3 lg:gap-7">
        <BentoItem
          title="Smart Task Organization"
          description="Automatically categorize and prioritize your tasks based on deadlines and importance."
        />
        <BentoItem
          title="Natural Language Planning"
          description="Just tell GAIA what you need to do - it converts your thoughts into actionable tasks."
        />
        <BentoItem
          title="Intelligent Reminders"
          description="Get timely reminders and suggestions to help you stay on track with your goals."
        />
      </div>
    </div>
  );
}
