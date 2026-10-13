"use client";

import dynamic from "next/dynamic";

// EmailComposeCard pulls in zod (~260KB), DOMPurify, and the full mail API,
// none needed until the demo renders it. next/dynamic with { ssr: false } only
// works in a Client Component, so this loader is the boundary for DemoFinalCards.tsx.
const EmailComposeCard = dynamic(
  () => import("@/features/mail/components/EmailComposeCard"),
  { ssr: false },
);

export default EmailComposeCard;
