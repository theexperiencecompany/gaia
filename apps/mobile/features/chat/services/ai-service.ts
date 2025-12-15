/**
 * AI Service
 * Handles communication with AI backend
 */

/**
 * Mock AI response function - replace with actual AI integration
 * @param userMessage - The user's message
 * @param chatId - The chat session ID for backend context
 */
export const getAIResponse = async (userMessage: string, chatId: string): Promise<string> => {
    // Simulate API delay
    await new Promise(resolve => setTimeout(resolve, 1000));

    // In production, send chatId to backend:
    // const response = await fetch('/api/chat', {
    //   method: 'POST',
    //   body: JSON.stringify({ message: userMessage, chatId }),
    // });
    // return response.json();

    // Simple mock responses
    const responses = [
        "I'm here to help! How can I assist you today?",
        "That's an interesting question. Let me think about that...",
        "I understand. Could you provide more details?",
        "Great question! Here's what I think...",
    ];

    return responses[Math.floor(Math.random() * responses.length)];
};
