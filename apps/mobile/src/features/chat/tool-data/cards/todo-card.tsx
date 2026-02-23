import { Card } from "heroui-native";
import { Text } from "@/components/ui/text";

export interface TodoData {
  todos?: Array<{
    title?: string;
    completed?: boolean;
  }>;
  action?: string;
  message?: string;
}

export function TodoCard({ data }: { data: TodoData }) {
  const todoCount = data.todos?.length || 0;

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-1">Todos</Text>
        {data.message && (
          <Text className="text-foreground text-sm mb-1">{data.message}</Text>
        )}
        {data.todos && todoCount > 0 && (
          <>
            {data.todos.slice(0, 3).map((todo) => (
              <Text
                key={todo.title}
                className={`text-sm ${todo.completed ? "text-muted line-through" : "text-foreground"}`}
              >
                • {todo.title}
              </Text>
            ))}
            {todoCount > 3 && (
              <Text className="text-muted text-xs mt-1">
                +{todoCount - 3} more
              </Text>
            )}
          </>
        )}
      </Card.Body>
    </Card>
  );
}
