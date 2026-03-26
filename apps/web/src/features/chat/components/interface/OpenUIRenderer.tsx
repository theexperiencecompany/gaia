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

function OpenUIRendererInner({ code, isStreaming }: OpenUIRendererProps) {
  const appendToInput = useAppendToInput();
  // Normalize named args (key=value) to positional before the parser sees them.
  // The @openuidev/react-lang parser only understands positional arguments.
  const normalizedCode = React.useMemo(
    () => normalizeOpenUICode(code, genericLibrary),
    [code],
  );
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
            rawCode: code,
            normalizedCode,
            validationErrors: result.meta?.validationErrors,
            unresolved: result.meta?.unresolved,
            statementCount: result.meta?.statementCount,
          },
        );
      }
      setParseFailed(failed && !isStreaming);
    },
    [code, normalizedCode, isStreaming],
  );

  // When the code or streaming state changes, reset the failure flag so
  // a stale fallback doesn't linger while the new parse is in-flight.
  React.useEffect(() => {
    setParseFailed(false);
  }, [code, isStreaming]);

  if (parseFailed) {
    return null;
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
  { hasError: boolean; errorCode: string }
> {
  constructor(props: { children: React.ReactNode; code: string }) {
    super(props);
    this.state = { hasError: false, errorCode: "" };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidUpdate(prevProps: { code: string }) {
    if (this.state.hasError && prevProps.code !== this.props.code) {
      this.setState({ hasError: false, errorCode: "" });
    }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("[OpenUIRenderer] Render error:", error, info, {
      code: this.props.code,
    });
  }

  render() {
    if (this.state.hasError) {
      return null;
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
      <OpenUIRendererInner code={code} isStreaming={isStreaming} />
    </OpenUIErrorBoundary>
  );
}
