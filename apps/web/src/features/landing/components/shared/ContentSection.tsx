import { cn } from "@/lib/utils";

export function ContentSection({
  title,
  description,
  className,
}: {
  title?: string;
  description: string;
  className?: string;
}) {
  return (
    <div className={`flex flex-col gap-3 ${cn(className)}`}>
      {title && <h3 className="text-4xl font-medium text-foreground-900">{title}</h3>}
      <div className="text-lg font-light text-foreground-500">{description} </div>
    </div>
  );
}
