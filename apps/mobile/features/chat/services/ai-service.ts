/**
 * AI Service
 * Handles communication with AI backend
 */

/**
 * Mock AI response function - replace with actual AI integration
 */
export const getAIResponse = async (userMessage: string): Promise<string> => {
    // Simulate API delay
    await new Promise(resolve => setTimeout(resolve, 1000));

    // Simple mock responses
    const responses = [
        "I'm here to help! How can I assist you today?",
        "That's an interesting question. Let me think about that...",
        "I understand. Could you provide more details?",
        "Great question! Here's what I think...",
    ];

    return responses[Math.floor(Math.random() * responses.length)];
};
