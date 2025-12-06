import { generateFAQSchema } from "./seo";

export interface FAQItem {
  question: string;
  answer: string;
}

export const faqData: FAQItem[] = [
  {
    question: "Is this just another chatbot like ChatGPT?",
    answer:
      "No. ChatGPT and other assistants are reactive - they wait for you to ask questions. GAIA is proactive - it watches your emails, calendar, and notifications to automatically draft replies, schedule meetings, create documents, set reminders, and handle tasks before you even think about them. It's like having a human assistant who actually does the work.",
  },
  {
    question: "Who is GAIA for?",
    answer:
      "GAIA is designed for anyone drowning in digital overwhelm. Students love it for automatically turning assignment emails into complete project setups with docs, deadlines, and research. Professionals use it to escape the endless cycle of email management and meeting coordination. Entrepreneurs rely on it to juggle multiple projects without losing focus on strategy. Whether you're a busy knowledge worker or someone managing complex workflows, GAIA is perfect if you want an AI that actually does the work instead of just chatting about it.",
  },
  {
    question: "What can GAIA actually do for me day-to-day?",
    answer:
      "GAIA automates your entire digital workflow: manages your Gmail and calendar, creates Google Docs and Sheets, handles goal tracking and to-dos, controls your browser for research tasks, processes assignment emails into complete project setups, and integrates with tools like Linear, GitHub, Todoist, and WhatsApp. When you get a college assignment email, GAIA automatically creates docs, sets deadlines, does research, and organizes everything - turning hours of setup into minutes.",
  },
  {
    question: "Is my personal data safe with GAIA?",
    answer:
      "Absolutely. We never train on your data or sell it to third parties - period. You can self-host GAIA completely (you control everything) or use our cloud version where your data stays encrypted and isolated. We're also open-source, so you can inspect every line of code. Your information stays yours, always.",
  },
  {
    question:
      "How is this different from Siri, Google Assistant, or existing AI tools?",
    answer:
      "Traditional assistants are glorified voice search that forget you exist between conversations. GAIA remembers everything about you - your work style, preferences, relationships, and goals - and gets smarter over time. It creates custom workflows, connects all your apps, and handles multi-step automation. Think less 'smart speaker' and more 'digital teammate who knows you personally.'",
  },
  {
    question: "Do I need to be technical to use this?",
    answer:
      "Not at all. GAIA works through natural conversation - just text it like you would a friend. You can start immediately with our web version or self-host with our guided installer. No coding required. Just say 'Help me plan mom's visit next month' and GAIA handles research, scheduling, document creation, and reminders automatically.",
  },
  {
    question: "Is GAIA free?",
    answer:
      "GAIA starts completely free with core features that handle email automation, calendar management, and task organization. Pro plans begin at $20/month and unlock higher usage limits, and priority support. For maximum privacy and control, you can self-host GAIA entirely free on your own infrastructure - no ongoing costs, complete data ownership.",
  },
  {
    question: "Can I talk to customer support?",
    answer:
      "Yes! We pride ourselves on genuine human support. Email support@heygaia.io for technical issues or reach our founder Aryan directly at aryan@heygaia.io - he personally reads every email. We also have active Discord and WhatsApp communities where you can get help from both our team and other users. Response time is typically 24-48 hours, often much faster.",
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
