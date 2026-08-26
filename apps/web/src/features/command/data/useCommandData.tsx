"use client";

import {
  Brain02Icon,
  CheckmarkCircle02Icon,
  ConnectIcon,
  MessageMultiple02Icon,
  NotificationIcon,
  Settings01Icon,
  ZapIcon,
} from "@icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo } from "react";
import { useKeyboardShortcuts } from "@/components/providers/KeyboardShortcutsProvider";
import { getLinkByLabel } from "@/config/appConfig";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { useLogout } from "@/features/auth/hooks/useLogout";
import { useChatActions } from "@/features/chat/hooks/useChatActions";
import { useConversationList } from "@/features/chat/hooks/useConversationList";
import { prepareNewChat } from "@/features/chat/utils/newChatNavigation";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { memoryApi } from "@/features/memory/api/memoryApi";
import { useNotifications } from "@/features/notification/hooks/useNotifications";
import { useUserSubscriptionStatus } from "@/features/pricing/hooks/usePricing";
import type { SearchConversationResult } from "@/features/search/api/searchApi";
import { useWorkflowActions } from "@/features/workflows/hooks/useWorkflowActions";
import { useWorkflows } from "@/features/workflows/hooks/useWorkflows";
import { useComposerStore } from "@/stores/composerStore";
import { usePricingModalStore } from "@/stores/pricingModalStore";
import { useTodoStore } from "@/stores/todoStore";
import { ICON } from "../model/constants";
import type {
  BuildCtx,
  CommandGroup,
  CommandHost,
  CommandItem,
} from "../model/types";
import {
  type ChatLike,
  makeChatItem,
  makeMessageItem,
} from "../providers/chats";
import { buildCommandGroups } from "../providers/commands";
import { buildIntegrationItems } from "../providers/integrations";
import { buildMemoryItems } from "../providers/memories";
import { buildNotificationItems } from "../providers/notifications";
import { buildSettingsItems } from "../providers/settings";
import { buildTodoItems } from "../providers/todos";
import { buildWorkflowItems } from "../providers/workflows";

// Keyed to the user so cached memories never leak across sessions.
const memoriesQueryKey = (userEmail: string) =>
  ["command-k", "memories", userEmail] as const;
const RECENT_COUNT = 3;

const ms = (date?: string | null) => (date ? new Date(date).getTime() : 0);

export interface CommandData {
  groups: CommandGroup[];
  recent: CommandItem[];
  context: { heading: string; item: CommandItem } | null;
  buildSearchChat: (result: SearchConversationResult) => CommandItem;
  buildSearchMessage: (result: {
    conversation_id: string;
    message: { message_id: string };
    snippet: string;
  }) => CommandItem;
  askGaia: (query: string) => void;
}

/** Orchestrates live app data into normalized command groups via per-entity builders. */
export function useCommandData(host: CommandHost): CommandData {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { isAuthenticated, userEmail } = useAuth();
  const queryClient = useQueryClient();

  const { conversations } = useConversationList();
  const chatActions = useChatActions();
  const workflowActions = useWorkflowActions();
  const { workflows } = useWorkflows();
  const { integrations, connectIntegration, disconnectIntegration } =
    useIntegrations();
  const todos = useTodoStore((s) => s.todos);
  const loadTodos = useTodoStore((s) => s.loadTodos);
  const updateTodo = useTodoStore((s) => s.updateTodo);
  const deleteTodo = useTodoStore((s) => s.deleteTodo);
  const { notifications, markAsRead, archiveNotification } = useNotifications();
  const { data: subscriptionStatus } = useUserSubscriptionStatus();
  const openPricing = usePricingModalStore((s) => s.openModal);
  const { openShortcutsModal } = useKeyboardShortcuts();
  const { logout } = useLogout();
  const { data: memoryList } = useQuery({
    queryKey: memoriesQueryKey(userEmail),
    queryFn: () => memoryApi.listMemories({ pageSize: 50 }),
    enabled: isAuthenticated,
    staleTime: 60_000,
  });

  useEffect(() => {
    if (isAuthenticated) loadTodos();
  }, [isAuthenticated, loadTodos]);

  const ctx = useMemo<BuildCtx>(
    () => ({
      host,
      navigate: (path: string) => () => {
        router.push(path);
        host.close();
      },
    }),
    [host, router],
  );

  // ── Per-entity item arrays (reused for groups + recent + search) ───────
  const chats = useMemo(() => {
    const sorted = [...(conversations as ChatLike[])].sort((a, b) => {
      const unread = (b.is_unread ? 1 : 0) - (a.is_unread ? 1 : 0);
      if (unread !== 0) return unread;
      return (b.updatedAt?.getTime() ?? 0) - (a.updatedAt?.getTime() ?? 0);
    });
    const byConv = new Map<string, CommandItem>();
    const items = sorted.map((c) => {
      const item = makeChatItem(c, ctx, chatActions);
      byConv.set(c.conversation_id, item);
      return item;
    });
    return { items, byConv };
  }, [conversations, ctx, chatActions]);

  const workflowItems = useMemo(
    () => buildWorkflowItems(workflows, ctx, workflowActions),
    [workflows, ctx, workflowActions],
  );
  const integrationItems = useMemo(
    () =>
      buildIntegrationItems(integrations, ctx, {
        connectIntegration,
        disconnectIntegration,
      }),
    [integrations, ctx, connectIntegration, disconnectIntegration],
  );
  const todoItems = useMemo(
    () => buildTodoItems(todos, ctx, { updateTodo, deleteTodo }),
    [todos, ctx, updateTodo, deleteTodo],
  );
  const notificationItems = useMemo(
    () =>
      buildNotificationItems(notifications, ctx, {
        markAsRead,
        archiveNotification,
      }),
    [notifications, ctx, markAsRead, archiveNotification],
  );
  const memoryItems = useMemo(
    () =>
      buildMemoryItems(memoryList?.memories ?? [], ctx, {
        refetch: () =>
          queryClient.invalidateQueries({
            queryKey: memoriesQueryKey(userEmail),
          }),
      }),
    [memoryList, ctx, queryClient, userEmail],
  );
  const settingsItems = useMemo(() => buildSettingsItems(ctx), [ctx]);

  const groups = useMemo<CommandGroup[]>(() => {
    const entity = (
      id: string,
      heading: string,
      icon: CommandGroup["icon"],
      accent: string,
      path: string,
      items: CommandItem[],
    ): CommandGroup => ({
      id,
      heading,
      icon,
      accent,
      kind: "entity",
      path,
      items,
    });

    // Static commands (New chat, Upgrade, Community, Resources, Account).
    const [quickActions, ...secondaryCommands] = buildCommandGroups(ctx, {
      isSubscribed: Boolean(subscriptionStatus?.is_subscribed),
      openPricing,
      openShortcuts: openShortcutsModal,
      logout: async () => {
        const ok = await host.confirm({
          title: "Sign out",
          message: "Are you sure you want to sign out?",
          confirmText: "Sign out",
          variant: "destructive",
        });
        if (!ok) return;
        host.close();
        await logout();
      },
      links: {
        discord: getLinkByLabel("Discord")?.href,
        whatsapp: getLinkByLabel("WhatsApp")?.href,
        docs: getLinkByLabel("Documentation")?.href,
        github: getLinkByLabel("GitHub")?.href,
      },
    });

    const entityGroups = [
      entity(
        "chats",
        "Chats",
        <MessageMultiple02Icon {...ICON} />,
        "text-sky-400",
        "/c",
        chats.items,
      ),
      entity(
        "workflows",
        "Workflows",
        <ZapIcon {...ICON} />,
        "text-amber-400",
        "/workflows",
        workflowItems,
      ),
      entity(
        "integrations",
        "Integrations",
        <ConnectIcon {...ICON} />,
        "text-violet-400",
        "/integrations",
        integrationItems,
      ),
      entity(
        "todos",
        "Todos",
        <CheckmarkCircle02Icon {...ICON} />,
        "text-green-400",
        "/todos",
        todoItems,
      ),
      entity(
        "notifications",
        "Notifications",
        <NotificationIcon {...ICON} />,
        "text-orange-400",
        "/notifications",
        notificationItems,
      ),
      entity(
        "memories",
        "Memories",
        <Brain02Icon {...ICON} />,
        "text-fuchsia-400",
        "/settings/memory",
        memoryItems,
      ),
      entity(
        "settings",
        "Settings",
        <Settings01Icon {...ICON} />,
        "text-zinc-400",
        "/settings",
        settingsItems,
      ),
    ];

    // Order: Quick actions → entity categories (Browse) → secondary command groups.
    // Entity categories always show as browsable sections (even when empty / not
    // yet fetched) so Workflows/Integrations/Todos are always reachable; only
    // empty command groups are dropped.
    return [quickActions, ...entityGroups, ...secondaryCommands].filter(
      (group) => group.kind === "entity" || group.items.length > 0,
    );
  }, [
    chats.items,
    workflowItems,
    integrationItems,
    todoItems,
    notificationItems,
    memoryItems,
    settingsItems,
    ctx,
    host,
    subscriptionStatus,
    openPricing,
    openShortcutsModal,
    logout,
  ]);

  // Recent across all types, newest first.
  const recent = useMemo<CommandItem[]>(() => {
    const candidates: { item: CommandItem; ts: number }[] = [];
    (conversations as ChatLike[]).forEach((c) => {
      const item = chats.byConv.get(c.conversation_id);
      if (item) candidates.push({ item, ts: c.updatedAt?.getTime() ?? 0 });
    });
    workflows.forEach((w, i) => {
      const item = workflowItems[i];
      if (item)
        candidates.push({ item, ts: ms(w.last_executed_at || w.updated_at) });
    });
    todos.forEach((t, i) => {
      const item = todoItems[i];
      if (item) candidates.push({ item, ts: ms(t.updated_at) });
    });
    notifications.forEach((n, i) => {
      const item = notificationItems[i];
      if (item) candidates.push({ item, ts: ms(n.created_at) });
    });
    return candidates
      .filter((c) => c.ts > 0)
      .sort((a, b) => b.ts - a.ts)
      .slice(0, RECENT_COUNT)
      .map((c) => c.item);
  }, [
    conversations,
    workflows,
    todos,
    notifications,
    chats.byConv,
    workflowItems,
    todoItems,
    notificationItems,
  ]);

  const context = useMemo(() => {
    const itemById = (id: string) =>
      groups.flatMap((g) => g.items).find((i) => i.id === id);
    const chatMatch = pathname.match(/\/c\/([^/?]+)/);
    if (chatMatch) {
      const item = itemById(`chat:${chatMatch[1]}`);
      if (item) return { heading: "Current chat", item };
    }
    if (pathname.includes("/workflows")) {
      const id = searchParams.get("id");
      const item = id ? itemById(`workflow:${id}`) : undefined;
      if (item) return { heading: "Current workflow", item };
    }
    if (pathname.includes("/integrations")) {
      const id = searchParams.get("id");
      const item = id ? itemById(`integration:${id}`) : undefined;
      if (item) return { heading: "Current integration", item };
    }
    return null;
  }, [groups, pathname, searchParams]);

  const buildSearchChat = (result: SearchConversationResult): CommandItem =>
    chats.byConv.get(result.conversation_id) ??
    makeChatItem(
      { conversation_id: result.conversation_id, title: result.description },
      ctx,
      chatActions,
      false,
    );

  const buildSearchMessage = (result: {
    conversation_id: string;
    message: { message_id: string };
    snippet: string;
  }): CommandItem =>
    makeMessageItem(
      {
        conversation_id: result.conversation_id,
        message_id: result.message.message_id,
        snippet: result.snippet,
      },
      ctx,
    );

  const askGaia = useCallback(
    (query: string) => {
      prepareNewChat();
      useComposerStore.getState().appendToInput(query);
      router.push("/c");
      host.close();
    },
    [router, host],
  );

  return {
    groups,
    recent,
    context,
    buildSearchChat,
    buildSearchMessage,
    askGaia,
  };
}
