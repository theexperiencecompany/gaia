/**
 * useChat Hook
 * Manages chat state and message handling
 */

import { useCallback, useRef, useState } from 'react';
import { FlatList } from 'react-native';
import { getAIResponse } from '../services/ai-service';
import { Message } from '../types';

export function useChat() {
    const [messages, setMessages] = useState<Message[]>([]);
    const [isTyping, setIsTyping] = useState(false);
    const flatListRef = useRef<FlatList>(null);

    const scrollToBottom = useCallback(() => {
        if (messages.length > 0) {
            setTimeout(() => {
                flatListRef.current?.scrollToEnd({ animated: true });
            }, 100);
        }
    }, [messages.length]);

    const sendMessage = useCallback(async (text: string) => {
        // Add user message
        const userMessage: Message = {
            id: Date.now().toString(),
            text,
            isUser: true,
            timestamp: new Date(),
        };

        setMessages(prev => [...prev, userMessage]);
        setIsTyping(true);

        try {
            // Get AI response
            const aiResponseText = await getAIResponse(text);

            const aiMessage: Message = {
                id: (Date.now() + 1).toString(),
                text: aiResponseText,
                isUser: false,
                timestamp: new Date(),
            };

            setMessages(prev => [...prev, aiMessage]);
        } catch (error) {
            console.error('Error getting AI response:', error);
        } finally {
            setIsTyping(false);
        }
    }, []);

    const clearMessages = useCallback(() => {
        setMessages([]);
    }, []);

    return {
        messages,
        isTyping,
        flatListRef,
        sendMessage,
        clearMessages,
        scrollToBottom,
    };
}
