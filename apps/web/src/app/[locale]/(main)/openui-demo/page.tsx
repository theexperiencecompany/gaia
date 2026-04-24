"use client";

import { Divider } from "@heroui/divider";
import { notFound } from "next/navigation";
import type React from "react";
import {
  AccordionView,
  AreaChartView,
  AudioPlayerView,
  AvatarView,
  BarChartView,
  ButtonsView,
  ButtonView,
  CalendarMiniView,
  CalloutView,
  CardHeaderView,
  CarouselView,
  CheckboxView,
  CodeDiffView,
  CopyableContentView,
  FileTreeView,
  GaugeChartView,
  ImageBlockView,
  ImageGalleryView,
  KbdRowView,
  LineChartView,
  MapBlockView,
  NumberTickerView,
  PieChartView,
  ProgressView,
  RadarChartView,
  RadioView,
  ScatterChartView,
  StatView,
  StepsView,
  TableView,
  TabsBlockView,
  TagBlockView,
  TagView,
  TextContentView,
  TextDocumentView,
  TimelineView,
  VideoBlockView,
} from "@/config/openui/genericLibrary";

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-2xl bg-zinc-900/40 p-4 md:p-5 space-y-4">
      <div>
        <h2 className="text-sm font-semibold text-zinc-100">{title}</h2>
        {description && (
          <p className="text-xs text-zinc-400 mt-1">{description}</p>
        )}
      </div>
      <Divider className="bg-zinc-700" />
      {children}
    </section>
  );
}

function Row({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-wrap gap-4 items-start">{children}</div>;
}

// ---------------------------------------------------------------------------
// Demo page
// ---------------------------------------------------------------------------

export default function OpenUIDemoPage() {
  if (process.env.NODE_ENV !== "development") {
    notFound();
  }
  return (
    <div className="h-full min-h-0 overflow-y-auto p-4 md:p-6 pb-16">
      <div className="mx-auto max-w-5xl space-y-6">
        <header className="rounded-2xl bg-zinc-800 p-5">
          <h1 className="text-xl font-semibold text-zinc-100">
            OpenUI Component Library
          </h1>
          <p className="text-sm text-zinc-400 mt-1">
            Live preview of all components. Compositions at the bottom.
          </p>
        </header>

        {/* ---------------------------------------------------------------- */}
        {/* Primitives                                                        */}
        {/* ---------------------------------------------------------------- */}

        <Section title="TextContent" description="All text variant styles">
          <Row>
            <TextContentView text="Heading 1" variant="h1" />
            <TextContentView text="Heading 2" variant="h2" />
            <TextContentView text="Body text" variant="body" />
            <TextContentView text="Body heavy" variant="body-heavy" />
            <TextContentView text="Small muted" variant="small" />
            <TextContentView text="Caption text" variant="caption" />
            <TextContentView text="Muted note" variant="muted" />
          </Row>
        </Section>

        <Section title="CardHeader">
          <CardHeaderView
            title="Project Alpha"
            subtitle="Last updated 2h ago"
          />
        </Section>

        <Section title="Tag + TagBlock">
          <Row>
            <TagView label="Success" color="success" />
            <TagView label="Warning" color="warning" />
            <TagView label="Danger" color="danger" />
            <TagView label="Default" color="default" />
            <TagView label="Primary" color="primary" />
          </Row>
          <TagBlockView
            labels={["React", "TypeScript", "Deployed", "v2.1.0"]}
          />
        </Section>

        <Section title="Callout">
          <Row>
            <CalloutView
              variant="warning"
              title="This action cannot be undone."
            />
            <CalloutView
              variant="success"
              title="Deployment succeeded on all regions."
            />
            <CalloutView
              variant="error"
              title="Rate limit reached."
              description="Retry in 60 seconds."
            />
            <CalloutView
              variant="info"
              title="Scheduled maintenance tonight at 2 AM UTC."
            />
          </Row>
        </Section>

        <Section title="Stat">
          <Row>
            <StatView
              value="$48,200"
              label="Revenue"
              trend="up"
              trendLabel="+12%"
            />
            <StatView value="1,284" label="Active users" />
            <StatView value="99.9%" label="Uptime" trend="neutral" />
            <StatView
              value="23ms"
              label="P95 latency"
              trend="down"
              trendLabel="-4ms"
            />
          </Row>
        </Section>

        <Section title="Button">
          <Row>
            <ButtonView label="Primary action" variant="primary" />
            <ButtonView label="Secondary" variant="secondary" />
            <ButtonView label="Danger" color="danger" variant="flat" />
            <ButtonView label="Ghost" variant="ghost" />
          </Row>
        </Section>

        <Section title="Progress">
          <div className="space-y-3 max-w-md">
            <ProgressView value={72} label="Storage used" showValue />
            <ProgressView
              value={45}
              label="CPU load"
              color="warning"
              showValue
            />
            <ProgressView value={92} label="Memory" color="danger" showValue />
            <ProgressView value={100} label="Build" color="success" showValue />
          </div>
        </Section>

        <Section
          title="Avatar"
          description="Default: image only. Pass showName to show label."
        >
          <Row>
            <AvatarView
              name="Aryan Randeriya"
              image="https://github.com/aryanranderiya.png"
            />
            <AvatarView name="Jane Smith" />
            <AvatarView name="Bob" color="success" />
            <AvatarView
              name="Aryan Randeriya"
              image="https://github.com/aryanranderiya.png"
              showName
            />
            <AvatarView name="Jane Smith" showName />
          </Row>
        </Section>

        <Section title="Checkbox + Radio">
          <Row>
            <div className="space-y-1">
              <CheckboxView label="Enable notifications" checked />
              <CheckboxView label="Dark mode" />
              <CheckboxView label="Auto-update" checked />
            </div>
            <div className="space-y-1">
              <RadioView label="Free tier" value="free" />
              <RadioView label="Pro — $12/mo" value="pro" selected />
              <RadioView label="Enterprise" value="enterprise" />
            </div>
          </Row>
        </Section>

        <Section title="Table">
          <TableView
            title="Team roster"
            cols={
              [
                {
                  props: {
                    header: "Name",
                    values: [
                      "Alice Chen",
                      "Bob Kim",
                      "Carol Davis",
                      "Dave Park",
                    ],
                  },
                },
                {
                  props: {
                    header: "Role",
                    values: [
                      "Lead Engineer",
                      "Designer",
                      "Product Manager",
                      "DevOps",
                    ],
                  },
                },
                {
                  props: {
                    header: "Status",
                    values: ["active", "active", "inactive", "active"],
                    type: "badge",
                  },
                },
                {
                  props: {
                    header: "PRs merged",
                    values: [42, 17, 3, 28],
                    type: "number",
                    align: "end",
                  },
                },
              ] as Parameters<typeof TableView>[0]["cols"]
            }
            striped
          />
        </Section>

        {/* ---------------------------------------------------------------- */}
        {/* Layout                                                            */}
        {/* ---------------------------------------------------------------- */}

        <Section title="CopyableContent">
          <div className="space-y-3">
            <CopyableContentView
              content={`GAIA_API_KEY=gaia_sk_prod_abc123xyz
GAIA_WEBHOOK_SECRET=wh_secret_def456
NEXT_PUBLIC_GAIA_URL=https://api.heygaia.io`}
              languageHint=".env"
            />
            <CopyableContentView
              content="npm install @gaia/sdk"
              mode="inline"
            />
          </div>
        </Section>

        <Section title="FileTree — file variant">
          <FileTreeView
            title="src/"
            items={[
              { path: "src/app/page.tsx", type: "file" },
              { path: "src/app/layout.tsx", type: "file" },
              { path: "src/components/Button.tsx", type: "file" },
              { path: "src/components/Modal.tsx", type: "file" },
              { path: "src/lib/api.ts", type: "file" },
            ]}
          />
        </Section>

        <Section title="FileTree — generic variant">
          <FileTreeView
            title="Company hierarchy"
            variant="generic"
            items={[
              { path: "Engineering/Frontend/Alice" },
              { path: "Engineering/Frontend/Bob" },
              { path: "Engineering/Backend/Carol" },
              { path: "Design/Dave" },
              { path: "Product/Eve" },
            ]}
          />
        </Section>

        <Section title="Accordion">
          <AccordionView
            title="FAQ"
            items={[
              {
                label: "How does billing work?",
                content:
                  "You are billed monthly at the start of each cycle. Cancel any time.",
              },
              {
                label: "Can I export my data?",
                content:
                  "Yes. Go to Settings > Data > Export to download a full JSON archive.",
              },
              {
                label: "Is there a free tier?",
                content: "Yes — up to 100 AI actions per month at no cost.",
              },
            ]}
          />
        </Section>

        <Section
          title="TabsBlock"
          description="Each tab can hold any OpenUI content — charts, stats, timelines."
        >
          <TabsBlockView
            tabs={[
              {
                label: "Analytics",
                content: (
                  <BarChartView
                    title="Weekly API requests"
                    data={[
                      { day: "Mon", requests: 1200 },
                      { day: "Tue", requests: 1800 },
                      { day: "Wed", requests: 1600 },
                      { day: "Thu", requests: 2100 },
                      { day: "Fri", requests: 2400 },
                    ]}
                    xKey="day"
                    yKeys={["requests"]}
                  />
                ),
              },
              {
                label: "Health",
                content: (
                  <div className="space-y-3">
                    <div className="flex flex-wrap gap-3">
                      <StatView value="99.8%" label="Uptime" trend="neutral" />
                      <StatView
                        value="23ms"
                        label="P95 latency"
                        trend="down"
                        trendLabel="-4ms"
                      />
                      <StatView value="4 / 6" label="Nodes healthy" />
                    </div>
                    <ProgressView value={62} label="CPU" showValue />
                    <ProgressView
                      value={89}
                      label="Memory"
                      color="danger"
                      showValue
                    />
                  </div>
                ),
              },
              {
                label: "Activity",
                content: (
                  <TimelineView
                    items={[
                      {
                        time: "2026-04-24T11:00:00",
                        title: "Deployment to production",
                        actor: "aryanranderiya",
                        status: "success",
                        description: "v2.1.0 deployed across all regions.",
                      },
                      {
                        time: "2026-04-24T10:30:00",
                        title: "CI checks passed",
                        status: "success",
                        description: "All 48 tests passed in 2m 14s.",
                      },
                      {
                        time: "2026-04-24T09:15:00",
                        title: "Review requested",
                        actor: "janedoe",
                        status: "warning",
                        description: "Awaiting 1 more approval.",
                      },
                    ]}
                  />
                ),
              },
            ]}
          />
        </Section>

        <Section
          title="KbdRow"
          description="Compose shortcut rows inside a Card for a full shortcut reference."
        >
          <div className="rounded-2xl bg-zinc-900 p-3 w-full max-w-lg space-y-2">
            <p className="text-sm font-semibold text-zinc-100 mb-3">
              Keyboard shortcuts
            </p>
            <KbdRowView keys={["⌘", "K"]} description="Open command palette" />
            <KbdRowView
              keys={["⌘", "Shift", "P"]}
              description="Quick actions"
            />
            <KbdRowView keys={["⌘", "Z"]} description="Undo last change" />
            <KbdRowView keys={["Esc"]} description="Close modal / dismiss" />
          </div>
        </Section>

        {/* ---------------------------------------------------------------- */}
        {/* Analytics                                                         */}
        {/* ---------------------------------------------------------------- */}

        <Section title="BarChart">
          <BarChartView
            title="Monthly revenue"
            data={[
              { month: "Jan", revenue: 4200 },
              { month: "Feb", revenue: 5800 },
              { month: "Mar", revenue: 7100 },
              { month: "Apr", revenue: 6400 },
              { month: "May", revenue: 8900 },
            ]}
            xKey="month"
            yKeys="revenue"
          />
        </Section>

        <Section title="LineChart">
          <LineChartView
            title="API requests"
            data={[
              { day: "Mon", requests: 1200 },
              { day: "Tue", requests: 1800 },
              { day: "Wed", requests: 1600 },
              { day: "Thu", requests: 2100 },
              { day: "Fri", requests: 2400 },
            ]}
            xKey="day"
            yKeys="requests"
          />
        </Section>

        <Section title="AreaChart">
          <AreaChartView
            title="Bandwidth usage"
            data={[
              { hour: "00:00", gb: 1.2 },
              { hour: "06:00", gb: 0.8 },
              { hour: "12:00", gb: 3.4 },
              { hour: "18:00", gb: 4.1 },
              { hour: "23:00", gb: 2.9 },
            ]}
            xKey="hour"
            yKeys="gb"
          />
        </Section>

        <Section title="PieChart">
          <PieChartView
            title="Traffic sources"
            data={[
              { source: "Organic", value: 45 },
              { source: "Direct", value: 25 },
              { source: "Social", value: 18 },
              { source: "Referral", value: 12 },
            ]}
            nameKey="source"
            valueKey="value"
          />
        </Section>

        <Section title="GaugeChart">
          <GaugeChartView
            value={73}
            title="CPU Usage"
            min={0}
            max={100}
            unit="%"
          />
        </Section>

        <Section title="RadarChart">
          <RadarChartView
            title="Team skills"
            data={[
              { skill: "Frontend", alice: 90, bob: 65 },
              { skill: "Backend", alice: 70, bob: 85 },
              { skill: "Design", alice: 80, bob: 55 },
              { skill: "DevOps", alice: 60, bob: 75 },
              { skill: "Testing", alice: 75, bob: 80 },
            ]}
            angleKey="skill"
            valueKeys={["alice", "bob"]}
          />
        </Section>

        <Section title="ScatterChart">
          <ScatterChartView
            title="Latency vs payload"
            data={[
              { size: 10, latency: 12 },
              { size: 50, latency: 34 },
              { size: 100, latency: 58 },
              { size: 200, latency: 91 },
              { size: 500, latency: 145 },
            ]}
            xKey="size"
            yKey="latency"
          />
        </Section>

        {/* ---------------------------------------------------------------- */}
        {/* Content                                                           */}
        {/* ---------------------------------------------------------------- */}

        <Section title="NumberTicker">
          <Row>
            <NumberTickerView value={48200} label="Total revenue" unit="$" />
            <NumberTickerView value={99.9} label="Uptime" unit="%" />
            <NumberTickerView value={1284} label="Active users" />
          </Row>
        </Section>

        <Section title="ImageBlock">
          <ImageBlockView
            src="https://images.unsplash.com/photo-1518770660439-4636190af475?w=800"
            alt="Technology"
            caption="High-performance server rack"
          />
        </Section>

        <Section title="Carousel">
          <CarouselView
            items={[
              {
                title: "Feature launch",
                body: "Introducing AI-powered scheduling for your entire team.",
                badge: "New",
              },
              {
                title: "Performance update",
                body: "Response times are now 40% faster across all regions.",
              },
              {
                title: "Mobile app",
                body: "The iOS and Android apps are now available in 12 languages.",
                badge: "v2.0",
              },
            ]}
          />
        </Section>

        <Section title="CalendarMini">
          <CalendarMiniView
            markedDates={[
              { date: "2026-04-15", label: "Sprint end", color: "warning" },
              { date: "2026-04-22", label: "Release", color: "success" },
              { date: "2026-04-28", label: "Retro" },
            ]}
            title="Upcoming milestones"
          />
        </Section>

        <Section title="VideoBlock">
          <VideoBlockView
            src="https://www.youtube.com/watch?v=dQw4w9WgXcQ"
            title="Demo walkthrough"
          />
        </Section>

        <Section title="AudioPlayer">
          <AudioPlayerView
            src="https://cdn.pixabay.com/audio/2024/03/06/audio_e6f50b9524.mp3"
            title="Episode 42 — The state of AI in 2026"
            description="Weekly tech roundup, 28 min"
          />
        </Section>

        <Section title="ImageGallery">
          <ImageGalleryView
            images={[
              {
                src: "https://images.unsplash.com/photo-1518770660439-4636190af475?w=600",
                alt: "Server rack",
                caption: "Data center",
              },
              {
                src: "https://images.unsplash.com/photo-1517694712202-14dd9538aa97?w=600",
                alt: "Code on monitor",
                caption: "Terminal",
              },
              {
                src: "https://images.unsplash.com/photo-1487058792275-0ad4aaf24ca7?w=600",
                alt: "Abstract code",
                caption: "Algorithms",
              },
              {
                src: "https://images.unsplash.com/photo-1526374965328-7f61d4dc18c5?w=600",
                alt: "Glowing UI",
                caption: "Interfaces",
              },
            ]}
          />
        </Section>

        <Section title="MapBlock">
          <MapBlockView
            lat={40.7128}
            lng={-74.006}
            label="New York City"
            zoom={12}
          />
        </Section>

        <Section title="Buttons">
          <ButtonsView
            buttons={
              [
                {
                  props: {
                    label: "Accept",
                    variant: "primary",
                    color: "success",
                  },
                },
                {
                  props: { label: "Reject", variant: "flat", color: "danger" },
                },
                { props: { label: "Request more info", variant: "ghost" } },
              ] as Parameters<typeof ButtonsView>[0]["buttons"]
            }
          />
        </Section>

        {/* ---------------------------------------------------------------- */}
        {/* Timeline & Steps                                                  */}
        {/* ---------------------------------------------------------------- */}

        <Section title="Timeline — with actor, links, actions">
          <TimelineView
            title="PR #421 activity"
            items={[
              {
                time: "2026-04-24T09:15:00",
                title: "Opened pull request",
                actor: "aryanranderiya",
                status: "neutral",
                links: [{ label: "View PR", url: "#", type: "primary" }],
              },
              {
                time: "2026-04-24T10:30:00",
                title: "CI checks passed",
                status: "success",
                description: "All 48 tests passed in 2m 14s.",
              },
              {
                time: "2026-04-24T11:00:00",
                title: "Review requested changes",
                actor: "janedoe",
                status: "warning",
                description: "Please add unit tests for the new hook.",
                actions: [
                  { label: "View comments", value: "show_pr_comments" },
                ],
              },
            ]}
          />
        </Section>

        <Section title="Steps">
          <StepsView
            title="Onboarding checklist"
            items={[
              {
                title: "Connect your Google account",
                description: "Grant calendar and email access.",
                status: "complete",
              },
              {
                title: "Set your work hours",
                description: "Tell GAIA when you're available.",
                status: "active",
              },
              {
                title: "Add your first integration",
                description: "Slack, Notion, or Linear.",
                status: "pending",
              },
              { title: "Invite a teammate", status: "pending" },
            ]}
          />
        </Section>

        {/* ---------------------------------------------------------------- */}
        {/* Code                                                              */}
        {/* ---------------------------------------------------------------- */}

        <Section title="CodeDiff">
          <CodeDiffView
            filename="greet.ts"
            oldCode={`function greet(name: string) {
  return "Hello " + name;
}`}
            newCode={`function greet(name: string): string {
  return \`Hello, \${name}!\`;
}`}
          />
        </Section>

        {/* ---------------------------------------------------------------- */}
        {/* Documents                                                         */}
        {/* ---------------------------------------------------------------- */}

        <Section title="TextDocument">
          <TextDocumentView
            title="Weekly Report"
            body="<h2>Summary</h2><p>This week the team shipped the OpenUI primitives revamp and reduced the backend prompt size by 30%. Performance benchmarks improved by 18% after the chart margin rewrite.</p><h2>Highlights</h2><ul><li>OpenUI component library synced with backend</li><li>Demo page now covers every registered component</li><li>Anonymous Pro replaced with Geist Mono across the app</li></ul><h2>Next Week</h2><p>Focus shifts to the scalability audit findings and shadcn-style chart polish.</p>"
            fields={[
              { label: "Author", value: "Aryan" },
              { label: "Period", value: "Apr 18 – Apr 24, 2026" },
              { label: "Word Count", value: "178" },
            ]}
          />
        </Section>

        {/* ---------------------------------------------------------------- */}
        {/* Layout containers                                                 */}
        {/* ---------------------------------------------------------------- */}

        <Section
          title="Layout containers"
          description="Stack, Card (card / sunk / clear variants), Grid, Row, Column, Separator. These are used by the LLM as composition wrappers — rendered here for visual reference."
        >
          <div className="space-y-4">
            <div className="rounded-2xl bg-zinc-800 p-4">
              <p className="text-xs text-zinc-400 mb-2">
                Card — variant="card" (zinc-800)
              </p>
              <div className="flex flex-col gap-3">
                <CardHeaderView title="Project Atlas" subtitle="3 open items" />
                <TagBlockView labels={["Active", "P1", "Engineering"]} />
              </div>
            </div>
            <div className="rounded-2xl bg-zinc-900 p-3">
              <p className="text-xs text-zinc-400 mb-2">
                Card — variant="sunk" (zinc-900)
              </p>
              <StatView value="$4.2K" label="MRR" trend="up" trendLabel="+8%" />
            </div>
            <div className="rounded-2xl p-3">
              <p className="text-xs text-zinc-400 mb-2">
                Card — variant="clear" (transparent, no border)
              </p>
              <CalloutView
                variant="info"
                title="Transparent container with no surface"
              />
            </div>

            <div className="w-full max-w-4xl">
              <div className="flex items-center gap-3">
                <div className="h-px flex-1 bg-zinc-700" />
                <span className="text-[11px] text-zinc-500 uppercase tracking-wide">
                  Separator with label
                </span>
                <div className="h-px flex-1 bg-zinc-700" />
              </div>
            </div>

            <div>
              <p className="text-xs text-zinc-400 mb-2">
                Grid — 3 columns of Stat
              </p>
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                <StatView value="128" label="Users" />
                <StatView value="42" label="Teams" />
                <StatView value="1.2K" label="Events" />
              </div>
            </div>

            <div>
              <p className="text-xs text-zinc-400 mb-2">
                Row — equal-width flex children (min 240px each)
              </p>
              <div className="flex flex-wrap gap-3 items-stretch">
                <div className="flex-1 min-w-[240px]">
                  <StatView value="23ms" label="P95" />
                </div>
                <div className="flex-1 min-w-[240px]">
                  <StatView value="99.9%" label="Uptime" />
                </div>
              </div>
            </div>

            <div>
              <p className="text-xs text-zinc-400 mb-2">
                Column + Stack — vertical grouping
              </p>
              <div className="flex flex-col gap-3">
                <CalloutView variant="success" title="All systems healthy." />
                <ProgressView value={72} label="Storage used" showValue />
              </div>
            </div>
          </div>
        </Section>

        {/* ---------------------------------------------------------------- */}
        {/* Complex compositions                                              */}
        {/* ---------------------------------------------------------------- */}

        <Section
          title="Composition — System health dashboard"
          description="Callout + Stat row + GaugeChart row + Progress list"
        >
          <div className="space-y-3">
            <CalloutView
              variant="warning"
              title="High memory usage detected on node-03."
              description="Consider scaling or restarting the process."
            />
            <div className="flex flex-wrap gap-3">
              <StatView value="99.8%" label="Uptime" trend="neutral" />
              <StatView
                value="23ms"
                label="P95 latency"
                trend="down"
                trendLabel="-4ms"
              />
              <StatView value="4 / 6" label="Nodes healthy" />
              <StatView
                value="$842"
                label="Cost today"
                trend="up"
                trendLabel="+12%"
              />
            </div>
            <div className="flex flex-wrap gap-3">
              <GaugeChartView
                value={62}
                title="CPU"
                min={0}
                max={100}
                unit="%"
              />
              <GaugeChartView
                value={89}
                title="Memory"
                min={0}
                max={100}
                unit="%"
              />
              <GaugeChartView
                value={41}
                title="Disk I/O"
                min={0}
                max={100}
                unit="%"
              />
            </div>
            <div className="space-y-2 max-w-md">
              <ProgressView value={62} label="CPU" showValue />
              <ProgressView
                value={89}
                label="Memory"
                color="danger"
                showValue
              />
              <ProgressView value={41} label="Disk I/O" showValue />
            </div>
          </div>
        </Section>

        <Section
          title="Composition — Pricing cards"
          description="CardHeader + TagBlock + Callout + Buttons per plan"
        >
          <div className="flex flex-wrap gap-3">
            <div className="rounded-2xl bg-zinc-800 p-4 flex flex-col gap-3 w-60">
              <CardHeaderView title="Free" subtitle="Get started at no cost" />
              <TagBlockView labels={["100 actions/mo", "1 workspace"]} />
              <ButtonView label="Get started" variant="flat" />
            </div>
            <div className="rounded-2xl bg-zinc-800 p-4 flex flex-col gap-3 w-60 border border-[#00bbff]/30">
              <CardHeaderView title="Pro" subtitle="$12 / month" />
              <CalloutView variant="info" title="Most popular plan" />
              <TagBlockView
                labels={[
                  "Unlimited actions",
                  "5 workspaces",
                  "Priority support",
                ]}
              />
              <ButtonView
                label="Start free trial"
                variant="primary"
                color="primary"
              />
            </div>
            <div className="rounded-2xl bg-zinc-800 p-4 flex flex-col gap-3 w-60">
              <CardHeaderView title="Enterprise" subtitle="Custom pricing" />
              <TagBlockView
                labels={["SSO + SAML", "SLA 99.99%", "Dedicated support"]}
              />
              <ButtonView label="Contact sales" variant="flat" />
            </div>
          </div>
        </Section>

        <Section
          title="Composition — GitHub PR feed"
          description="Timeline with full actor, links, status, and actions"
        >
          <TimelineView
            title="Recent pull requests"
            items={[
              {
                time: "2026-04-24T14:00:00",
                title: "feat(openui): add primitives revamp",
                actor: "aryanranderiya",
                status: "success",
                description: "Merged after 2 approvals. 47 files changed.",
                links: [
                  { label: "PR #648", url: "#", type: "primary" },
                  { label: "Diff", url: "#" },
                ],
              },
              {
                time: "2026-04-24T12:30:00",
                title: "fix(api): harden timezone resolution",
                actor: "janedoe",
                status: "warning",
                description: "Awaiting review from 1 more approver.",
                actions: [{ label: "Review", value: "review_pr_644" }],
                links: [{ label: "PR #644", url: "#", type: "primary" }],
              },
              {
                time: "2026-04-24T10:00:00",
                title: "fix(web): alias node built-ins in Turbopack",
                actor: "bobsmith",
                status: "neutral",
                description: "Draft — not ready for review.",
                links: [{ label: "PR #645", url: "#", type: "primary" }],
              },
            ]}
          />
        </Section>

        <Section
          title="Composition — Onboarding status"
          description="Steps + Callout + Avatar + TagBlock"
        >
          <div className="space-y-3">
            <div className="flex items-center gap-3">
              <AvatarView
                name="Aryan Randeriya"
                image="https://github.com/aryanranderiya.png"
              />
              <div>
                <CardHeaderView
                  title="Aryan Randeriya"
                  subtitle="aryanranderiya@gaia.app"
                />
              </div>
            </div>
            <TagBlockView labels={["Pro plan", "Admin", "2FA enabled"]} />
            <CalloutView
              variant="info"
              title="2 steps remaining to complete setup."
            />
            <StepsView
              items={[
                {
                  title: "Create your account",
                  status: "complete",
                },
                {
                  title: "Connect Google Workspace",
                  status: "complete",
                },
                {
                  title: "Invite your team",
                  description: "Add teammates to your workspace.",
                  status: "active",
                },
                {
                  title: "Set up integrations",
                  description: "Connect Slack, Notion, or Linear.",
                  status: "pending",
                },
              ]}
            />
          </div>
        </Section>
      </div>
    </div>
  );
}
