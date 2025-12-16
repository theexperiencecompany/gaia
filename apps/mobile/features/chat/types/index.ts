/**
 * Chat Types & Interfaces
 * Central type definitions for the chat module
 */

export interface Message {
    id: string;
    text: string;
    isUser: boolean;
    timestamp: Date;
}

export interface ChatSession {
    id: string;
    title: string;
    lastMessage?: string;
    timestamp: Date;
}

export interface Suggestion {
    id: string;
    iconUrl: string;
    text: string;
}

export interface ChatState {
    messages: Message[];
    isTyping: boolean;
    activeSessionId?: string;
}

export interface AIModel {
    id: string;
    name: string;
    provider: string;
    icon: string;
    isPro?: boolean;
    isDefault?: boolean;
}
