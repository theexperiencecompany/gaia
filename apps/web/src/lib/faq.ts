import { generateFAQSchema } from "./seo";

export interface FAQItem {
  question: string;
  answer: string;
}

/**
 * Homepage FAQ subset — consumed by BOTH the visible accordion and the
 * homepage FAQ JSON-LD schema. Always source both from this list so the
 * rich snippet never drifts from what visitors actually see.
 */
export const homepageFAQs: FAQItem[] = [
  {
    question: "Is this just another chatbot like ChatGPT?",
    answer:
      "No. ChatGPT waits for you to ask. GAIA watches your inbox, calendar, and tools, and acts before you ask: drafting replies, scheduling meetings, and closing tasks on its own. Less chatbot, more teammate who actually does the work.",
  },
  {
    question: "Can GAIA really run my whole day?",
    answer:
      "Yes, that's the point. Every morning GAIA sends you a briefing: the two or three things that need you, and the list it's planning to handle itself. Approve with one tap and it gets to work drafting, scheduling, and following up, then reports back in the evening with what got done. Anything outward-facing waits for your OK first.",
  },
  {
    question: "What does that look like on a normal day?",
    answer:
      'You wake up to a briefing instead of forty unread emails. GAIA has already drafted the replies that need answers, moved the meeting that clashed, and prepped notes for your 10 AM. During the day you text it things as they come up, like "chase the invoice" or "find time with Sarah next week", and they just get done.',
  },
  {
    question: "Do I need to be technical to use this?",
    answer:
      'No. If you can send a text, you can use GAIA. You write in plain English, like "plan my mum\'s visit next month", and GAIA does the research, books the calendar, and sets the reminders. Connecting your apps is one click each. No setup, no code.',
  },
  {
    question: "Is my personal data safe?",
    answer:
      "Yes. We never train on your data, never sell it, and never share it with model providers. GAIA is open source, so every line of code that touches your data is inspectable. And if you want total control, you can self-host the whole thing.",
  },
  {
    question: "Can I talk to a real human?",
    answer:
      "Yes. Email support@heygaia.io, or reach our founder Aryan directly at aryan@heygaia.io. He reads every email. There's also an active Discord and WhatsApp community. Most replies go out within 24 to 48 hours, often faster.",
  },
];

/**
 * Full FAQ list — /faq page and pricing. Homepage questions first, then the
 * deeper cuts (competitor comparisons, personas, memory) that earn their
 * place on dedicated pages but not on the homepage.
 */
export const faqData: FAQItem[] = [
  ...homepageFAQs,
  {
    question: "How is GAIA different from Claude Cowork?",
    answer:
      "Claude Cowork runs on your desktop. You install it and give it tasks to run on your laptop. It can't do anything without a prompt, it can't be messaged from WhatsApp or Slack, and when you close your laptop it stops. GAIA runs in the cloud. You text it from WhatsApp, Telegram, Slack, Discord, or the web, and it watches your inbox and calendar on its own so it can surface things before you ask.",
  },
  {
    question: "How is GAIA different from OpenClaw?",
    answer:
      "OpenClaw is a kit. You run your own agent on your own machine with your own credentials, then figure out what to build. Fun for developers, a security headache for everyone else. GAIA is the finished product: cloud hosted, with 50+ integrations wired up and workflows that work from day one.",
  },
  {
    question: "Who is GAIA for?",
    answer:
      "Anyone who spends too much time managing their digital life. Students use GAIA to turn assignment emails into full project setups with docs and deadlines. Professionals use it to get out from under the email and meeting grind. Founders use it to keep multiple projects moving without dropping context. If you want an assistant that does the work instead of talking about the work, GAIA is for you.",
  },
  {
    question:
      "How is this different from Siri, Google Assistant, or existing AI tools?",
    answer:
      "Voice assistants are basically search with a microphone. They forget you exist between questions. GAIA remembers everything about you: your work, your relationships, your goals. It connects your apps, runs multi-step workflows, and gets sharper the longer you use it. Less smart speaker, more digital teammate who knows you personally.",
  },
  {
    question: "How does GAIA learn my preferences?",
    answer:
      "GAIA keeps persistent memory across conversations. It picks up your work style, your important people, your recurring patterns, and the way you write. Over time it drafts replies that sound like you and surfaces the things you actually care about. You can see and edit what it remembers at any time.",
  },
  {
    question: "Is GAIA free?",
    answer:
      "Yes, there is a free tier that covers email automation, calendar management, and todos. Pro starts at $20 a month for higher limits and priority support. Enterprise is available for teams that need SSO, custom integrations, and dedicated support. You can also self-host the whole thing for zero cost on your own infrastructure.",
  },
];

/**
 * Generate FAQ schema from the centralized FAQ data
 */
export function getFAQSchema() {
  return generateFAQSchema(faqData);
}

/**
 * Get all FAQs
 */
export function getAllFAQs(): FAQItem[] {
  return faqData;
}
