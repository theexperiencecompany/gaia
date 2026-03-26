"use client";

import Image from "next/image";
import type React from "react";
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
  CodeDiffView,
  ComparisonTableView,
  DataCardView,
  FileTreeView,
  GaugeChartView,
  ImageBlockView,
  ImageGalleryView,
  KbdBlockView,
  LineChartView,
  MapBlockView,
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

// ── Chat layout primitives ─────────────────────────────────────────────────────

/** Mirrors the user bubble from ChatBubbleUser */
function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex w-full justify-end gap-3">
      <div className="flex items-end gap-1">
        <div className="chat_bubble_container user">
          <div className="imessage-bubble imessage-from-me imessage-grouped-last">
            <div className="flex max-w-[30vw] text-wrap whitespace-pre-wrap select-text text-sm">
              {text}
            </div>
          </div>
        </div>
        <div className="min-w-10">
          <div className="h-[35px] w-[35px] rounded-full bg-zinc-700 flex items-center justify-center text-xs font-semibold text-zinc-300">
            U
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * Mirrors ChatBubbleBot + TextBubble layout.
 * - textBefore: optional text shown in an iMessage bubble above the card
 * - textAfter: optional text shown in an iMessage bubble below the card
 * - children: the OpenUI card component (renders in .chat_bubble_container, no bubble wrapper)
 */
function BotMessage({
  textBefore,
  textAfter,
  children,
}: {
  textBefore?: string;
  textAfter?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="relative flex flex-col">
      <div className="flex items-end gap-1">
        {/* GAIA logo — mirrors the min-w-10 shrink-0 slot */}
        <div className="relative bottom-0 min-w-10 shrink-0">
          <Image
            alt="GAIA"
            src="/images/logos/logo.webp"
            width={30}
            height={30}
          />
        </div>

        {/* Content area — mirrors chatbubblebot_parent */}
        <div className="chatbubblebot_parent flex-1">
          <div className="flex w-full flex-col gap-2">
            <div className="chat_bubble_container">
              {textBefore && (
                <div className="imessage-bubble imessage-from-them imessage-grouped-last">
                  <div className="text-sm">{textBefore}</div>
                </div>
              )}
              {children}
              {textAfter && (
                <div className="imessage-bubble imessage-from-them imessage-grouped-last">
                  <div className="text-sm">{textAfter}</div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/** A full exchange: user question → bot card response */
function Exchange({
  name,
  userText,
  textBefore,
  textAfter,
  children,
}: {
  name: string;
  userText: string;
  textBefore?: string;
  textAfter?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-3">
      {/* Component name label */}
      <div className="flex items-center gap-2 px-1">
        <span className="font-mono text-[11px] font-semibold text-[#00bbff] bg-[#00bbff]/10 px-2 py-0.5 rounded-md">
          {name}
        </span>
        <div className="h-px flex-1 bg-zinc-800" />
      </div>

      {/* Simulated conversation */}
      <UserBubble text={userText} />
      <BotMessage textBefore={textBefore} textAfter={textAfter}>
        {children}
      </BotMessage>
    </section>
  );
}

function CategoryDivider({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3 pt-6">
      <span className="text-[10px] font-bold uppercase tracking-[0.15em] text-zinc-600">
        {label}
      </span>
      <div className="h-px flex-1 bg-zinc-800/60" />
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function OpenUIPreview() {
  return (
    <div className="min-h-screen bg-[#111111]">
      <div className="mx-auto max-w-3xl px-4 py-10 pb-32 space-y-8">
        <div className="space-y-1 pb-2">
          <h1 className="text-base font-semibold text-zinc-100">
            OpenUI Component Preview
          </h1>
          <p className="text-xs text-zinc-500">
            Each block shows a simulated chat exchange — user message on the
            right, bot card on the left — exactly as rendered in the chat UI.
          </p>
        </div>

        {/* ── DATA ── */}
        <CategoryDivider label="Data" />

        <Exchange name="DataCard" userText="Show me the details.">
          <DataCardView
            title="Item Details"
            fields={[
              { label: "Field A", value: "Value 1" },
              { label: "Field B", value: "Value 2" },
              { label: "Field C", value: "Value 3" },
              { label: "Field D", value: "Value 4" },
            ]}
          />
        </Exchange>

        <Exchange name="ComparisonTable" userText="Compare the two options.">
          <ComparisonTableView
            title="Option A vs Option B"
            leftLabel="Option A"
            rightLabel="Option B"
            rows={[
              {
                label: "Feature 1",
                left: "Yes",
                right: "Yes",
                highlight: true,
              },
              {
                label: "Feature 2",
                left: "No",
                right: "Yes",
                highlight: false,
              },
              {
                label: "Feature 3",
                left: "Basic",
                right: "Advanced",
                highlight: true,
              },
              {
                label: "Feature 4",
                left: "Yes",
                right: "Yes",
                highlight: false,
              },
            ]}
          />
        </Exchange>

        <Exchange
          name="ResultList"
          userText="Search for something."
          textBefore="Here are the results:"
        >
          <ResultListView
            title="Search Results"
            items={[
              {
                title: "Result One",
                subtitle: "source.com",
                body: "Description of the first result.",
                badge: "Tag A",
              },
              {
                title: "Result Two",
                subtitle: "source.com",
                body: "Description of the second result.",
                badge: "Tag B",
              },
              {
                title: "Result Three",
                subtitle: "source.com",
                body: "Description of the third result.",
              },
            ]}
          />
        </Exchange>

        <Exchange name="FileTree" userText="Show me the file structure.">
          <FileTreeView
            title="Project Files"
            items={[
              { path: "src/", type: "dir" },
              { path: "src/components/", type: "dir" },
              {
                path: "src/components/Button.tsx",
                type: "file",
                size: "1.2 KB",
              },
              {
                path: "src/components/Input.tsx",
                type: "file",
                size: "0.9 KB",
              },
              { path: "src/utils.ts", type: "file", size: "2.4 KB" },
              { path: "package.json", type: "file", size: "3.1 KB" },
            ]}
          />
        </Exchange>

        <Exchange name="TreeView" userText="Show me the hierarchy.">
          <TreeViewView
            title="Node Hierarchy"
            nodes={[
              {
                id: "root",
                label: "Root Node",
                description: "3 children",
                children: [
                  { id: "a", label: "Child A", description: "leaf" },
                  {
                    id: "b",
                    label: "Child B",
                    description: "2 children",
                    children: [
                      { id: "b1", label: "Child B1", description: "leaf" },
                      { id: "b2", label: "Child B2", description: "leaf" },
                    ],
                  },
                ],
              },
            ]}
          />
        </Exchange>

        {/* ── METRICS ── */}
        <CategoryDivider label="Metrics" />

        <Exchange name="StatRow" userText="What are the key numbers?">
          <div className="flex flex-wrap gap-3">
            <StatRowView
              title="Metric Up"
              value={1240}
              trend="up"
              trendLabel="+12% vs last period"
            />
            <StatRowView
              title="Metric Down"
              value={340}
              unit="ms"
              trend="down"
              trendLabel="Faster by 8%"
            />
            <StatRowView
              title="Metric Flat"
              value="99.9%"
              trend="neutral"
              trendLabel="No change"
            />
          </div>
        </Exchange>

        <Exchange name="NumberTicker" userText="Show me live counts.">
          <div className="flex flex-wrap gap-3">
            <NumberTickerView value={84293} label="Count A" duration={1200} />
            <NumberTickerView value={1430} label="Count B" />
            <NumberTickerView
              value={99.9}
              label="Count C"
              unit="%"
              duration={800}
            />
          </div>
        </Exchange>

        <Exchange name="ProgressList" userText="What's the progress?">
          <ProgressListView
            title="Progress Breakdown"
            items={[
              { label: "Item A", value: 100, max: 100, color: "success" },
              { label: "Item B", value: 72, max: 100, color: "primary" },
              { label: "Item C", value: 45, max: 100, color: "warning" },
              { label: "Item D", value: 20, max: 100, color: "danger" },
            ]}
          />
        </Exchange>

        <Exchange name="GaugeChart" userText="Show system usage.">
          <div className="flex flex-wrap gap-3">
            <GaugeChartView
              title="Gauge Low"
              value={25}
              min={0}
              max={100}
              unit="%"
              thresholds={{ warning: 60, danger: 80 }}
            />
            <GaugeChartView
              title="Gauge Mid"
              value={70}
              min={0}
              max={100}
              unit="%"
              thresholds={{ warning: 60, danger: 80 }}
            />
            <GaugeChartView
              title="Gauge High"
              value={90}
              min={0}
              max={100}
              unit="%"
              thresholds={{ warning: 60, danger: 80 }}
            />
          </div>
        </Exchange>

        {/* ── CHARTS ── */}
        <CategoryDivider label="Charts" />

        <Exchange name="BarChart (single)" userText="Show monthly revenue.">
          <BarChartView
            title="Monthly Revenue"
            data={[
              { month: "Jan", revenue: 4200 },
              { month: "Feb", revenue: 5100 },
              { month: "Mar", revenue: 4800 },
              { month: "Apr", revenue: 6200 },
              { month: "May", revenue: 5900 },
            ]}
            xKey="month"
            yKeys={["revenue"]}
          />
        </Exchange>

        <Exchange
          name="BarChart (multi-series)"
          userText="Compare revenue vs cost by quarter."
        >
          <BarChartView
            title="Revenue vs Cost"
            data={[
              { quarter: "Q1", revenue: 14200, cost: 8800 },
              { quarter: "Q2", revenue: 18100, cost: 10200 },
              { quarter: "Q3", revenue: 16800, cost: 9400 },
              { quarter: "Q4", revenue: 21500, cost: 11800 },
            ]}
            xKey="quarter"
            yKeys={["revenue", "cost"]}
            colors={["#00bbff", "#f472b6"]}
          />
        </Exchange>

        <Exchange
          name="LineChart (multi-series)"
          userText="Show traffic and errors over the week."
        >
          <LineChartView
            title="Traffic This Week"
            data={[
              { day: "Mon", requests: 1200, errors: 23, latency: 145 },
              { day: "Tue", requests: 1450, errors: 18, latency: 132 },
              { day: "Wed", requests: 980, errors: 45, latency: 178 },
              { day: "Thu", requests: 1680, errors: 12, latency: 121 },
              { day: "Fri", requests: 2100, errors: 31, latency: 156 },
              { day: "Sat", requests: 890, errors: 8, latency: 98 },
              { day: "Sun", requests: 720, errors: 5, latency: 87 },
            ]}
            xKey="day"
            yKeys={["requests", "errors", "latency"]}
            colors={["#00bbff", "#f87171", "#fbbf24"]}
          />
        </Exchange>

        <Exchange
          name="AreaChart (multi-series)"
          userText="Show user growth by platform."
        >
          <AreaChartView
            title="User Growth by Platform"
            data={[
              { month: "Jan", web: 800, mobile: 400, desktop: 200 },
              { month: "Feb", web: 1200, mobile: 650, desktop: 280 },
              { month: "Mar", web: 1900, mobile: 980, desktop: 350 },
              { month: "Apr", web: 2400, mobile: 1400, desktop: 420 },
              { month: "May", web: 3100, mobile: 1900, desktop: 510 },
            ]}
            xKey="month"
            yKeys={["web", "mobile", "desktop"]}
            colors={["#00bbff", "#34d399", "#a78bfa"]}
          />
        </Exchange>

        <Exchange
          name="AreaChart (single)"
          userText="Show total signups over time."
        >
          <AreaChartView
            title="Total Signups"
            data={[
              { month: "Jan", signups: 120 },
              { month: "Feb", signups: 190 },
              { month: "Mar", signups: 280 },
              { month: "Apr", signups: 390 },
              { month: "May", signups: 530 },
              { month: "Jun", signups: 710 },
            ]}
            xKey="month"
            yKeys={["signups"]}
          />
        </Exchange>

        <Exchange name="PieChart" userText="Show browser usage breakdown.">
          <PieChartView
            title="Browser Usage"
            data={[
              { browser: "Chrome", share: 65 },
              { browser: "Safari", share: 18 },
              { browser: "Firefox", share: 10 },
              { browser: "Edge", share: 5 },
              { browser: "Other", share: 2 },
            ]}
            nameKey="browser"
            valueKey="share"
          />
        </Exchange>

        <Exchange
          name="ScatterChart"
          userText="Show correlation between study hours and scores."
        >
          <ScatterChartView
            title="Study Hours vs Score"
            data={[
              { hours: 1, score: 42 },
              { hours: 2, score: 58 },
              { hours: 3, score: 65 },
              { hours: 5, score: 78 },
              { hours: 6, score: 82 },
              { hours: 8, score: 91 },
              { hours: 10, score: 95 },
            ]}
            xKey="hours"
            yKey="score"
          />
        </Exchange>

        <Exchange
          name="RadarChart (multi-series)"
          userText="Compare skill profiles for Alice and Bob."
        >
          <RadarChartView
            title="Skill Comparison"
            data={[
              { skill: "Frontend", alice: 90, bob: 65 },
              { skill: "Backend", alice: 70, bob: 95 },
              { skill: "DevOps", alice: 55, bob: 85 },
              { skill: "Design", alice: 80, bob: 40 },
              { skill: "Testing", alice: 75, bob: 70 },
              { skill: "Leadership", alice: 85, bob: 60 },
            ]}
            angleKey="skill"
            valueKeys={["alice", "bob"]}
            colors={["#00bbff", "#f472b6"]}
          />
        </Exchange>

        <Exchange
          name="RadarChart (single)"
          userText="Show my skill breakdown."
        >
          <RadarChartView
            title="Your Skills"
            data={[
              { skill: "React", score: 92 },
              { skill: "TypeScript", score: 88 },
              { skill: "Python", score: 75 },
              { skill: "SQL", score: 70 },
              { skill: "Design", score: 60 },
            ]}
            angleKey="skill"
            valueKeys={["score"]}
          />
        </Exchange>

        {/* ── STATUS & ALERTS ── */}
        <CategoryDivider label="Status & Alerts" />

        <Exchange
          name="StatusCard"
          userText="What's the current status?"
          textBefore="Here's a summary:"
        >
          <div className="space-y-2">
            <StatusCardView
              title="Success state"
              status="success"
              message="Operation completed."
              detail="Details line"
            />
            <StatusCardView
              title="Error state"
              status="error"
              message="Something went wrong."
              detail="Error code: ERR_001"
            />
            <StatusCardView
              title="Warning state"
              status="warning"
              message="Approaching limit."
            />
            <StatusCardView
              title="Info state"
              status="info"
              message="Update available."
            />
            <StatusCardView
              title="Pending state"
              status="pending"
              message="Processing..."
            />
          </div>
        </Exchange>

        <Exchange name="AlertBanner" userText="Any system alerts?">
          <div className="space-y-2">
            <AlertBannerView
              variant="info"
              title="Info banner"
              description="Informational message."
            />
            <AlertBannerView
              variant="success"
              title="Success banner"
              description="Action completed successfully."
            />
            <AlertBannerView
              variant="warning"
              title="Warning banner"
              description="Please review before continuing."
            />
            <AlertBannerView
              variant="error"
              title="Error banner"
              description="Something failed. Try again."
            />
          </div>
        </Exchange>

        {/* ── NAVIGATION & LAYOUT ── */}
        <CategoryDivider label="Navigation & Layout" />

        <Exchange name="Accordion" userText="Show me the FAQ.">
          <AccordionView
            title="Frequently Asked Questions"
            items={[
              {
                label: "Question 1?",
                content: "Answer to question one goes here.",
              },
              {
                label: "Question 2?",
                content: "Answer to question two goes here.",
              },
              {
                label: "Question 3?",
                content: "Answer to question three goes here.",
              },
            ]}
          />
        </Exchange>

        <Exchange name="TabsBlock" userText="Show me the tabs.">
          <TabsBlockView
            tabs={[
              {
                label: "Tab 1",
                content:
                  "Content for the first tab. Lorem ipsum dolor sit amet.",
              },
              {
                label: "Tab 2",
                content: "Content for the second tab. Different content here.",
              },
              {
                label: "Tab 3",
                content: "Content for the third tab. More information.",
              },
            ]}
          />
        </Exchange>

        <Exchange name="Steps" userText="Walk me through the steps.">
          <StepsView
            title="Step-by-step Guide"
            items={[
              {
                title: "Step 1",
                description: "Complete the first action.",
                status: "complete",
              },
              {
                title: "Step 2",
                description: "Now do this second thing.",
                status: "active",
              },
              {
                title: "Step 3",
                description: "This comes next.",
                status: "pending",
              },
              {
                title: "Step 4",
                description: "Final step to finish.",
                status: "pending",
              },
            ]}
          />
        </Exchange>

        <Exchange name="Timeline" userText="Show me the timeline.">
          <TimelineView
            title="Event Timeline"
            items={[
              {
                time: "2026-01-04T09:00:00Z",
                title: "Event A",
                description: "Description of event A.",
                status: "success",
              },
              {
                time: "2026-01-03T14:00:00Z",
                title: "Event B",
                description: "Description of event B.",
                status: "neutral",
              },
              {
                time: "2026-01-02T12:00:00Z",
                title: "Event C",
                description: "Description of event C.",
                status: "error",
              },
              {
                time: "2026-01-01T10:00:00Z",
                title: "Event D",
                description: "Description of event D.",
                status: "warning",
              },
            ]}
          />
        </Exchange>

        <Exchange name="Carousel" userText="Show me the cards.">
          <CarouselView
            items={[
              {
                title: "Card 1",
                body: "Content for card one.",
                badge: "Badge",
                actions: [{ label: "Action A", value: "action a" }],
              },
              {
                title: "Card 2",
                body: "Content for card two.",
                actions: [{ label: "Action B", value: "action b" }],
              },
              { title: "Card 3", body: "Content for card three." },
            ]}
          />
        </Exchange>

        {/* ── INTERACTIVE ── */}
        <CategoryDivider label="Interactive" />

        <Exchange name="ActionCard" userText="What should I do next?">
          <ActionCardView
            title="What would you like to do?"
            description="Choose an action to continue the conversation."
            actions={[
              {
                label: "Option A",
                type: "continue_conversation",
                value: "option a",
              },
              {
                label: "Option B",
                type: "continue_conversation",
                value: "option b",
              },
              {
                label: "Option C",
                type: "continue_conversation",
                value: "option c",
              },
            ]}
          />
        </Exchange>

        <Exchange name="SelectableList" userText="Which option should I pick?">
          <SelectableListView
            title="Select an option"
            description="Pick the one that fits best."
            options={[
              {
                label: "Option 1",
                description: "Description for option 1",
                value: "1",
                badge: "Recommended",
              },
              {
                label: "Option 2",
                description: "Description for option 2",
                value: "2",
              },
              {
                label: "Option 3",
                description: "Description for option 3",
                value: "3",
              },
            ]}
          />
        </Exchange>

        <Exchange name="CalendarMini" userText="Show me upcoming events.">
          <CalendarMiniView
            title="Month View"
            markedDates={[
              { date: "2026-03-10", label: "Event A", color: "success" },
              { date: "2026-03-18", label: "Event B", color: "warning" },
              { date: "2026-03-25", label: "Event C", color: "danger" },
            ]}
          />
        </Exchange>

        {/* ── DISPLAY ── */}
        <CategoryDivider label="Display" />

        <Exchange name="TagGroup" userText="What are the tags?">
          <TagGroupView
            title="Tag Group"
            tags={[
              { label: "Primary", color: "primary" },
              { label: "Success", color: "success" },
              { label: "Warning", color: "warning" },
              { label: "Danger", color: "danger" },
              { label: "Default", color: "default" },
            ]}
          />
        </Exchange>

        <Exchange
          name="AvatarList (with details)"
          userText="Who are the members?"
        >
          <AvatarListView
            title="Team Members"
            items={[
              {
                name: "Person A",
                role: "Lead",
                description: "Full-stack",
                initials: "PA",
                color: "#00bbff",
              },
              {
                name: "Person B",
                role: "Designer",
                description: "UI/UX",
                initials: "PB",
                color: "#34d399",
              },
              {
                name: "Person C",
                role: "Engineer",
                description: "Backend",
                initials: "PC",
                color: "#f472b6",
              },
            ]}
          />
        </Exchange>

        <Exchange name="AvatarList (compact)" userText="Who's online?">
          <AvatarListView
            title="Online Now"
            items={[
              { name: "Alice", initials: "A", color: "#00bbff" },
              { name: "Bob", initials: "B", color: "#34d399" },
              { name: "Carol", initials: "C", color: "#f472b6" },
              { name: "Dave", initials: "D", color: "#fb923c" },
              { name: "Eve", initials: "E", color: "#a78bfa" },
            ]}
          />
        </Exchange>

        <Exchange name="KbdBlock" userText="What are the keyboard shortcuts?">
          <KbdBlockView
            title="Keyboard Shortcuts"
            shortcuts={[
              { keys: ["⌘", "K"], description: "Open palette" },
              { keys: ["⌘", "Enter"], description: "Confirm action" },
              { keys: ["⌘", "N"], description: "New item" },
              { keys: ["Esc"], description: "Dismiss" },
            ]}
          />
        </Exchange>

        <Exchange
          name="ImageBlock"
          userText="Show me an image."
          textAfter="Let me know if you need a different image."
        >
          <ImageBlockView
            src="https://images.unsplash.com/photo-1677442135703-1787eea5ce01?w=800&q=80"
            alt="Placeholder image"
            caption="Image caption goes here."
          />
        </Exchange>

        <Exchange name="ImageGallery" userText="Show me some photos.">
          <ImageGalleryView
            images={[
              {
                src: "https://images.unsplash.com/photo-1677442135703-1787eea5ce01?w=400&q=80",
                alt: "Image 1",
                caption: "Caption 1",
              },
              {
                src: "https://images.unsplash.com/photo-1676299081847-824916de030a?w=400&q=80",
                alt: "Image 2",
                caption: "Caption 2",
              },
              {
                src: "https://images.unsplash.com/photo-1675271591211-126ad94e495d?w=400&q=80",
                alt: "Image 3",
                caption: "Caption 3",
              },
              {
                src: "https://images.unsplash.com/photo-1620712943543-bcc4688e7485?w=400&q=80",
                alt: "Image 4",
                caption: "Caption 4",
              },
              {
                src: "https://images.unsplash.com/photo-1535378917042-10a22c95931a?w=400&q=80",
                alt: "Image 5",
                caption: "Caption 5",
              },
            ]}
          />
        </Exchange>

        <Exchange name="MapBlock" userText="Where is it located?">
          <MapBlockView
            lat={37.7749}
            lng={-122.4194}
            label="Location Label"
            zoom={12}
          />
        </Exchange>

        <Exchange
          name="VideoBlock (YouTube)"
          userText="Show me a YouTube video."
        >
          <VideoBlockView
            src="https://www.youtube.com/watch?v=dQw4w9WgXcQ"
            title="YouTube Embed"
          />
        </Exchange>

        <Exchange name="VideoBlock (Vimeo)" userText="Show me a Vimeo video.">
          <VideoBlockView
            src="https://vimeo.com/148751763"
            title="Vimeo Embed"
          />
        </Exchange>

        <Exchange name="AudioPlayer" userText="Play the audio.">
          <AudioPlayerView
            src="https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3"
            title="Audio Title"
            description="Audio description goes here."
          />
        </Exchange>

        {/* ── CODE ── */}
        <CategoryDivider label="Code" />

        <Exchange
          name="CodeDiff (unified)"
          userText="Show me what changed in the config file."
        >
          <CodeDiffView
            filename="src/config.ts"
            oldCode={`export const API_URL = 'http://localhost:3000';
export const TIMEOUT = 5000;
export const MAX_RETRIES = 3;`}
            newCode={`export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:3000';
export const TIMEOUT = 10000;
export const MAX_RETRIES = 5;
export const RETRY_DELAY = 500;`}
            title="Config Update"
          />
        </Exchange>

        <Exchange
          name="CodeDiff (split)"
          userText="Show me the auth refactor side by side."
        >
          <CodeDiffView
            filename="auth.py"
            oldCode={`def login(user, pwd):
    if not user or not pwd:
        return False
    return check_credentials(user, pwd)

def logout(user):
    clear_session(user)`}
            newCode={`def login(user: str, pwd: str) -> bool:
    if not user or not pwd:
        raise ValueError("Missing credentials")
    return check_credentials(user, pwd)

def logout(user: str) -> None:
    clear_session(user)
    audit_log(user, "logout")`}
            title="Auth Refactor"
            diffStyle="split"
          />
        </Exchange>

        <Exchange
          name="CodeDiff (char diff, no header)"
          userText="Show the exact characters that changed."
        >
          <CodeDiffView
            filename="utils.ts"
            oldCode={`function formatDate(date: Date): string {
  return date.toLocaleDateString();
}

function formatCurrency(amount: number): string {
  return '$' + amount.toFixed(2);
}`}
            newCode={`function formatDate(date: Date, locale = 'en-US'): string {
  return date.toLocaleDateString(locale);
}

function formatCurrency(amount: number, currency = 'USD'): string {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(amount);
}`}
            lineDiffType="char"
            disableFileHeader={true}
            expandUnchanged={true}
          />
        </Exchange>
      </div>
    </div>
  );
}
