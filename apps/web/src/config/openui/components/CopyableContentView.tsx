import { Button } from "@heroui/react";
import { CheckmarkCircle02Icon, Copy01Icon } from "@icons";
import React from "react";
import type { z } from "zod";
import { cn } from "@/lib/utils";
import { ToolCard } from "../primitives/ToolCard";
import type { copyableContentSchema } from "../promptSpecs";

export function CopyableContentView(
  props: z.infer<typeof copyableContentSchema>,
) {
  const [copied, setCopied] = React.useState(false);
  const inline = props.mode === "inline";
  const timeoutRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  React.useEffect(
    () => () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    },
    [],
  );

  const copy = React.useCallback(() => {
    // navigator.clipboard is undefined in non-secure contexts (e.g. http,
    // some webviews). Calling writeText on undefined would throw synchronously
    // before the catch can swallow it.
    if (!navigator.clipboard?.writeText) return;
    void navigator.clipboard
      .writeText(props.content)
      .then(() => {
        setCopied(true);
        if (timeoutRef.current) clearTimeout(timeoutRef.current);
        timeoutRef.current = setTimeout(() => setCopied(false), 1800);
      })
      .catch(() => {
        /* best-effort copy: clipboard failures (permissions, insecure context) are non-actionable */
      });
  }, [props.content]);

  if (inline) {
    return (
      <Button
        size="sm"
        variant="flat"
        onPress={copy}
        aria-label={copied ? "Copied" : "Copy content"}
        className="inline-flex items-center gap-1.5 rounded-full bg-zinc-800 hover:bg-zinc-700 transition-colors px-3 py-1.5 min-w-0 h-auto"
      >
        <span className="font-mono text-xs text-zinc-200 truncate">
          {props.content}
        </span>
        {copied ? (
          <CheckmarkCircle02Icon className="w-3.5 h-3.5 shrink-0 text-emerald-400" />
        ) : (
          <Copy01Icon className="w-3 h-3 shrink-0 text-zinc-500" />
        )}
      </Button>
    );
  }

  const isCode =
    props.languageHint !== undefined ||
    props.content.includes("\n") ||
    /^[A-Z_]+=/.test(props.content);

  return (
    <ToolCard size="standard" className="p-3">
      <div className="flex items-start gap-2">
        <pre
          className={cn(
            "flex-1 text-sm leading-relaxed break-words whitespace-pre-wrap",
            isCode ? "font-mono text-zinc-200" : "font-sans text-zinc-300",
          )}
        >
          {props.content}
        </pre>
        <Button
          isIconOnly
          size="sm"
          variant="light"
          onPress={copy}
          aria-label={copied ? "Copied" : "Copy content"}
          className={cn(
            "shrink-0 aspect-square min-w-7 w-7 h-7 p-0",
            copied ? "text-emerald-400" : "text-zinc-500",
          )}
        >
          {copied ? (
            <CheckmarkCircle02Icon className="w-4 h-4" />
          ) : (
            <Copy01Icon className="w-3.5 h-3.5" />
          )}
        </Button>
      </div>
    </ToolCard>
  );
}
