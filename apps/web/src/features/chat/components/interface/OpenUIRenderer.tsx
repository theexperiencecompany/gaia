import { type ActionEvent, Renderer } from "@openuidev/react-lang";
import React from "react";
import { gaiaLibrary } from "@/config/openui/gaiaLibrary";

interface OpenUIRendererProps {
  code: string;
  isStreaming: boolean;
}

function OpenUIRendererInner({ code, isStreaming }: OpenUIRendererProps) {
  const handleAction = React.useCallback((event: ActionEvent) => {
    if (event.type === "continue_conversation" && event.humanFriendlyMessage) {
      // TODO: integrate with chat input to send follow-up messages
      console.error(
        "[OpenUIRenderer] continue_conversation action not yet wired:",
        event.humanFriendlyMessage,
      );
    }
  }, []);

  return (
    <Renderer
      response={code}
      library={gaiaLibrary}
      isStreaming={isStreaming}
      onAction={handleAction}
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

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("[OpenUIRenderer] Render error:", error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <pre className="whitespace-pre-wrap text-sm text-zinc-400">
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
