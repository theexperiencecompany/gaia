import { GaiaButton } from "@/components/shared/GaiaButton";
import { cn } from "@/lib/utils";

interface LoadErrorProps {
  title: string;
  /** What is still true despite the failed read; left out of the inline form. */
  description?: string;
  onRetry: () => void;
  /** "block" stands in for a whole page or panel; "inline" sits in a row of other content. */
  layout?: "block" | "inline";
  className?: string;
}

/**
 * A read that failed and can be retried. Shown instead of the data, never next
 * to defaults, so nothing on screen passes for what is stored.
 */
export function LoadError({
  title,
  description,
  onRetry,
  layout = "block",
  className,
}: LoadErrorProps) {
  if (layout === "inline") {
    return (
      <div className={cn("flex items-center gap-3", className)}>
        <p className="text-sm text-zinc-500">{title}</p>
        <GaiaButton size="sm" variant="default-soft" onPress={onRetry}>
          Try again
        </GaiaButton>
      </div>
    );
  }
  return (
    <div
      className={cn(
        "flex flex-col items-center gap-3 rounded-2xl bg-zinc-900/60 p-10 text-center",
        className,
      )}
    >
      <p className="text-sm font-medium text-zinc-200">{title}</p>
      {description && (
        <p className="max-w-sm text-xs text-zinc-500">{description}</p>
      )}
      <GaiaButton
        size="sm"
        variant="accent-soft"
        shape="pill"
        className="mt-1 font-medium"
        onPress={onRetry}
      >
        Try again
      </GaiaButton>
    </div>
  );
}
