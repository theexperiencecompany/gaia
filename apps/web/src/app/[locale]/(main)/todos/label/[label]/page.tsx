import TodoListPage from "@/features/todo/components/TodoListPage";

interface LabelTodosPageProps {
  params: Promise<{ label: string }>;
}

export default async function LabelTodosPage({
  params,
}: Readonly<LabelTodosPageProps>) {
  // params.label is already decoded by the App Router; decoding again would
  // throw on labels containing a literal "%" (e.g. "100%").
  const { label } = await params;

  return <TodoListPage filters={{ labels: [label], completed: false }} />;
}
