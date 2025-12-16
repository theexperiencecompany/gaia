/**
 * Chat Module Exports
 * Central export point for all chat components
 */

// Main screen
export { ChatScreen } from './chat-screen';

// Core components
export { ChatHistory } from './chat-history';
export { ChatInput } from './chat-input';
export { ChatMessage } from './chat-message';
export { Sidebar } from './sidebar';
export { SidebarFooter } from './sidebar-footer';
export { SidebarHeader } from './sidebar-header';

// Sub-components
export { ChatEmptyState } from './components/chat-empty-state';
export { ChatHeader } from './components/chat-header';
export { ModelSelector } from './components/model-selector';
export { SuggestionCard } from './components/suggestion-card';

// Hooks
export { useChat, useSidebar, ChatProvider, useChatContext } from './hooks';

// Types
export type { ChatSession, ChatState, Message, Suggestion } from './types';

// Services
export { getAIResponse } from './services/ai-service';

// Data
export { AI_MODELS, DEFAULT_MODEL } from './data/models';
export { DEFAULT_SUGGESTIONS } from './data/suggestions';

