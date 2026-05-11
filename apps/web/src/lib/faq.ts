import { generateFAQSchema } from "./seo";

export interface FAQItem {
  question: string;
  answer: string;
}

export const faqData: FAQItem[] = [
  {
    question: "How is GAIA different from Claude Cowork?",
    answer:
      "Claude Cowork runs on your desktop. You install it and give it tasks to run on your laptop. It can't do anything without a prompt. It can't be messaged from WhatsApp or Slack. Close your laptop and it stops. GAIA runs in the cloud. You text it from WhatsApp Telegram Slack Discord or the web. It also watches your inbox and calendar on its own so it can surface things before you ask.",
  },
  {
    question: "How is GAIA different from OpenClaw?",
    answer:
      "OpenClaw is a kit. You run your own agent on your own machine with your own credentials and then figure out what to build. Fun for developers. A security headache for everyone else. GAIA is the finished product. It's cloud hosted with 50+ integrations wired up and workflows that work from day one.",
  },
  {
    question: "Is this just another chatbot like ChatGPT?",
    answer:
      "No. ChatGPT waits for you to ask. GAIA watches your inbox calendar and tools and acts before you ask. It drafts replies schedules meetings creates docs and closes tasks on its own. Think of it less as a chatbot and more as a teammate who actually does the work.",
  },
  {
    question: "Who is GAIA for?",
    answer:
      "Anyone who spends too much time managing their digital life. Students use GAIA to turn assignment emails into full project setups with docs and deadlines. Professionals use it to get out from under the email and meeting grind. Founders use it to keep multiple projects moving without dropping context. If you want an assistant that does the work instead of talking about the work GAIA is for you.",
  },
  {
    question: "What can GAIA actually do for me day to day?",
    answer:
      "GAIA runs your digital workflow. It handles Gmail and Google Calendar. It creates docs and sheets. It tracks goals and todos. It does research. It connects to Linear GitHub Todoist WhatsApp and 50+ other tools. Get an assignment email and GAIA spins up a doc sets deadlines does the research and organises everything. Hours of setup become minutes.",
  },
  {
    question: "Is my personal data safe with GAIA?",
    answer:
      "Yes. We never train on your data and we never sell it. You can use our cloud where your data stays encrypted and isolated or you can self host the whole thing on your own infrastructure. GAIA is open source so every line of code that touches your data is inspectable.",
  },
  {
    question: "Is my data used to train AI models?",
    answer:
      "No. Your data is yours. We do not train on it and we do not share it with model providers for training. If that still feels uncomfortable you can self host GAIA and route everything through your own infrastructure.",
  },
  {
    question: "How does GAIA learn my preferences?",
    answer:
      "GAIA keeps persistent memory across conversations. It picks up your work style your important people your recurring patterns and the way you write. Over time it drafts replies that sound like you and surfaces the things you actually care about. You can see and edit what it remembers at any time.",
  },
  {
    question:
      "How is this different from Siri Google Assistant or existing AI tools?",
    answer:
      "Voice assistants are basically search with a microphone. They forget you exist between questions. GAIA remembers everything about you. Your work your relationships your goals. It connects your apps runs multi step workflows and gets sharper the longer you use it. Less smart speaker more digital teammate who knows you personally.",
  },
  {
    question: "Do I need to be technical to use this?",
    answer:
      "No. Text GAIA like you would a friend. Start on the web or self host with a guided installer. No coding. Just say help me plan mum's visit next month and GAIA handles the research the scheduling the doc and the reminders.",
  },
  {
    question: "Is GAIA free?",
    answer:
      "Yes there is a free tier that covers email automation calendar management and todos. Pro starts at $20 a month for higher limits and priority support. Enterprise is available for teams that need SSO custom integrations and dedicated support. You can also self host the whole thing for zero cost on your own infrastructure.",
  },
  {
    question: "Can I talk to customer support?",
    answer:
      "Yes. Email support@heygaia.io or reach our founder Aryan directly at aryan@heygaia.io. He reads every email. We also run active Discord and WhatsApp communities. Most replies go out in 24 to 48 hours often faster.",
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
