import "./page.css";
import "./page.2.css";
import "./page.3.css";
import "./page.4.css";
import "./page.5.css";
import TodoListPage from "@/features/todo/components/TodoListPage";

export default function CompletedTodosPage() {
  return <TodoListPage filters={{ completed: true }} />;
}
