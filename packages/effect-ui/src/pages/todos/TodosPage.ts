import { Command, Component, Query, UiSchema } from "@effect/ui";
import { Html } from "@effect/ui/html";
import type { H } from "@effect/ui/html/Html";
import { Effect, Schema } from "effect";
import { AsyncResult } from "effect/reactivity";
import { Todo, TodoList } from "../../domain/Todo";
import { Api, ApiError } from "../../services/Api";

/**
 * The Todos list, ported 1:1 from
 * apps/web/src/features/todo/components/TodoListPage.tsx and TodoItem.tsx.
 * Classes and DOM shape are copied from the rendered React page; the only
 * replacement is the HeroUI checkbox, rebuilt with the same classes and a
 * native input.
 */

export const TodosMessage = UiSchema.TaggedEnum({
  RequestedToggle: { id: Schema.String, completed: Schema.Boolean },
  ToggledTodo: {},
  Failed: { message: Schema.String },
});

type TodosH = H<typeof TodosMessage.Type>;

export class ListTodos extends Query.Service<ListTodos>()("Todos/ListTodos", {
  success: Schema.Array(Todo),
  error: ApiError,
  staleTime: "5 seconds",
}) {
  static readonly layer = this.toLayer(
    Effect.gen(function* () {
      const api = yield* Api;
      return () =>
        api
          .request("/todos?completed=false", { method: "GET" }, TodoList)
          .pipe(Effect.map((response) => response.data));
    }),
  );
}

export class ToggleTodo extends Command.Service<ToggleTodo>()(
  "Todos/ToggleTodo",
  {
    args: { id: Schema.String, completed: Schema.Boolean },
    success: TodosMessage,
    invalidates: () => [ListTodos],
    optimistic: ({ id, completed }) => [
      ListTodos.patch({}, (todos) =>
        todos.map((todo) =>
          todo.id === id ? { ...todo, completed } : todo,
        ),
      ),
    ],
  },
) {
  static readonly layer = this.toLayer(
    Effect.gen(function* () {
      const api = yield* Api;
      return ({ id, completed }) =>
        api
          .request(
            `/todos/${encodeURIComponent(id)}`,
            { method: "PUT", body: JSON.stringify({ completed }) },
            Todo,
          )
          .pipe(
            Effect.match({
              onSuccess: () => TodosMessage.ToggledTodo(),
              onFailure: (error) =>
                TodosMessage.Failed({ message: error.message }),
            }),
          );
    }),
  );
}

const PRIORITY_RING: Record<Todo["priority"], string> = {
  high: "border-red-500",
  medium: "border-yellow-500",
  low: "border-blue-500",
  none: "border-zinc-500",
};

const CHECKBOX_BASE =
  "relative inline-flex items-center justify-center shrink-0 overflow-hidden before:content-[''] before:absolute before:inset-0 before:border-solid before:border-2 before:box-border before:border-default after:content-[''] after:absolute after:inset-0 after:scale-50 after:opacity-0 after:origin-center group-data-[selected=true]:after:scale-100 group-data-[selected=true]:after:opacity-100 group-data-[hover=true]:before:bg-default-100 outline-solid outline-transparent group-data-[focus-visible=true]:z-10 group-data-[focus-visible=true]:ring-2 group-data-[focus-visible=true]:ring-focus group-data-[focus-visible=true]:ring-offset-2 group-data-[focus-visible=true]:ring-offset-background after:bg-default after:text-default-foreground text-default-foreground w-5 h-5 me-2 rounded-full before:rounded-full after:rounded-full before:transition-colors group-data-[pressed=true]:scale-95 transition-transform after:transition-transform-opacity after:!ease-linear after:!duration-200 motion-reduce:transition-none";

const checkIcon = (h: TodosH) =>
  h.svg
    .attr("aria-hidden", "true")
    .attr("fill", "none")
    .attr("role", "presentation")
    .attr("stroke", "currentColor")
    .attr("stroke-dasharray", "22")
    .attr("stroke-dashoffset", "66")
    .attr("stroke-linecap", "round")
    .attr("stroke-linejoin", "round")
    .attr("stroke-width", "2")
    .attr("viewBox", "0 0 17 18")
    .class(
      "z-10 opacity-0 group-data-[selected=true]:opacity-100 pointer-events-none w-4 h-3 transition-opacity motion-reduce:transition-none",
    )
    .children(h.polyline.attr("points", "1 9 7 14 15 4"));

const chevron = (h: TodosH) =>
  h.svg
    .attr("xmlns", "http://www.w3.org/2000/svg")
    .attr("width", "20")
    .attr("height", "20")
    .attr("viewBox", "0 0 24 24")
    .attr("fill", "none")
    .attr("stroke", "currentColor")
    .attr("stroke-width", "2")
    .attr("stroke-linecap", "round")
    .attr("stroke-linejoin", "round")
    .class("text-zinc-400")
    .children(h.path.attr("d", "m9 18 6-6-6-6"));

const TodoRow = (h: TodosH, todo: Todo) => {
  const checkboxClass = `${CHECKBOX_BASE} mt-1 ${
    todo.completed
      ? ""
      : `${PRIORITY_RING[todo.priority]} border-dashed! border-1 before:border-0! bg-zinc-900`
  }`;

  return h.div
    .key(todo.id)
    .class(
      `pointer-events-auto relative w-full rounded-xl p-2 pl-3 mb-0 group hover:bg-zinc-800/50 ${
        todo.completed ? "opacity-30" : ""
      }`,
    )
    .children(
      h.div
        .class(
          "pointer-events-none relative z-20 flex h-full items-start gap-2",
        )
        .children(
          h.div.class("pointer-events-auto").children(
            h.label
              .class(
                "group relative max-w-fit inline-flex items-center justify-start cursor-pointer tap-highlight-transparent p-2 -m-2 select-none rounded-full has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-focus has-[:focus-visible]:ring-offset-2 has-[:focus-visible]:ring-offset-background",
              )
              .attr("data-selected", todo.completed ? "true" : "false")
              .children(
                h.input
                  .attr("type", "checkbox")
                  .attr("aria-label", `Toggle ${todo.title}`)
                  .checked(todo.completed)
                  .class(
                    "font-inherit text-[100%] leading-[1.15] m-0 p-0 overflow-visible box-border absolute top-0 w-full h-full opacity-[0.0001] z-[1] cursor-pointer disabled:cursor-default",
                  )
                  .on("change", ({ checked }) =>
                    TodosMessage.RequestedToggle({
                      id: todo.id,
                      completed: checked,
                    }),
                  ),
                h.span
                  .attr("aria-hidden", "true")
                  .class(checkboxClass)
                  .children(checkIcon(h)),
              ),
          ),
          h.div.class("min-w-0 flex-1").children(
            h.div.children(
              h.h4
                .style({
                  display: "-webkit-box",
                  webkitBoxOrient: "vertical",
                  webkitLineClamp: "2",
                  overflow: "hidden",
                })
                .class(
                  `text-base font-normal ${
                    todo.completed ? "text-zinc-500 line-through" : ""
                  }`,
                )
                .children(h.span(todo.title)),
            ),
          ),
          h.div
            .class(
              "flex h-full min-h-full justify-center items-center self-center group-hover:opacity-100 opacity-0 transition",
            )
            .children(chevron(h)),
        ),
    );
};

const TodosPageDef = Html.component({
  name: "TodosPage",
  model: Schema.Struct({}),
  message: TodosMessage,
  queries: {
    todos: { query: ListTodos, args: () => ({}) },
  },
});

export const TodosPageNoDeps = TodosPageDef.make({
  init: () => ({}),

  update: {
    RequestedToggle: ($, { id, completed }) =>
      $.run(ToggleTodo.make({ id, completed })),
    ToggledTodo: ($) => $.model,
    Failed: ($) => $.model,
  },

  view: (h) =>
    h.div.class("flex h-full w-full flex-col").children(
      h.div.class("w-full flex-1 overflow-y-auto px-4").children(
        AsyncResult.match(h.queries.todos, {
          onInitial: () =>
            h.div
              .class("flex h-64 items-center justify-center")
              .children(
                h.p.class("text-sm text-zinc-500").children("Loading tasks…"),
              ),
          onFailure: () =>
            h.div
              .class(
                "flex h-64 flex-col items-center justify-center gap-3 px-4",
              )
              .children(
                h.p
                  .class("text-base text-zinc-300")
                  .children("Couldn't load tasks"),
                h.p
                  .class("text-sm text-zinc-500")
                  .children("Refresh the page to try again."),
              ),
          onSuccess: ({ value }) => {
            const sorted = [...value].sort(
              (a, b) => Number(a.completed) - Number(b.completed),
            );

            if (sorted.length === 0) {
              return h.div
                .class(
                  "flex h-64 flex-col items-center justify-center text-foreground-500 sm:min-w-5xl",
                )
                .children(
                  h.p.class("mb-2 text-lg").children("No tasks found"),
                  h.p
                    .class("text-sm")
                    .children("Create a new task to get started"),
                );
            }

            return h.div.class("flex w-full justify-center").children(
              h.div
                .style({
                  height: `${16 + sorted.length * 42 + 16}px`,
                  position: "relative",
                  width: "100%",
                })
                .children(
                  sorted.map((todo, index) =>
                    h.div
                      .key(todo.id)
                      .attr("data-index", String(index))
                      .style({
                        position: "absolute",
                        top: "0",
                        left: "0",
                        width: "100%",
                        transform: `translateY(${16 + index * 42}px)`,
                      })
                      .children(TodoRow(h, todo)),
                  ),
                ),
            );
          },
        }),
      ),
    ),
});

export const TodosPage = TodosPageNoDeps.pipe(
  Component.provide([ListTodos.layer, ToggleTodo.layer]),
);
