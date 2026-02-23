/**
 * Shared command handlers for all bot platforms.
 *
 * Each handler: calls GaiaClient -> formats the result -> returns a string.
 * Bot adapters become thin wrappers: extract platform args -> call handler -> reply.
 *
 * All handlers catch errors via formatBotError, so bot code doesn't need
 * its own try/catch for API failures. The returned string is always safe
 * to send directly to the user.
 *
 * To add a new command:
 * 1. Add the API method to GaiaClient (api/index.ts)
 * 2. Add a formatter if needed (formatters.ts)
 * 3. Add a handler here following the same pattern
 * 4. Import and call it from each bot's command adapter
 */
import type { GaiaClient } from "../api";
import type { CommandContext } from "../types";
import {
  COMMAND_HELP,
  formatBotError,
  formatConversationList,
  formatTodo,
  formatTodoList,
  formatWorkflow,
  formatWorkflowList,
} from "./formatters";

export async function handleWorkflowList(
  gaia: GaiaClient,
  ctx: CommandContext,
): Promise<string> {
  try {
    const response = await gaia.listWorkflows(ctx);
    return formatWorkflowList(response.workflows);
  } catch (error: unknown) {
    return formatBotError(error);
  }
}

export async function handleWorkflowExecute(
  gaia: GaiaClient,
  workflowId: string,
  ctx: CommandContext,
  inputs?: Record<string, unknown>,
): Promise<string> {
  try {
    const response = await gaia.executeWorkflow(
      { workflow_id: workflowId, inputs },
      ctx,
    );
    return `✅ Workflow execution started!\nExecution ID: ${response.execution_id}\nStatus: ${response.status}`;
  } catch (error: unknown) {
    return formatBotError(error);
  }
}

export async function handleTodoList(
  gaia: GaiaClient,
  ctx: CommandContext,
  completed?: boolean,
): Promise<string> {
  try {
    const response = await gaia.listTodos(ctx, { completed });
    return formatTodoList(response.todos);
  } catch (error: unknown) {
    return formatBotError(error);
  }
}

export async function handleTodoCreate(
  gaia: GaiaClient,
  title: string,
  ctx: CommandContext,
  options?: { priority?: "low" | "medium" | "high"; description?: string },
): Promise<string> {
  try {
    const todo = await gaia.createTodo(
      {
        title,
        priority: options?.priority,
        description: options?.description,
      },
      ctx,
    );
    return `✅ Todo created!\n\n${formatTodo(todo)}`;
  } catch (error: unknown) {
    return formatBotError(error);
  }
}

export async function handleTodoComplete(
  gaia: GaiaClient,
  todoId: string,
  ctx: CommandContext,
): Promise<string> {
  try {
    const todo = await gaia.completeTodo(todoId, ctx);
    return `✅ Todo marked as complete: ${todo.title}`;
  } catch (error: unknown) {
    return formatBotError(error);
  }
}

export async function handleConversationList(
  gaia: GaiaClient,
  ctx: CommandContext,
  page = 1,
): Promise<string> {
  try {
    const response = await gaia.listConversations(ctx, { page, limit: 5 });
    return formatConversationList(
      response.conversations,
      gaia.getFrontendUrl(),
    );
  } catch (error: unknown) {
    return formatBotError(error);
  }
}

export async function handleWorkflowGet(
  gaia: GaiaClient,
  workflowId: string,
  ctx: CommandContext,
): Promise<string> {
  try {
    const response = await gaia.getWorkflow(workflowId, ctx);
    return formatWorkflow(response);
  } catch (error: unknown) {
    return formatBotError(error);
  }
}

export async function handleWorkflowCreate(
  gaia: GaiaClient,
  name: string,
  ctx: CommandContext,
  description?: string,
): Promise<string> {
  try {
    const workflow = await gaia.createWorkflow(
      { name, description: description || "" },
      ctx,
    );
    return `✅ Workflow created!\n\n${formatWorkflow(workflow)}`;
  } catch (error: unknown) {
    return formatBotError(error);
  }
}

export async function handleTodoDelete(
  gaia: GaiaClient,
  todoId: string,
  ctx: CommandContext,
): Promise<string> {
  try {
    await gaia.deleteTodo(todoId, ctx);
    return "✅ Todo deleted successfully";
  } catch (error: unknown) {
    return formatBotError(error);
  }
}

export async function dispatchTodoSubcommand(
  gaia: GaiaClient,
  ctx: CommandContext,
  subcommand: string,
  args: string[],
): Promise<string> {
  switch (subcommand) {
    case "list":
      return handleTodoList(gaia, ctx);
    case "add": {
      const title = args.join(" ");
      if (!title) return COMMAND_HELP.todoUsage.add;
      return handleTodoCreate(gaia, title, ctx);
    }
    case "complete": {
      if (!args[0]) return COMMAND_HELP.todoUsage.complete;
      return handleTodoComplete(gaia, args[0], ctx);
    }
    case "delete": {
      if (!args[0]) return COMMAND_HELP.todoUsage.delete;
      return handleTodoDelete(gaia, args[0], ctx);
    }
    default:
      return COMMAND_HELP.todo;
  }
}

export async function handleWorkflowDelete(
  gaia: GaiaClient,
  workflowId: string,
  ctx: CommandContext,
): Promise<string> {
  try {
    await gaia.deleteWorkflow(workflowId, ctx);
    return "✅ Workflow deleted successfully";
  } catch (error: unknown) {
    return formatBotError(error);
  }
}

export async function dispatchWorkflowSubcommand(
  gaia: GaiaClient,
  ctx: CommandContext,
  subcommand: string,
  args: string[],
): Promise<string> {
  switch (subcommand) {
    case "list":
      return handleWorkflowList(gaia, ctx);
    case "get": {
      if (!args[0]) return COMMAND_HELP.workflowUsage.get;
      return handleWorkflowGet(gaia, args[0], ctx);
    }
    case "execute": {
      if (!args[0]) return COMMAND_HELP.workflowUsage.execute;
      return handleWorkflowExecute(gaia, args[0], ctx);
    }
    case "delete": {
      if (!args[0]) return COMMAND_HELP.workflowUsage.delete;
      return handleWorkflowDelete(gaia, args[0], ctx);
    }
    default:
      return COMMAND_HELP.workflow;
  }
}

/**
 * Starts a new conversation for the user.
 *
 * Resets the bot session, creating a fresh conversation context while
 * preserving the previous conversation (accessible from web app).
 *
 * **Use case**: Users can start fresh when conversation context becomes too
 * long or when switching to a completely different topic.
 *
 * @param gaia - GaiaClient instance
 * @param ctx - Command context (platform, user ID, channel)
 * @returns Success message explaining that previous conversation is saved
 */
export async function handleNewConversation(
  gaia: GaiaClient,
  ctx: CommandContext,
): Promise<string> {
  try {
    await gaia.resetSession(ctx.platform, ctx.platformUserId, ctx.channelId);
    return "Started a new conversation. Your previous conversation is saved and accessible from the GAIA web app.";
  } catch (_error: unknown) {
    return "Failed to start a new conversation. Please try again.";
  }
}
