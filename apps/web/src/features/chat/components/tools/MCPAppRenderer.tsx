"use client";

import {
  AppRenderer,
  type AppRendererHandle,
  type AppRendererProps,
} from "@mcp-ui/client";
import { useCallback, useMemo, useRef } from "react";
import type { MCPAppData } from "@/config/registries/toolRegistry";
import { callMCPAppTool } from "@/features/chat/api/mcpProxyApi";

type OnCallTool = NonNullable<AppRendererProps["onCallTool"]>;
type OnOpenLink = NonNullable<AppRendererProps["onOpenLink"]>;

interface Props {
  data: MCPAppData;
}

export function MCPAppRenderer({ data }: Props) {
  const appRef = useRef<AppRendererHandle>(null);

  const sandbox = useMemo(
    () => ({ url: new URL("/mcp-sandbox-proxy.html", window.location.origin) }),
    [],
  );

  const onCallTool: OnCallTool = useCallback(
    async (params) => {
      const result = await callMCPAppTool(
        data.server_url,
        params.name,
        params.arguments ?? {},
      );
      return {
        content: result.content,
        isError: result.is_error ?? false,
      } as Awaited<ReturnType<OnCallTool>>;
    },
    [data.server_url],
  );

  const onOpenLink: OnOpenLink = useCallback(async ({ url }) => {
    window.open(url, "_blank", "noopener,noreferrer");
    return {};
  }, []);

  const toolResult = useMemo((): AppRendererProps["toolResult"] => {
    if (!data.tool_result) return undefined;
    const content =
      typeof data.tool_result === "string"
        ? [{ type: "text" as const, text: data.tool_result }]
        : (data.tool_result as AppRendererProps["toolResult"] extends
            | { content: infer C }
            | undefined
            ? C
            : never);
    return { content } as AppRendererProps["toolResult"];
  }, [data.tool_result]);

  return (
    <div className="mcp-app-container max-w-2xl rounded-lg overflow-hidden border border-default-200 my-2 h-[600px]">
      <AppRenderer
        ref={appRef}
        html={data.html_content}
        toolName={data.tool_name}
        sandbox={sandbox}
        toolInput={{}}
        toolResult={toolResult}
        onCallTool={onCallTool}
        onOpenLink={onOpenLink}
        onError={(e) => console.error("[MCPAppRenderer]", data.tool_name, e)}
      />
    </div>
  );
}
