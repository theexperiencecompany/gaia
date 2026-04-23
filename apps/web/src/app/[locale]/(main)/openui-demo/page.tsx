"use client";

import { Divider } from "@heroui/divider";
import type React from "react";
import {
  AccordionView,
  AreaChartView,
  AvatarView,
  BarChartView,
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
  KbdBlockView,
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
  TabsBlockView,
  TagBlockView,
  TagView,
  TextContentView,
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

        <Section title="Avatar">
          <Row>
            <AvatarView
              name="Aryan Randeriya"
              image="https://github.com/aryanranderiya.png"
            />
            <AvatarView name="Jane Smith" />
            <AvatarView name="Bob" color="success" />
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
              <RadioView label="Pro — $12/mo" value="pro" />
              <RadioView label="Enterprise" value="enterprise" />
            </div>
          </Row>
        </Section>

        <Section
          title="Table"
          description="Col + Table are DSL-only primitives (use via :::openui). Demo shows rendered output."
        >
          <div className="rounded-2xl bg-zinc-900 p-3 text-xs text-zinc-400">
            <pre className="whitespace-pre-wrap">{`:::openui
root = Table([name, role, status], "Team")
name = Col("Name", ["Alice", "Bob", "Carol"])
role = Col("Role", ["Engineer", "Designer", "PM"])
status = Col("Status", ["active", "inactive", "active"], "badge")
:::`}</pre>
          </div>
        </Section>

        {/* ---------------------------------------------------------------- */}
        {/* Layout                                                            */}
        {/* ---------------------------------------------------------------- */}

        <Section title="CopyableContent">
          <Row>
            <CopyableContentView
              content="GAIA_API_KEY=gaia_sk_prod_abc123xyz"
              languageHint=".env"
            />
            <CopyableContentView
              content="npm install @gaia/sdk"
              mode="inline"
            />
          </Row>
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

        <Section title="TabsBlock">
          <TabsBlockView
            tabs={[
              {
                label: "Overview",
                content: "Key metrics and recent activity for your workspace.",
              },
              {
                label: "Members",
                content: "Manage team members, roles, and permissions.",
              },
              {
                label: "Billing",
                content: "View invoices and update your payment method.",
              },
            ]}
          />
        </Section>

        <Section title="KbdBlock">
          <KbdBlockView
            title="Keyboard shortcuts"
            shortcuts={[
              { keys: ["⌘", "K"], description: "Open command palette" },
              { keys: ["⌘", "Shift", "P"], description: "Quick actions" },
              { keys: ["⌘", "Z"], description: "Undo last change" },
              { keys: ["Esc"], description: "Close modal / dismiss" },
            ]}
          />
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
