import type { Metadata } from "next";

import ChatPage from "@/features/chat/components/interface/ChatPage";

export const metadata: Metadata = {
  title: "New chat",
  description:
    "Start a new conversation with GAIA, your AI assistant designed to help with tasks, answer questions, and boost productivity.",
  openGraph: {
    title: "New chat",
    siteName: "GAIA - Personal Assistant",
    url: "https://heygaia.io/chat/new",
    type: "website",
    description:
      "Start a new conversation with GAIA, your AI assistant designed to help with tasks, answer questions, and boost productivity.",
    images: ["og-image.webp"],
  },
  twitter: {
    card: "summary_large_image",
    title: "New chat",
    description:
      "Start a new conversation with GAIA, your AI assistant designed to help with tasks, answer questions, and boost productivity.",
    images: ["og-image.webp"],
  },
  keywords: [
    "GAIA",
    "AI chat",
    "AI Assistant",
    "Chatbot",
    "AI Personal Assistant",
    "Conversational AI",
    "Virtual Assistant",
    "Smart AI",
    "Productivity AI",
  ],
};

export default function CreateNewChatPage() {
  return <ChatPage />;
}
