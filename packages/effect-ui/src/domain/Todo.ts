import { Schema } from "effect";

/**
 * The subset of the API's TodoResponse the ported page renders. Unknown
 * fields are ignored by the decoder, so the page does not pin the whole
 * server model.
 */
export const Todo = Schema.Struct({
  id: Schema.String,
  title: Schema.String,
  completed: Schema.Boolean,
  priority: Schema.Literals(["high", "medium", "low", "none"]),
  due_date: Schema.NullOr(Schema.String),
  created_at: Schema.String,
});

export type Todo = typeof Todo.Type;

export const TodoList = Schema.Struct({
  data: Schema.Array(Todo),
});

export type TodoList = typeof TodoList.Type;
