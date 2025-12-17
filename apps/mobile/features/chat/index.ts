/**
 * Chat Feature Exports
 * Centralized exports for all chat-related components and utilities
 */

// Components
export { ChatInput } from './components/chat-input';
export { ChatMessage } from './components/chat-message';
export { ChatHistory } from './components/chat-history';
export { ChatHeader } from './components/chat-header';
export { ChatEmptyState } from './components/chat-empty-state';
export { SidebarContent, SIDEBAR_WIDTH } from './components/sidebar';
export { SidebarHeader } from './components/sidebar-header';
export { SidebarFooter } from './components/sidebar-footer';
export { ModelSelector } from './components/model-selector';
export { SuggestionCard } from './components/suggestion-card';

// Hooks
export { useChat, useSidebar } from './hooks';
export { useChatContext, ChatProvider } from './hooks/use-chat-context';

// Types
export type { ChatSession, ChatState, Message, Suggestion } from './types';

// Services
export { getAIResponse } from './services/ai-service';

// Data
export { AI_MODELS, DEFAULT_MODEL } from './data/models';
export { DEFAULT_SUGGESTIONS } from './data/suggestions';
