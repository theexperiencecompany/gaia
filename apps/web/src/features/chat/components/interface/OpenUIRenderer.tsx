import {
  type ActionEvent,
  type ParseResult,
  Renderer,
} from "@openuidev/react-lang";
import { dispatchOpenUIAction, normalizeOpenUICode } from "@shared/utils";
import React from "react";
import { genericLibrary } from "@/config/openui/genericLibrary";
import {
  OpenUIErrorBoundary,
  OpenUIErrorCard,
} from "@/config/openui/OpenUIErrorBoundary";
import { useAppendToInput } from "@/stores/composerStore";

interface OpenUIRendererProps {
  code: string;
  isStreaming: boolean;
}

function OpenUIShimmer() {
  return (
    <div className="w-full max-w-lg animate-pulse rounded-2xl bg-zinc-800 p-4">
      <div className="space-y-2.5">
        <div className="h-3 w-full rounded-lg bg-zinc-700/70" />
        <div className="h-3 w-5/6 rounded-lg bg-zinc-700/70" />
        <div className="h-3 w-2/3 rounded-lg bg-zinc-700/70" />
      </div>
      <div className="mt-4 h-24 w-full rounded-xl bg-zinc-700/50" />
    </div>
  );
}

function OpenUIRendererInner({ code, isStreaming }: OpenUIRendererProps) {
  const appendToInput = useAppendToInput();
  const normalizedCode = React.useMemo(
    () => normalizeOpenUICode(code, genericLibrary),
    [code],
  );

  const [failedForCode, setFailedForCode] = React.useState<string | null>(null);
  const [failureReason, setFailureReason] = React.useState<string>("");
  const [hasRendered, setHasRendered] = React.useState(false);
  const parseFailed = !isStreaming && failedForCode === normalizedCode;

  const handleAction = React.useCallback(
    (event: ActionEvent) => {
      dispatchOpenUIAction(event, {
        appendToInput,
        openUrl: (url) => {
          window.open(url, "_blank", "noopener,noreferrer");
        },
      }).catch((err) => {
        console.error("[OpenUIRenderer] Action dispatch failed:", err);
      });
    },
    [appendToInput],
  );

  const handleParseResult = React.useCallback(
    (result: ParseResult | null) => {
      if (!result) return;
      if (result.root !== null && !hasRendered) {
        setHasRendered(true);
      }
      const failed = result.root === null && !isStreaming;
      if (failed) {
        const errors = result.meta?.errors;
        const reason = errors?.length
          ? errors
              .map((e: unknown) =>
                typeof e === "string" ? e : JSON.stringify(e),
              )
              .join("; ")
          : "Parse produced no root node";
        console.error(`[OpenUIRenderer] ${reason}`, {
          rawCode: code,
          normalizedCode,
          unresolved: result.meta?.unresolved,
          statementCount: result.meta?.statementCount,
        });
        setFailedForCode(normalizedCode);
        setFailureReason(reason);
      } else {
        setFailedForCode(null);
        setFailureReason("");
      }
    },
    [code, normalizedCode, isStreaming, hasRendered],
  );

  if (parseFailed) {
    return <OpenUIErrorCard code={code} error={failureReason} />;
  }

  const showShimmer = isStreaming && !hasRendered;

  return (
    <>
      {showShimmer && <OpenUIShimmer />}
      <div className={showShimmer ? "hidden" : undefined}>
        <Renderer
          response={normalizedCode}
          library={genericLibrary}
          isStreaming={isStreaming}
          onAction={handleAction}
          onParseResult={handleParseResult}
          onError={(errors) => {
            // Surface structured validation errors so an empty render is never
            // silent (the previous parser dropped invalid trees with no signal).
            if (errors.length > 0) {
              console.error("[OpenUIRenderer] validation errors:", errors);
            }
          }}
        />
      </div>
    </>
  );
}

export default function OpenUIRenderer({
  code,
  isStreaming,
}: OpenUIRendererProps) {
  return (
    <OpenUIErrorBoundary code={code}>
      <div className="my-4">
        <OpenUIRendererInner code={code} isStreaming={isStreaming} />
      </div>
    </OpenUIErrorBoundary>
  );
}
