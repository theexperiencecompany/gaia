import {
  type ActionEvent,
  type ParseResult,
  Renderer,
} from "@openuidev/react-lang";
import React from "react";
import { genericLibrary } from "@/config/openui/genericLibrary";
import { dispatchOpenUIAction } from "@/features/chat/actions/openUIActionDispatcher";
import { useAppendToInput } from "@/stores/composerStore";

interface OpenUIRendererProps {
  code: string;
  isStreaming: boolean;
}

function OpenUIRendererInner({ code, isStreaming }: OpenUIRendererProps) {
  const appendToInput = useAppendToInput();
  // Track whether the last parse produced a renderable root.
  // Used to show a fallback when parsing silently fails post-streaming.
  const [parseFailed, setParseFailed] = React.useState(false);

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
      const failed = result.root === null;
      if (failed && !isStreaming) {
        console.error(
          "[OpenUIRenderer] Parse produced no root — component will not render.",
          {
            code,
            validationErrors: result.meta?.validationErrors,
            unresolved: result.meta?.unresolved,
            statementCount: result.meta?.statementCount,
          },
        );
      }
      setParseFailed(failed && !isStreaming);
    },
    [code, isStreaming],
  );

  // When the code or streaming state changes, reset the failure flag so
  // a stale fallback doesn't linger while the new parse is in-flight.
  React.useEffect(() => {
    setParseFailed(false);
  }, [code, isStreaming]);

  if (parseFailed) {
    return (
      <pre className="rounded-xl bg-zinc-900 p-3 text-xs text-zinc-500 whitespace-pre-wrap overflow-x-auto max-w-xl">
        {code}
      </pre>
    );
  }

  return (
    <Renderer
      response={code}
      library={genericLibrary}
      isStreaming={isStreaming}
      onAction={handleAction}
      onParseResult={handleParseResult}
    />
  );
}

class OpenUIErrorBoundary extends React.Component<
  { children: React.ReactNode; fallbackText: string },
  { hasError: boolean }
> {
  constructor(props: { children: React.ReactNode; fallbackText: string }) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidUpdate(prevProps: { fallbackText: string }) {
    if (
      this.state.hasError &&
      prevProps.fallbackText !== this.props.fallbackText
    ) {
      this.setState({ hasError: false });
    }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("[OpenUIRenderer] Render error:", error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <pre className="rounded-xl bg-zinc-900 p-3 text-xs text-zinc-500 whitespace-pre-wrap overflow-x-auto max-w-xl">
          {this.props.fallbackText}
        </pre>
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
    <OpenUIErrorBoundary fallbackText={code}>
      <OpenUIRendererInner code={code} isStreaming={isStreaming} />
    </OpenUIErrorBoundary>
  );
}
