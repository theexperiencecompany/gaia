import "./page.css";
import "./page.2.css";
import "./page.3.css";
import "./page.4.css";
import "./page.5.css";
import "./page.6.css";
import "./page.7.css";
import "./page.8.css";
import "@/features/chat/components/interface/markdown.css";
import type { Metadata } from "next";

import ChatPage from "@/features/chat/components/interface/ChatPage";
import { generatePageMetadata } from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "New Chat",
  description:
    "Start a new conversation with GAIA, your AI assistant designed to help with tasks, answer questions, and boost productivity.",
  path: "/c",
  keywords: [
    "AI chat",
    "chatbot",
    "conversational AI",
    "new conversation",
    "AI personal assistant",
  ],
});

export default function CreateNewChatPage() {
  return <ChatPage />;
}
