"use client";

import dynamic from "next/dynamic";

// EmailComposeCard pulls in zod (~260KB), DOMPurify, and the full mail API —
// none of which are needed until the demo actually renders the email card.
// next/dynamic with { ssr: false } is only valid inside a Client Component,
// so this loader acts as the client boundary for DemoFinalCards.tsx.
const EmailComposeCard = dynamic(
  () => import("@/features/mail/components/EmailComposeCard"),
  { ssr: false },
);

export default EmailComposeCard;
