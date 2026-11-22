/**
 * Shared command handlers for all bot platforms.
 *
 * Each handler: calls GaiaClient -> formats the result -> returns a string.
 * Bot adapters become thin wrappers: extract platform args -> call handler -> reply.
 *
 * All handlers catch API failures through reportCommandFailure, which records
 * the failure on the command's wide event and returns the user-facing text,
 * so bot code doesn't need its own try/catch. The returned string is always
 * safe to send directly to the user.
 *
 * To add a new command:
 * 1. Add the API method to GaiaClient (api/index.ts)
 * 2. Add a formatter if needed (formatters.ts)
 * 3. Add a handler here following the same pattern
 * 4. Import and call it from each bot's command adapter
 */
import type { TaskCreateRequest } from "../../api/generated";
import type { GaiaClient } from "../api";
import type { CommandContext } from "../types";
import { recordBotFailure } from "./failure-reasons";
import {
  COMMAND_HELP,
  formatBotError,
  formatConversationList,
  formatTask,
  formatTaskList,
  formatWorkflow,
  formatWorkflowList,
} from "./formatters";

/**
 * Records a command's caught API failure on its wide event (reason, HTTP status,
 * API error code) and returns the reply for the user.
 */
export function reportCommandFailure(
  operation: string,
  error: unknown,
  ctx: CommandContext,
): string {
  recordBotFailure(`${operation}_failed`, error, { operation });
  return formatBotError(error, ctx.platform);
}

export async function handleWorkflowList(
  gaia: GaiaClient,
  ctx: CommandContext,
): Promise<string> {
  try {
    const response = await gaia.listWorkflows(ctx);
    return formatWorkflowList(response.workflows);
  } catch (error: unknown) {
    return reportCommandFailure("list_workflows", error, ctx);
  }
}

export async function handleWorkflowExecute(
  gaia: GaiaClient,
  workflowId: string,
  ctx: CommandContext,
): Promise<string> {
  try {
    const response = await gaia.executeWorkflow(workflowId, ctx);
    return `✅ Workflow execution started!\nExecution ID: ${response.execution_id}`;
  } catch (error: unknown) {
    return reportCommandFailure("execute_workflow", error, ctx);
  }
}

export async function handleTaskList(
  gaia: GaiaClient,
  ctx: CommandContext,
  completed?: boolean,
): Promise<string> {
  try {
    const response = await gaia.listTasks(ctx, { completed });
    return formatTaskList(response.tasks);
  } catch (error: unknown) {
    return reportCommandFailure("list_tasks", error, ctx);
  }
}

export async function handleTaskCreate(
  gaia: GaiaClient,
  title: string,
  ctx: CommandContext,
  options?: Pick<TaskCreateRequest, "priority" | "body">,
): Promise<string> {
  try {
    const task = await gaia.createTask({ title, ...options }, ctx);
    return `✅ Todo created!\n\n${formatTask(task)}`;
  } catch (error: unknown) {
    return reportCommandFailure("create_task", error, ctx);
  }
}

export async function handleTaskComplete(
  gaia: GaiaClient,
  taskId: string,
  ctx: CommandContext,
): Promise<string> {
  try {
    const task = await gaia.completeTask(taskId, ctx);
    return `✅ Todo marked as complete: ${task.title}`;
  } catch (error: unknown) {
    return reportCommandFailure("complete_task", error, ctx);
  }
}

export async function handleConversationList(
  gaia: GaiaClient,
  ctx: CommandContext,
  page = 1,
): Promise<string> {
  try {
    const response = await gaia.listConversations(ctx, { page, limit: 5 });
    return formatConversationList(response.conversations);
  } catch (error: unknown) {
    return reportCommandFailure("list_conversations", error, ctx);
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
    return reportCommandFailure("get_workflow", error, ctx);
  }
}

/** Creates a workflow the user runs on demand; the instructions become its prompt. */
export async function handleWorkflowCreate(
  gaia: GaiaClient,
  title: string,
  instructions: string,
  ctx: CommandContext,
): Promise<string> {
  try {
    const workflow = await gaia.createWorkflow(
      {
        title,
        prompt: instructions,
        trigger_config: { type: "manual", enabled: true },
      },
      ctx,
    );
    return `✅ Workflow created!\n\n${formatWorkflow(workflow)}`;
  } catch (error: unknown) {
    return reportCommandFailure("create_workflow", error, ctx);
  }
}

export async function handleTaskDelete(
  gaia: GaiaClient,
  taskId: string,
  ctx: CommandContext,
): Promise<string> {
  try {
    await gaia.deleteTask(taskId, ctx);
    return "✅ Todo deleted successfully";
  } catch (error: unknown) {
    return reportCommandFailure("delete_task", error, ctx);
  }
}

export async function dispatchTaskSubcommand(
  gaia: GaiaClient,
  ctx: CommandContext,
  subcommand: string,
  args: string[],
): Promise<string> {
  switch (subcommand) {
    case "list":
      return handleTaskList(gaia, ctx);
    case "add": {
      const title = args.join(" ");
      if (!title) return COMMAND_HELP.todoUsage.add;
      return handleTaskCreate(gaia, title, ctx);
    }
    case "complete": {
      if (!args[0]) return COMMAND_HELP.todoUsage.complete;
      return handleTaskComplete(gaia, args[0], ctx);
    }
    case "delete": {
      if (!args[0]) return COMMAND_HELP.todoUsage.delete;
      return handleTaskDelete(gaia, args[0], ctx);
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
    return reportCommandFailure("delete_workflow", error, ctx);
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
 * Starts a new conversation for the user, resetting bot session context while preserving the
 * previous conversation (still accessible from the web app) — for when context gets too long
 * or the topic changes completely. Returns a success message explaining that
 * the previous conversation is saved.
 */
export async function handleNewConversation(
  gaia: GaiaClient,
  ctx: CommandContext,
): Promise<string> {
  try {
    await gaia.resetSession(
      ctx.platform,
      ctx.platformUserId,
      ctx.channelId,
      ctx.isDm,
    );
    return "Started a new conversation. Your previous conversation is saved and accessible from the GAIA web app.";
  } catch (error: unknown) {
    return reportCommandFailure("reset_session", error, ctx);
  }
}
