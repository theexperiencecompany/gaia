import { HtmlLocator, HtmlScene } from "@effect/ui/html/testing";
import { Locator, Story } from "@effect/ui/testing";
import { assert, it } from "@effect/vitest";
import { Effect } from "effect";
import { TodosMessage, TodosPageNoDeps, ToggleTodo } from "../src/index";

const todo = {
  id: "todo-1",
  title: "Buy milk",
  completed: false,
  priority: "medium" as const,
  due_date: null,
  created_at: "2026-11-28T00:00:00.000Z",
};

it.effect("a row's checkbox issues ToggleTodo", () =>
  Effect.gen(function* () {
    const story = yield* Story.make(TodosPageNoDeps, {});
    story.given({}, { todos: [todo] });

    story.send(TodosMessage.RequestedToggle({ id: todo.id, completed: true }));
    story.expectExact(ToggleTodo);
    story.resolve(ToggleTodo, TodosMessage.ToggledTodo());

    assert.deepStrictEqual(story.model, {});
  }),
);

it.effect("the list renders the task title and its checkbox", () =>
  Effect.gen(function* () {
    const scene = yield* HtmlScene.make(TodosPageNoDeps, {});
    scene.given({}, { todos: [todo] });

    scene.expect(Locator.text("Buy milk")).toExist();
    scene.click(HtmlLocator.role("checkbox", { name: "Toggle Buy milk" }));
    scene.expectExact(ToggleTodo);
    scene.resolve(ToggleTodo, TodosMessage.ToggledTodo());
  }),
);
