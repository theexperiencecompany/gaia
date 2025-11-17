import { cn } from "@/lib/utils";

export function ContentSection({
  title,
  description,
  className,
}: {
  title: string;
  description: string;
  className?: string;
}) {
  return (
    <div className={`flex flex-col gap-2 ${cn(className)}`}>
      <h3 className="text-4xl font-medium text-zinc-100">{title}</h3>
      <p className="text-lg font-light text-zinc-400">{description}</p>
    </div>
  );
}
