import { Alert01Icon } from "@icons";
import {
  type ActionEvent,
  type ParseResult,
  Renderer,
} from "@openuidev/react-lang";
import React from "react";
import { genericLibrary } from "@/config/openui/genericLibrary";
import { dispatchOpenUIAction } from "@/features/chat/actions/openUIActionDispatcher";
import { normalizeOpenUICode } from "@/features/chat/utils/openUIParser";
import { useAppendToInput } from "@/stores/composerStore";

interface OpenUIRendererProps {
  code: string;
  isStreaming: boolean;
}

function OpenUIErrorCard({ code, error }: { code: string; error?: string }) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4 w-full max-w-lg">
      <div className="flex items-center gap-2 mb-2">
        <Alert01Icon className="h-4 w-4 text-red-400 shrink-0" />
        <p className="text-sm font-medium text-red-400">
          Component failed to render
        </p>
      </div>
      {error && <p className="text-xs text-zinc-500 mb-2">{error}</p>}
      <pre className="rounded-xl bg-zinc-900 p-3 text-xs text-zinc-400 overflow-x-auto whitespace-pre-wrap break-all">
        {code}
      </pre>
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
  const parseFailed = !isStreaming && failedForCode === normalizedCode;

  const handleAction = React.useCallback(
    (event: ActionEvent) => {
      dispatchOpenUIAction(event, appendToInput).catch((err) => {
        console.error("[OpenUIRenderer] Action dispatch failed:", err);
      });
    },
    [appendToInput],
  );

  const handleParseResult = React.useCallback(
    (result: ParseResult | null) => {
      if (!result) return;
      const failed = result.root === null && !isStreaming;
      if (failed) {
        const errors = result.meta?.validationErrors;
        const reason = errors?.length
          ? errors
              .map((e: unknown) =>
                typeof e === "string" ? e : JSON.stringify(e),
              )
              .join("; ")
          : "Parse produced no root node";
        console.error("[OpenUIRenderer] " + reason, {
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
    [code, normalizedCode, isStreaming],
  );

  if (parseFailed) {
    return <OpenUIErrorCard code={code} error={failureReason} />;
  }

  return (
    <Renderer
      response={normalizedCode}
      library={genericLibrary}
      isStreaming={isStreaming}
      onAction={handleAction}
      onParseResult={handleParseResult}
    />
  );
}

class OpenUIErrorBoundary extends React.Component<
  { children: React.ReactNode; code: string },
  { hasError: boolean; errorMessage: string }
> {
  constructor(props: { children: React.ReactNode; code: string }) {
    super(props);
    this.state = { hasError: false, errorMessage: "" };
  }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, errorMessage: error.message };
  }

  componentDidUpdate(prevProps: { code: string }) {
    if (this.state.hasError && prevProps.code !== this.props.code) {
      this.setState({ hasError: false, errorMessage: "" });
    }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("[OpenUIRenderer] Render error:", error, info, {
      code: this.props.code,
    });
  }

  render() {
    if (this.state.hasError) {
      return (
        <OpenUIErrorCard
          code={this.props.code}
          error={this.state.errorMessage}
        />
      );
    }
    return this.props.children;
  }
}

export default function OpenUIRenderer({
  code,
  isStreaming,
}: OpenUIRendererProps) {
  return (
    <OpenUIErrorBoundary code={code}>
      <div className="my-1">
        <OpenUIRendererInner code={code} isStreaming={isStreaming} />
      </div>
    </OpenUIErrorBoundary>
  );
}
