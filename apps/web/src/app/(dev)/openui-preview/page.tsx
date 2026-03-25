"use client";

import React from "react";
import {
  AccordionView,
  ActionCardView,
  AlertBannerView,
  AreaChartView,
  AudioPlayerView,
  AvatarListView,
  BarChartView,
  CalendarMiniView,
  CarouselView,
  ComparisonTableView,
  DataCardView,
  DataTableView,
  DiffBlockView,
  FileTreeView,
  GaugeChartView,
  ImageBlockView,
  JsonViewerView,
  KbdBlockView,
  LineChartView,
  MapBlockView,
  MetricCardView,
  NumberTickerView,
  PieChartView,
  ProgressListView,
  RadarChartView,
  ResultListView,
  ScatterChartView,
  SelectableListView,
  StatRowView,
  StatusCardView,
  StepsView,
  TabsBlockView,
  TagGroupView,
  TimelineView,
  TreeViewView,
  VideoBlockView,
} from "@/config/openui/genericLibrary";

export default function OpenUIPreview() {
  return (
    <div className="min-h-screen bg-zinc-950 p-8 space-y-12">
      <h1 className="text-2xl font-bold text-zinc-100">
        OpenUI Component Library Preview
      </h1>

      {/* DataCard */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-300">DataCard</h2>
        <code className="text-xs text-zinc-500">DataCard(title, fields)</code>
        <DataCardView
          title="User Profile"
          fields={[
            { label: "Name", value: "Alex Kim" },
            { label: "Email", value: "alex@example.com" },
            { label: "Role", value: "Senior Engineer" },
            { label: "Location", value: "San Francisco, CA" },
            { label: "Joined", value: "Jan 2023" },
          ]}
        />
      </section>

      {/* ResultList */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-300">ResultList</h2>
        <code className="text-xs text-zinc-500">ResultList(title?, items)</code>
        <ResultListView
          title="Search Results"
          items={[
            {
              title: "Next.js 15 Released",
              subtitle: "vercel.com",
              body: "Next.js 15 brings improved caching, React 19 support, and faster builds.",
              url: "https://nextjs.org/blog/next-15",
              badge: "News",
            },
            {
              title: "TypeScript 5.8 Features",
              subtitle: "typescriptlang.org",
              body: "New inference improvements and performance enhancements in the latest release.",
              url: "https://devblogs.microsoft.com/typescript",
              badge: "Docs",
            },
            {
              title: "React Server Components Deep Dive",
              subtitle: "react.dev",
              body: "Understanding RSC architecture and when to use them in production.",
            },
          ]}
        />
      </section>

      {/* DataTable */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-300">DataTable</h2>
        <code className="text-xs text-zinc-500">DataTable(title?, columns, rows)</code>
        <DataTableView
          title="API Usage Stats"
          columns={["Endpoint", "Requests", "Avg Latency", "Error Rate"]}
          rows={[
            ["/api/chat", "12,430", "234ms", "0.2%"],
            ["/api/tools", "8,921", "89ms", "0.0%"],
            ["/api/memory", "3,102", "412ms", "1.1%"],
            ["/api/search", "5,678", "567ms", "0.4%"],
          ]}
        />
      </section>

      {/* ComparisonTable */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-300">ComparisonTable</h2>
        <code className="text-xs text-zinc-500">
          ComparisonTable(title?, leftLabel, rightLabel, rows)
        </code>
        <ComparisonTableView
          title="Plan Comparison"
          leftLabel="Free"
          rightLabel="Pro"
          rows={[
            { label: "Messages / month", left: "100", right: "Unlimited", highlight: true },
            { label: "File uploads", left: "5 MB", right: "500 MB", highlight: false },
            { label: "Memory", left: "Basic", right: "Full history", highlight: true },
            { label: "Priority support", left: "No", right: "Yes", highlight: false },
            { label: "Custom integrations", left: "No", right: "Yes", highlight: true },
          ]}
        />
      </section>

      {/* StatusCard */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-300">StatusCard</h2>
        <code className="text-xs text-zinc-500">
          StatusCard(title, status, message?, detail?)
        </code>
        <div className="space-y-2">
          <StatusCardView
            title="Deployment Successful"
            status="success"
            message="Build deployed to production in 42 seconds."
            detail="Version: v2.4.1 — Region: us-east-1"
          />
          <StatusCardView
            title="Payment Failed"
            status="error"
            message="Your card was declined. Please update your payment method."
            detail="Error code: card_declined"
          />
          <StatusCardView
            title="Processing"
            status="pending"
            message="Syncing data from Notion workspace..."
          />
          <StatusCardView
            title="Rate Limit Warning"
            status="warning"
            message="You have used 87% of your monthly quota."
          />
          <StatusCardView
            title="Update Available"
            status="info"
            message="GAIA v2.5 is available with improved memory and MCP support."
          />
        </div>
      </section>

      {/* ActionCard */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-300">ActionCard</h2>
        <code className="text-xs text-zinc-500">ActionCard(title, description?, actions?)</code>
        <ActionCardView
          title="What would you like to do next?"
          description="Your Notion export completed. Here are some things you can do with the data."
          actions={[
            {
              label: "Summarize the content",
              type: "continue_conversation",
              value: "Summarize the exported Notion content",
            },
            {
              label: "Find action items",
              type: "continue_conversation",
              value: "Find all action items in the exported Notion pages",
            },
            {
              label: "Create a task list",
              type: "continue_conversation",
              value: "Create a todo list from the Notion export",
            },
          ]}
        />
      </section>

      {/* TagGroup */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-300">TagGroup</h2>
        <code className="text-xs text-zinc-500">TagGroup(title?, tags)</code>
        <TagGroupView
          title="Tech Stack"
          tags={[
            { label: "TypeScript", color: "primary" },
            { label: "React", color: "primary" },
            { label: "Next.js", color: "default" },
            { label: "PostgreSQL", color: "success" },
            { label: "Redis", color: "warning" },
            { label: "Docker", color: "default" },
            { label: "Deprecated", color: "danger" },
          ]}
        />
      </section>

      {/* FileTree */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-300">FileTree</h2>
        <code className="text-xs text-zinc-500">FileTree(title?, items)</code>
        <FileTreeView
          title="Project Structure"
          items={[
            { path: "src/", type: "dir" },
            { path: "src/components/", type: "dir" },
            { path: "src/components/Button.tsx", type: "file", size: "2.1 KB" },
            { path: "src/components/Input.tsx", type: "file", size: "1.8 KB" },
            { path: "src/features/", type: "dir" },
            { path: "src/features/chat/", type: "dir" },
            {
              path: "src/features/chat/ChatWindow.tsx",
              type: "file",
              size: "8.4 KB",
            },
            { path: "src/lib/utils.ts", type: "file", size: "1.2 KB" },
            { path: "package.json", type: "file", size: "3.9 KB" },
          ]}
        />
      </section>

      {/* Accordion */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-300">Accordion</h2>
        <code className="text-xs text-zinc-500">Accordion(title?, items)</code>
        <AccordionView
          title="FAQ"
          items={[
            {
              label: "How does GAIA remember my preferences?",
              content:
                "GAIA uses a persistent memory layer backed by a vector database. Every interaction contributes to your personal memory graph, which GAIA queries in real time.",
            },
            {
              label: "Can I connect my own MCP tools?",
              content:
                "Yes. Go to Settings → Integrations and add your MCP server URL. GAIA will discover available tools automatically and make them accessible in conversations.",
            },
            {
              label: "Is my data encrypted?",
              content:
                "All data is encrypted at rest (AES-256) and in transit (TLS 1.3). Your personal memory is isolated per-user and never shared across accounts.",
            },
          ]}
        />
      </section>

      {/* TabsBlock */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-300">TabsBlock</h2>
        <code className="text-xs text-zinc-500">TabsBlock(tabs)</code>
        <TabsBlockView
          tabs={[
            {
              label: "Overview",
              content:
                "GAIA is a proactive AI assistant that learns your workflows, connects your tools, and acts on your behalf across email, calendar, tasks, and third-party integrations.",
            },
            {
              label: "Installation",
              content:
                "1. pnpm install\n2. cp .env.example .env\n3. nx dev web\n4. nx dev api",
            },
            {
              label: "Configuration",
              content:
                "Edit apps/api/.env with your API keys. Required: OPENAI_API_KEY, POSTGRES_URL, REDIS_URL. Optional: TAVILY_API_KEY for search, COMPOSIO_KEY for integrations.",
            },
          ]}
        />
      </section>

      {/* ProgressList */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-300">ProgressList</h2>
        <code className="text-xs text-zinc-500">ProgressList(title?, items)</code>
        <ProgressListView
          title="Migration Progress"
          items={[
            { label: "Database migration", value: 100, max: 100, color: "success" },
            { label: "API endpoints", value: 78, max: 100, color: "primary" },
            { label: "Frontend components", value: 45, max: 100, color: "warning" },
            { label: "Documentation", value: 20, max: 100, color: "danger" },
            { label: "Tests", value: 60, max: 100, color: "default" },
          ]}
        />
      </section>

      {/* StatRow */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-300">StatRow</h2>
        <code className="text-xs text-zinc-500">StatRow(stats)</code>
        <StatRowView
          stats={[
            { label: "Total users", value: "12,430", description: "+8% this month" },
            { label: "Active today", value: "1,892" },
            { label: "Messages sent", value: "284K" },
            { label: "Uptime", value: "99.97%", description: "Last 30 days" },
          ]}
        />
      </section>

      {/* SelectableList */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-300">SelectableList</h2>
        <code className="text-xs text-zinc-500">
          SelectableList(title?, description?, options)
        </code>
        <SelectableListView
          title="Choose a deployment region"
          description="Select the region closest to your users for best performance."
          options={[
            {
              label: "US East (Virginia)",
              description: "Lowest latency for North American users",
              value: "us-east-1",
              badge: "Recommended",
            },
            {
              label: "EU West (Ireland)",
              description: "GDPR-compliant storage and processing",
              value: "eu-west-1",
            },
            {
              label: "Asia Pacific (Singapore)",
              description: "Optimal for Southeast Asian users",
              value: "ap-southeast-1",
            },
          ]}
        />
      </section>

      {/* AvatarList */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-300">AvatarList</h2>
        <code className="text-xs text-zinc-500">AvatarList(title?, items)</code>
        <AvatarListView
          title="Team Members"
          items={[
            {
              name: "Aryan Sharma",
              role: "Engineering Lead",
              description: "Full-stack, AI systems",
              initials: "AS",
              color: "#a78bfa",
            },
            {
              name: "Maya Chen",
              role: "Product Designer",
              description: "UI/UX, design systems",
              initials: "MC",
              color: "#34d399",
            },
            {
              name: "Jordan Lee",
              role: "Backend Engineer",
              description: "Python, LangGraph, infra",
              initials: "JL",
              color: "#60a5fa",
            },
          ]}
        />
      </section>

      {/* KbdBlock */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-300">KbdBlock</h2>
        <code className="text-xs text-zinc-500">KbdBlock(title?, shortcuts)</code>
        <KbdBlockView
          title="Keyboard Shortcuts"
          shortcuts={[
            { keys: ["⌘", "K"], description: "Open command palette" },
            { keys: ["⌘", "Enter"], description: "Send message" },
            { keys: ["⌘", "N"], description: "New conversation" },
            { keys: ["⌘", "/"], description: "Toggle sidebar" },
            { keys: ["Esc"], description: "Close modal / cancel" },
          ]}
        />
      </section>

      {/* MetricCard */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-300">MetricCard</h2>
        <code className="text-xs text-zinc-500">MetricCard(title, value, ...)</code>
        <div className="flex flex-wrap gap-3">
          <MetricCardView
            title="Monthly Active Users"
            value={12430}
            trend="up"
            trendLabel="18% vs last month"
          />
          <MetricCardView
            title="Avg Response Time"
            value={234}
            unit="ms"
            trend="down"
            trendLabel="12% faster"
          />
          <MetricCardView
            title="Error Rate"
            value="0.4%"
            trend="neutral"
            trendLabel="No change"
          />
        </div>
      </section>

      {/* BarChart */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-300">BarChart</h2>
        <code className="text-xs text-zinc-500">BarChart(title?, data, xKey, yKey)</code>
        <BarChartView
          title="Weekly Messages"
          data={[
            { day: "Mon", messages: 1240 },
            { day: "Tue", messages: 1890 },
            { day: "Wed", messages: 2100 },
            { day: "Thu", messages: 1650 },
            { day: "Fri", messages: 2340 },
            { day: "Sat", messages: 890 },
            { day: "Sun", messages: 720 },
          ]}
          xKey="day"
          yKey="messages"
        />
      </section>

      {/* LineChart */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-300">LineChart</h2>
        <code className="text-xs text-zinc-500">LineChart(title?, data, xKey, yKeys)</code>
        <LineChartView
          title="Traffic Over Time"
          data={[
            { date: "Jan", web: 4000, api: 2400 },
            { date: "Feb", web: 3000, api: 1398 },
            { date: "Mar", web: 6000, api: 9800 },
            { date: "Apr", web: 8000, api: 3908 },
            { date: "May", web: 5000, api: 4800 },
            { date: "Jun", web: 9000, api: 3800 },
          ]}
          xKey="date"
          yKeys={["web", "api"]}
        />
      </section>

      {/* AreaChart */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-300">AreaChart</h2>
        <code className="text-xs text-zinc-500">AreaChart(title?, data, xKey, yKeys)</code>
        <AreaChartView
          title="Cumulative Requests"
          data={[
            { month: "Jan", requests: 12000 },
            { month: "Feb", requests: 19000 },
            { month: "Mar", requests: 28000 },
            { month: "Apr", requests: 39000 },
            { month: "May", requests: 53000 },
            { month: "Jun", requests: 71000 },
          ]}
          xKey="month"
          yKeys={["requests"]}
        />
      </section>

      {/* PieChart */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-300">PieChart</h2>
        <code className="text-xs text-zinc-500">PieChart(title?, data, nameKey, valueKey)</code>
        <PieChartView
          title="Tool Usage Breakdown"
          data={[
            { tool: "Email", usage: 35 },
            { tool: "Calendar", usage: 25 },
            { tool: "Search", usage: 20 },
            { tool: "Todos", usage: 12 },
            { tool: "Other", usage: 8 },
          ]}
          nameKey="tool"
          valueKey="usage"
        />
      </section>

      {/* ScatterChart */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-300">ScatterChart</h2>
        <code className="text-xs text-zinc-500">
          ScatterChart(title?, data, xKey, yKey, labelKey?)
        </code>
        <ScatterChartView
          title="Latency vs Request Size"
          data={[
            { size: 10, latency: 45 },
            { size: 25, latency: 89 },
            { size: 50, latency: 134 },
            { size: 80, latency: 201 },
            { size: 120, latency: 312 },
            { size: 200, latency: 489 },
            { size: 350, latency: 720 },
          ]}
          xKey="size"
          yKey="latency"
        />
      </section>

      {/* RadarChart */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-300">RadarChart</h2>
        <code className="text-xs text-zinc-500">
          RadarChart(title?, data, angleKey, valueKeys)
        </code>
        <RadarChartView
          title="Candidate Skills"
          data={[
            { skill: "TypeScript", alice: 90, bob: 75 },
            { skill: "Python", alice: 70, bob: 95 },
            { skill: "System Design", alice: 85, bob: 80 },
            { skill: "Communication", alice: 95, bob: 70 },
            { skill: "Testing", alice: 75, bob: 85 },
          ]}
          angleKey="skill"
          valueKeys={["alice", "bob"]}
        />
      </section>

      {/* GaugeChart */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-300">GaugeChart</h2>
        <code className="text-xs text-zinc-500">GaugeChart(title?, value, min?, max?, ...)</code>
        <div className="flex flex-wrap gap-3">
          <GaugeChartView
            title="CPU Usage"
            value={28}
            min={0}
            max={100}
            unit="%"
            thresholds={{ warning: 60, danger: 80 }}
          />
          <GaugeChartView
            title="Memory Usage"
            value={74}
            min={0}
            max={100}
            unit="%"
            thresholds={{ warning: 60, danger: 80 }}
          />
          <GaugeChartView
            title="Disk I/O"
            value={93}
            min={0}
            max={100}
            unit="%"
            thresholds={{ warning: 60, danger: 80 }}
          />
        </div>
      </section>

      {/* ImageBlock */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-300">ImageBlock</h2>
        <code className="text-xs text-zinc-500">ImageBlock(src, alt?, caption?)</code>
        <ImageBlockView
          src="https://images.unsplash.com/photo-1677442135703-1787eea5ce01?w=800&q=80"
          alt="AI visualization"
          caption="A visualization of neural network activations during inference."
        />
      </section>

      {/* DiffBlock */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-300">DiffBlock</h2>
        <code className="text-xs text-zinc-500">DiffBlock(title?, hunks)</code>
        <DiffBlockView
          title="src/config/settings.py"
          hunks={[
            {
              header: "@@ -94,8 +94,4 @@",
              lines: [
                { type: "context", content: "    # Feature Flags" },
                {
                  type: "context",
                  content: "    # ------------------------------------------",
                },
                {
                  type: "remove",
                  content:
                    "    ENABLE_OPENUI: bool = False  # Enable OpenUI Lang",
                },
                {
                  type: "remove",
                  content: "    MIGRATED_TOOLS: set[str] = set()",
                },
                {
                  type: "context",
                  content: "    # ------------------------------------------",
                },
              ],
            },
          ]}
        />
      </section>

      {/* MapBlock */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-300">MapBlock</h2>
        <code className="text-xs text-zinc-500">MapBlock(lat, lng, label?, zoom?)</code>
        <MapBlockView
          lat={37.7749}
          lng={-122.4194}
          label="San Francisco, CA"
          zoom={13}
        />
      </section>

      {/* CalendarMini */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-300">CalendarMini</h2>
        <code className="text-xs text-zinc-500">CalendarMini(title?, markedDates)</code>
        <CalendarMiniView
          title="March 2026"
          markedDates={[
            { date: "2026-03-25", label: "Sprint Review", color: "success" },
            { date: "2026-03-27", label: "Team Off-site", color: "warning" },
            { date: "2026-03-31", label: "Quarter End", color: "danger" },
          ]}
        />
      </section>

      {/* NumberTicker */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-300">NumberTicker</h2>
        <code className="text-xs text-zinc-500">NumberTicker(value, label?, unit?)</code>
        <div className="flex flex-wrap gap-3">
          <NumberTickerView value={284293} label="Total messages" duration={1500} />
          <NumberTickerView value={12430} label="Active users" />
          <NumberTickerView value={99.97} label="Uptime" unit="%" duration={800} />
        </div>
      </section>

      {/* Carousel */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-300">Carousel</h2>
        <code className="text-xs text-zinc-500">Carousel(items, autoPlay?)</code>
        <CarouselView
          items={[
            {
              title: "GAIA Pro",
              body: "Unlimited messages, full memory history, and priority support.",
              badge: "Most Popular",
              actions: [
                {
                  label: "Learn more",
                  value: "Tell me more about GAIA Pro",
                },
              ],
            },
            {
              title: "GAIA Team",
              body: "Shared workspace, team memory, and admin controls for your organization.",
              badge: "New",
              actions: [
                {
                  label: "See pricing",
                  value: "What is the pricing for GAIA Team?",
                },
              ],
            },
            {
              title: "GAIA Enterprise",
              body: "Custom deployment, SSO, audit logs, and dedicated support.",
              actions: [
                {
                  label: "Contact sales",
                  value: "I want to learn about GAIA Enterprise",
                },
              ],
            },
          ]}
        />
      </section>

      {/* TreeView */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-300">TreeView</h2>
        <code className="text-xs text-zinc-500">TreeView(title?, nodes)</code>
        <TreeViewView
          title="Engineering Org Chart"
          nodes={[
            {
              id: "eng",
              label: "Engineering",
              description: "12 members",
              children: [
                {
                  id: "fe",
                  label: "Frontend",
                  description: "4 members",
                  children: [
                    { id: "fe1", label: "Aryan Sharma", description: "Lead" },
                    { id: "fe2", label: "Maya Chen", description: "Senior" },
                  ],
                },
                {
                  id: "be",
                  label: "Backend",
                  description: "5 members",
                  children: [
                    { id: "be1", label: "Jordan Lee", description: "Lead" },
                    { id: "be2", label: "Sam Park", description: "Senior" },
                  ],
                },
              ],
            },
          ]}
        />
      </section>

      {/* Timeline */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-300">Timeline</h2>
        <code className="text-xs text-zinc-500">Timeline(title?, items)</code>
        <TimelineView
          title="Deployment History"
          items={[
            {
              time: "2026-03-25T14:30:00Z",
              title: "v2.4.1 deployed to production",
              description: "Build time: 42s. All health checks passed.",
              status: "success",
            },
            {
              time: "2026-03-25T09:15:00Z",
              title: "Database migration started",
              description: "Running schema updates for v2.4.0 → v2.4.1.",
              status: "neutral",
            },
            {
              time: "2026-03-24T18:00:00Z",
              title: "v2.4.0 rollback triggered",
              description: "Memory service returning 503 errors. Rolled back automatically.",
              status: "error",
            },
            {
              time: "2026-03-24T16:45:00Z",
              title: "v2.4.0 deployment failed",
              description: "Health check timeout after 120s.",
              status: "warning",
            },
          ]}
        />
      </section>

      {/* JsonViewer */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-300">JsonViewer</h2>
        <code className="text-xs text-zinc-500">JsonViewer(title?, data)</code>
        <JsonViewerView
          title="API Response"
          data={JSON.stringify({
            id: "msg_01XFDUDYJgAACXkMLMedJDkb",
            type: "message",
            role: "assistant",
            model: "claude-sonnet-4-6",
            usage: {
              input_tokens: 1842,
              output_tokens: 312,
              cache_creation_input_tokens: 0,
              cache_read_input_tokens: 1200,
            },
            stop_reason: "end_turn",
            metadata: {
              request_id: "req_abc123",
              latency_ms: 1240,
            },
          })}
        />
      </section>

      {/* AlertBanner */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-300">AlertBanner</h2>
        <code className="text-xs text-zinc-500">AlertBanner(variant, title, description?)</code>
        <div className="space-y-2">
          <AlertBannerView
            variant="info"
            title="New MCP integrations available"
            description="Connect Figma, Linear, and Vercel MCP servers from the integrations page."
          />
          <AlertBannerView
            variant="success"
            title="Export complete"
            description="Your data export is ready. The download link expires in 24 hours."
          />
          <AlertBannerView
            variant="warning"
            title="API key expiring soon"
            description="Your OpenAI API key expires in 7 days. Rotate it before then to avoid service interruption."
          />
          <AlertBannerView
            variant="error"
            title="Connection lost"
            description="Unable to reach the GAIA API. Retrying every 5 seconds."
          />
        </div>
      </section>

      {/* Steps */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-300">Steps</h2>
        <code className="text-xs text-zinc-500">Steps(title?, items)</code>
        <StepsView
          title="MCP Server Setup"
          items={[
            {
              title: "Install the MCP server",
              description: "npm install -g @modelcontextprotocol/server-notion",
              status: "complete",
            },
            {
              title: "Configure authentication",
              description:
                "Set NOTION_API_KEY in your environment variables.",
              status: "complete",
            },
            {
              title: "Add server URL to GAIA",
              description:
                "Go to Settings → Integrations and paste your MCP server URL.",
              status: "active",
            },
            {
              title: "Test the connection",
              description: "Send a test message to verify GAIA can reach your tools.",
              status: "pending",
            },
            {
              title: "Enable in conversations",
              description: "Your MCP tools will now appear when GAIA needs them.",
              status: "pending",
            },
          ]}
        />
      </section>

      {/* VideoBlock */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-300">VideoBlock</h2>
        <code className="text-xs text-zinc-500">VideoBlock(src, title?, poster?)</code>
        <VideoBlockView
          src="https://www.youtube.com/watch?v=dQw4w9WgXcQ"
          title="YouTube Embed Example"
        />
      </section>

      {/* AudioPlayer */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-300">AudioPlayer</h2>
        <code className="text-xs text-zinc-500">AudioPlayer(src, title?, description?)</code>
        <AudioPlayerView
          src="https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3"
          title="SoundHelix Song 1"
          description="A sample audio file for preview purposes."
        />
      </section>
    </div>
  );
}
