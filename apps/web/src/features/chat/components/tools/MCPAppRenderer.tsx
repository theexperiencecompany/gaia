"use client";

import { AppBridge, AppFrame, type McpUiHostContext } from "@mcp-ui/client";
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { MCPAppData } from "@/config/registries/toolRegistry";
import {
  callMCPAppTool,
  listMCPPrompts,
  listMCPResources,
  listMCPResourceTemplates,
  readMCPResource,
} from "@/features/chat/api/mcpProxyApi";
import { useSendMessage } from "@/hooks/useSendMessage";

type DisplayMode = "inline" | "fullscreen";

const HOST_CAPABILITIES = {
  openLinks: {},
  serverTools: {},
  serverResources: {},
  serverPrompts: {},
  logging: {},
} as const;

const HOST_INFO = { name: "GAIA", version: "1.0.0" } as const;

const AVAILABLE_MODES: DisplayMode[] = ["inline", "fullscreen"];

function getTheme(): "dark" | "light" {
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

interface Props {
  data: MCPAppData;
}

export function MCPAppRenderer({ data }: Props) {
  const [appHeight, setAppHeight] = useState(500);
  const [displayMode, setDisplayMode] = useState<DisplayMode>("inline");
  const [bridge, setBridge] = useState<AppBridge | null>(null);
  const bridgeRef = useRef<AppBridge | null>(null);

  const dataRef = useRef(data);
  const sendMessage = useSendMessage();
  const sendMessageRef = useRef(sendMessage);

  useEffect(() => {
    dataRef.current = data;
  });
  useEffect(() => {
    sendMessageRef.current = sendMessage;
  });

  const sandboxUrl = useMemo(
    () => new URL("/mcp-sandbox-proxy.html", window.location.origin),
    [],
  );

  const hasCsp = data.csp !== undefined;
  const cspKey = useMemo(() => JSON.stringify(data.csp ?? null), [data.csp]);
  const stableCsp = useMemo((): MCPAppData["csp"] | undefined => {
    if (!hasCsp) return undefined;
    return JSON.parse(cspKey) as MCPAppData["csp"];
  }, [cspKey, hasCsp]);

  const sandbox = useMemo(
    () => ({ url: sandboxUrl, csp: stableCsp }),
    [sandboxUrl, stableCsp],
  );

  useEffect(() => {
    const initialContext: McpUiHostContext = {
      platform: "web",
      theme: getTheme(),
      locale: navigator.language,
      timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      displayMode: "inline",
      availableDisplayModes: AVAILABLE_MODES,
    };

    const b = new AppBridge(null, HOST_INFO, HOST_CAPABILITIES, {
      hostContext: initialContext,
    });

    b.oncalltool = async (params) => {
      try {
        const result = await callMCPAppTool(
          dataRef.current.server_url,
          params.name,
          params.arguments ?? {},
        );
        const content = result.content.map((item) => {
          if (item && typeof item === "object") {
            const c = { ...(item as Record<string, unknown>) };
            if (c.annotations == null) delete c.annotations;
            return c;
          }
          return item;
        });
        return { content, isError: result.is_error ?? false } as Awaited<
          ReturnType<NonNullable<typeof b.oncalltool>>
        >;
      } catch (err) {
        const message = err instanceof Error ? err.message : "Tool call failed";
        return {
          content: [{ type: "text" as const, text: message }],
          isError: true,
        } as Awaited<ReturnType<NonNullable<typeof b.oncalltool>>>;
      }
    };

    b.onopenlink = async ({ url }) => {
      const a = document.createElement("a");
      a.href = url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      return {};
    };

    b.onmessage = async (params) => {
      const text = params.content
        .filter((c) => c.type === "text" && "text" in c)
        .map((c) => ("text" in c ? String(c.text) : ""))
        .join(" ")
        .trim();
      if (text) await sendMessageRef.current(text);
      return {};
    };

    b.onlistresources = async (params) => {
      try {
        const r = await listMCPResources(
          dataRef.current.server_url,
          params?.cursor as string | undefined,
        );
        return { resources: r.resources, nextCursor: r.next_cursor };
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Failed to list resources";
        throw Object.assign(new Error(message), { code: -32_603 });
      }
    };

    b.onlistresourcetemplates = async (params) => {
      try {
        const r = await listMCPResourceTemplates(
          dataRef.current.server_url,
          params?.cursor as string | undefined,
        );
        return {
          resourceTemplates: r.resource_templates,
          nextCursor: r.next_cursor,
        };
      } catch (err) {
        const message =
          err instanceof Error
            ? err.message
            : "Failed to list resource templates";
        throw Object.assign(new Error(message), { code: -32_603 });
      }
    };

    b.onreadresource = async (params, _extra) => {
      try {
        const r = await readMCPResource(dataRef.current.server_url, params.uri);
        const contents = r.contents.flatMap(
          (
            item,
          ): (
            | { uri: string; text: string; mimeType?: string }
            | { uri: string; blob: string; mimeType?: string }
          )[] => {
            const base = { uri: item.uri, mimeType: item.mimeType };
            if (item.text !== undefined) return [{ ...base, text: item.text }];
            if (item.blob !== undefined) return [{ ...base, blob: item.blob }];
            return [];
          },
        );
        return { contents };
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Failed to read resource";
        throw Object.assign(new Error(message), { code: -32_603 });
      }
    };

    b.onlistprompts = async (params) => {
      try {
        const r = await listMCPPrompts(
          dataRef.current.server_url,
          params?.cursor as string | undefined,
        );
        return { prompts: r.prompts, nextCursor: r.next_cursor };
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Failed to list prompts";
        throw Object.assign(new Error(message), { code: -32_603 });
      }
    };

    b.onrequestdisplaymode = async ({ mode }) => {
      const granted = (
        AVAILABLE_MODES.includes(mode as DisplayMode) ? mode : "inline"
      ) as DisplayMode;
      setDisplayMode(granted);
      b.setHostContext({
        displayMode: granted,
        availableDisplayModes: AVAILABLE_MODES,
      });
      return { mode: granted };
    };

    b.onloggingmessage = ({ level, data: logData }) => {
      if (typeof logData === "string") {
        try {
          const url = new URL(logData.trim());
          if (url.protocol === "https:" || url.protocol === "http:") {
            const a = document.createElement("a");
            a.href = url.href;
            a.target = "_blank";
            a.rel = "noopener noreferrer";
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            return;
          }
        } catch {
          // not a URL
        }
      }
      if (["error", "critical", "alert", "emergency"].includes(level)) {
        console.error("[MCPApp]", logData);
      } else if (level === "warning") {
        console.warn("[MCPApp]", logData);
      } else {
        console.info("[MCPApp]", logData);
      }
    };

    b.fallbackRequestHandler = async (request) => {
      const err = new Error(`Method not supported by host: ${request.method}`);
      (err as unknown as { code: number }).code = -32_601;
      throw err;
    };

    bridgeRef.current = b;
    setBridge(b);

    return () => {
      // Protocol requires teardownResource before closing so the guest
      // can save state. We give it 500ms then force-close regardless.
      const timeout = setTimeout(() => b.close(), 500);
      b.teardownResource({})
        .catch(() => {})
        .finally(() => {
          clearTimeout(timeout);
          b.close();
        });
      bridgeRef.current = null;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Escape to exit fullscreen
  useEffect(() => {
    if (displayMode !== "fullscreen") return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDisplayMode("inline");
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [displayMode]);

  // Observe the container and forward dimensions to the guest via hostContext
  const observeContainer = useCallback(
    (node: HTMLDivElement | null) => {
      if (!node || !bridge) return;
      const observer = new ResizeObserver((entries) => {
        const rect = entries[0]?.contentRect;
        if (!rect) return;
        bridgeRef.current?.setHostContext({
          containerDimensions: {
            width: Math.round(rect.width),
            height: Math.round(rect.height),
          },
        });
      });
      observer.observe(node);
      // Initial dimensions
      const rect = node.getBoundingClientRect();
      bridge.setHostContext({
        containerDimensions: {
          width: Math.round(rect.width),
          height: Math.round(rect.height),
        },
      });
      return () => observer.disconnect();
    },
    [bridge],
  );

  const toolInput = useMemo(
    () => data.tool_arguments ?? {},
    [data.tool_arguments],
  );

  const toolResult = useMemo((): CallToolResult | undefined => {
    if (data.tool_result == null) return undefined;

    if (
      typeof data.tool_result === "object" &&
      !Array.isArray(data.tool_result)
    ) {
      const r = data.tool_result as Record<string, unknown>;
      if (Array.isArray(r.content)) {
        return data.tool_result as CallToolResult;
      }
    }

    if (Array.isArray(data.tool_result)) {
      return { content: data.tool_result as CallToolResult["content"] };
    }

    if (typeof data.tool_result === "string") {
      return { content: [{ type: "text" as const, text: data.tool_result }] };
    }

    return {
      content: [{ type: "text" as const, text: String(data.tool_result) }],
    };
  }, [data.tool_result]);

  const handleSizeChanged = useCallback(
    (params: { width?: number; height?: number }) => {
      const h = Number(params.height);
      if (Number.isFinite(h) && h > 0) setAppHeight(Math.ceil(h));
    },
    [],
  );

  if (!bridge) return null;

  const frame = (
    <AppFrame
      html={data.html_content}
      sandbox={sandbox}
      appBridge={bridge}
      toolInput={toolInput}
      toolResult={toolResult}
      onSizeChanged={handleSizeChanged}
      onError={(e) => console.error("[MCPAppRenderer]", data.tool_name, e)}
    />
  );

  if (displayMode === "fullscreen") {
    return (
      <div ref={observeContainer} className="fixed inset-0 z-50 bg-background">
        {frame}
      </div>
    );
  }

  return (
    <div
      ref={observeContainer}
      className="rounded-2xl overflow-hidden border border-default-200 my-2 max-w-2xl"
      style={{ width: "100%", height: `${appHeight}px` }}
    >
      {frame}
    </div>
  );
}
