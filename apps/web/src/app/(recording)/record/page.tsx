export default function RecordIndexPage() {
  const scenarios = [
    { id: "calendar-booking-demo", title: "Calendar Booking Flow" },
    { id: "todo-management-demo", title: "Task Management Flow" },
    { id: "web-search-demo", title: "Web Search Flow" },
    { id: "email-workflow-demo", title: "Email Management Flow" },
    { id: "reasoning-demo", title: "Deep Reasoning Flow" },
  ];

  return (
    <div className="min-h-screen bg-background p-8 text-foreground">
      <h1 className="text-2xl font-semibold mb-2">Recording Scenarios</h1>
      <p className="text-muted-foreground text-sm mb-8">
        Click a scenario to preview it in the browser. Use the CLI to record as
        video.
      </p>
      <div className="space-y-3 max-w-md">
        {scenarios.map((s) => (
          <a
            key={s.id}
            href={`/record/${s.id}`}
            className="block p-4 rounded-lg border border-border hover:border-primary transition-colors"
          >
            <p className="font-medium">{s.title}</p>
            <p className="text-sm text-muted-foreground mt-1">{s.id}</p>
          </a>
        ))}
      </div>
    </div>
  );
}
