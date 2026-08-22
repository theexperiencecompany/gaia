/**
 * Decouples the todo store from workflow polling.
 *
 * The store fires this when a todo is created, and the global workflow listener
 * subscribes to it. Without this seam the store would import the polling module
 * directly, and that module writes results back through the store — an import
 * cycle that `noImportCycles` flags.
 */
type TodoCreatedHandler = (todoId: string) => void;

const handlers = new Set<TodoCreatedHandler>();

export function subscribeToTodoCreated(
  handler: TodoCreatedHandler,
): () => void {
  handlers.add(handler);
  return () => {
    handlers.delete(handler);
  };
}

export function emitTodoCreated(todoId: string): void {
  for (const handler of handlers) handler(todoId);
}
