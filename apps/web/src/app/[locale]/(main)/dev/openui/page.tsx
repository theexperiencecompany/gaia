"use client";

import { TextDocumentView } from "@/config/openui/components/document";

// ---------------------------------------------------------------------------
// Sample data
// ---------------------------------------------------------------------------

const EMAIL_BODY = `<p>Dear Sir/Ma'am,</p>
<p>I am submitting my Weekly Progress Report along with the IA2 poster for your review. Both documents have been attached to this email.</p>
<p>The report outlines the work completed during my internship period, including system design, development, and implementation details. The poster provides a concise overview of the project, covering motivation, methodology, and key outcomes.</p>
<p>Kindly let me know if any changes or additional information are required.</p>
<p>Thank you.</p>
<p>Regards,<br>Aryan Randeriya</p>`;

const REPORT_BODY = `<h2>Summary</h2><p>This report covers Q1 engineering milestones. All major deliverables were completed on schedule.</p><h2>Next Steps</h2><p>Review with the team and finalize the roadmap for Q2.</p>`;

const LONG_BODY = `<h2>Introduction</h2>
<p>This document serves as a comprehensive overview of the proposed system architecture for the next generation platform. It covers all major subsystems and their interactions.</p>
<h2>Background</h2>
<p>Over the past two years, the existing platform has struggled to scale beyond 10,000 concurrent users. Root cause analysis identified three bottlenecks: database connection pooling, synchronous task queues, and monolithic deployment units.</p>
<h2>Proposed Architecture</h2>
<p>The new architecture adopts a microservices approach with event-driven communication via RabbitMQ. Each service owns its data store and exposes a well-defined API contract.</p>
<h2>Services Breakdown</h2>
<p>The platform will be split into six core services: Auth, Users, Content, Notifications, Analytics, and Gateway. Each is independently deployable and horizontally scalable.</p>
<h2>Data Layer</h2>
<p>PostgreSQL remains the primary relational store. Redis handles caching and session state. MongoDB is introduced for unstructured content blobs. ChromaDB powers semantic search.</p>
<h2>Security Considerations</h2>
<p>All inter-service communication is mTLS-encrypted. JWTs are short-lived (15 minutes) with refresh token rotation. PII fields are encrypted at rest using AES-256.</p>
<h2>Migration Plan</h2>
<p>Phase 1 (Q2): Extract Auth and Users services. Phase 2 (Q3): Content and Notifications. Phase 3 (Q4): Analytics and Gateway cutover with full traffic migration.</p>
<h2>Risks</h2>
<p>Primary risk is data consistency during the dual-write migration window. Mitigation: feature flags per service, canary deployments, and automated rollback triggers on error rate thresholds.</p>
<h2>Timeline</h2>
<p>Target completion: Q4 2026. Team size: 6 engineers, 1 architect, 1 PM. Estimated effort: 2,400 engineering-hours across 9 months.</p>`;

// ---------------------------------------------------------------------------
// Code block — tokenised for readability
// ---------------------------------------------------------------------------

interface Token {
  text: string;
  color: string;
}

function tokenise(code: string): Token[] {
  const tokens: Token[] = [];
  // Walk char-by-char tracking state
  let i = 0;
  while (i < code.length) {
    // fence markers
    if (code.startsWith(":::", i)) {
      const end = code.indexOf("\n", i);
      const line = end === -1 ? code.slice(i) : code.slice(i, end + 1);
      tokens.push({ text: line, color: "text-zinc-500" });
      i += line.length;
      continue;
    }
    // string literals
    if (code[i] === '"') {
      let j = i + 1;
      while (j < code.length && code[j] !== '"') {
        if (code[j] === "\\") j++;
        j++;
      }
      tokens.push({ text: code.slice(i, j + 1), color: "text-amber-300" });
      i = j + 1;
      continue;
    }
    // keywords: root, null, true, false
    const kw = ["root", "null", "true", "false"];
    const matched = kw.find(
      (k) => code.startsWith(k, i) && !/\w/.test(code[i + k.length] ?? " "),
    );
    if (matched) {
      tokens.push({ text: matched, color: "text-blue-400" });
      i += matched.length;
      continue;
    }
    // component names (PascalCase word)
    const pascal = code.slice(i).match(/^[A-Z][a-zA-Z]+/);
    if (pascal) {
      tokens.push({ text: pascal[0], color: "text-purple-400" });
      i += pascal[0].length;
      continue;
    }
    // punctuation / operators: = ( ) [ ] , {  }
    if ("=()[]{},".includes(code[i])) {
      tokens.push({ text: code[i], color: "text-zinc-500" });
      i++;
      continue;
    }
    // everything else (whitespace, newlines, numbers)
    tokens.push({ text: code[i], color: "text-zinc-300" });
    i++;
  }
  return tokens;
}

interface CodeBlockProps {
  code: string;
}

function CodeBlock({ code }: CodeBlockProps) {
  const tokens = tokenise(code);
  return (
    <pre className="overflow-x-auto rounded-xl bg-zinc-900 p-4 text-xs leading-relaxed font-mono whitespace-pre-wrap">
      {tokens.map((t, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: static token list
        <span key={i} className={t.color}>
          {t.text}
        </span>
      ))}
    </pre>
  );
}

// ---------------------------------------------------------------------------
// Preview section
// ---------------------------------------------------------------------------

interface PreviewSectionProps {
  label: string;
  openui: string;
  children: React.ReactNode;
}

function PreviewSection({ label, openui, children }: PreviewSectionProps) {
  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs font-semibold uppercase tracking-widest text-zinc-500">
        {label}
      </p>
      {children}
      <CodeBlock code={openui} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Formatted OpenUI snippets (readable, not raw template literal)
// ---------------------------------------------------------------------------

const EMAIL_OPENUI = `:::openui
root = TextDocument(
  "Email",
  "<p>Dear Sir/Ma'am,</p><p>I am submitting my Weekly Progress Report...</p>",
  [
    {"label": "Subject", "value": "Submission: Weekly Progress Report and IA2 Poster"}
  ]
)
:::`;

const REPORT_OPENUI = `:::openui
root = TextDocument(
  "Report",
  "<h2>Summary</h2><p>Q1 milestones completed on schedule.</p><h2>Next Steps</h2><p>Finalize Q2 roadmap.</p>",
  [
    {"label": "Date",   "value": "April 11, 2026"},
    {"label": "Author", "value": "Aryan Randeriya"},
    {"label": "Status", "value": "Draft"}
  ]
)
:::`;

const LONG_OPENUI = `:::openui
root = TextDocument(
  "Architecture Proposal",
  "<h2>Introduction</h2><p>Comprehensive overview of the proposed system architecture...</p>",
  [
    {"label": "Author", "value": "Aryan Randeriya"},
    {"label": "Version", "value": "v0.3 Draft"},
    {"label": "Date",   "value": "April 12, 2026"}
  ]
)
:::`;

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function OpenUIPreviewPage() {
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-xl p-8">
        <p className="mb-8 text-xs font-medium uppercase tracking-widest text-zinc-500">
          OpenUI Preview — TextDocument
        </p>

        <div className="flex flex-col gap-10">
          <PreviewSection label="Email" openui={EMAIL_OPENUI}>
            <TextDocumentView
              title="Email"
              fields={[
                {
                  label: "Subject",
                  value: "Submission: Weekly Progress Report and IA2 Poster",
                },
              ]}
              body={EMAIL_BODY}
            />
          </PreviewSection>

          <PreviewSection label="Report" openui={REPORT_OPENUI}>
            <TextDocumentView
              title="Report"
              fields={[
                { label: "Date", value: "April 11, 2026" },
                { label: "Author", value: "Aryan Randeriya" },
                { label: "Status", value: "Draft" },
              ]}
              body={REPORT_BODY}
            />
          </PreviewSection>

          <PreviewSection
            label="Long content (scroll test)"
            openui={LONG_OPENUI}
          >
            <TextDocumentView
              title="Architecture Proposal"
              fields={[
                { label: "Author", value: "Aryan Randeriya" },
                { label: "Version", value: "v0.3 Draft" },
                { label: "Date", value: "April 12, 2026" },
              ]}
              body={LONG_BODY}
            />
          </PreviewSection>
        </div>
      </div>
    </div>
  );
}
