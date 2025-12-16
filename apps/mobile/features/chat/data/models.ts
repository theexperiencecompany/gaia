/**
 * AI Models Data
 * Available AI models for selection
 */

import { AIModel } from '../types';

export const AI_MODELS: AIModel[] = [
    {
        id: 'gemini-2.0-flash',
        name: 'Gemini 2.0 Flash',
        provider: 'Gemini',
        icon: 'https://upload.wikimedia.org/wikipedia/commons/thumb/8/8a/Google_Gemini_logo.svg/240px-Google_Gemini_logo.svg.png',
    },
    {
        id: 'gemini-2.5-flash',
        name: 'Gemini 2.5 Flash',
        provider: 'Gemini',
        icon: 'https://upload.wikimedia.org/wikipedia/commons/thumb/8/8a/Google_Gemini_logo.svg/240px-Google_Gemini_logo.svg.png',
    },
    {
        id: 'gemini-2.5-pro',
        name: 'Gemini 2.5 Pro',
        provider: 'Gemini',
        isPro: true,
        icon: 'https://upload.wikimedia.org/wikipedia/commons/thumb/8/8a/Google_Gemini_logo.svg/240px-Google_Gemini_logo.svg.png',
    },
    {
        id: 'gpt-4o-mini',
        name: 'GPT-4o Mini',
        provider: 'OpenAI',
        isDefault: true,
        icon: 'https://upload.wikimedia.org/wikipedia/commons/thumb/0/04/ChatGPT_logo.svg/240px-ChatGPT_logo.svg.png',
    },
];

export const DEFAULT_MODEL = AI_MODELS.find(m => m.isDefault) || AI_MODELS[0];
