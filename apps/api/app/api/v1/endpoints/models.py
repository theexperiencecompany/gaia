from fastapi import APIRouter

router = APIRouter(prefix="/chat-models", tags=["models"])

# Model selection and listing endpoints removed — a single default model is used
# for all users. Model configuration is handled via DEFAULT_MODEL_NAME in
# app/constants/llm.py.
