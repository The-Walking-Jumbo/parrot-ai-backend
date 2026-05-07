import os
import logging
from livekit.agents import llm
from groq import AsyncGroq

logger = logging.getLogger(__name__)

class GroqLLM(llm.LLM):
    """Custom Groq LLM wrapper for livekit-agents"""
    
    def __init__(self, model: str = "llama-3.3-70b-versatile", api_key: str = None):
        super().__init__()
        self.model = model
        self.client = AsyncGroq(api_key=api_key or os.getenv("GROQ_API_KEY"))
    
    def chat(self, chat_ctx: llm.ChatContext, **kwargs) -> llm.LLMStream:
        """Return an LLM stream which will yield chunks"""
        return GroqLLMStream(self.client, self.model, chat_ctx)


class GroqLLMStream(llm.LLMStream):
    """Stream wrapper for Groq responses"""
    
    def __init__(self, client: AsyncGroq, model: str, chat_ctx: llm.ChatContext):
        super().__init__()
        self.client = client
        self.model = model
        self.chat_ctx = chat_ctx
        self._stream = None
        
    async def _ensure_stream(self):
        if self._stream is None:
            messages = [
                {"role": msg.role, "content": msg.content}
                for msg in self.chat_ctx.messages
            ]
            self._stream = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True,
                temperature=0.7,
                max_tokens=1024,
            )

    async def __anext__(self):
        await self._ensure_stream()
        
        chunk = await self._stream.__anext__()
        
        # We need to loop here just in case Groq gives us chunks with empty content (like role chunks)
        while not chunk.choices[0].delta.content:
            chunk = await self._stream.__anext__()
            
        content = chunk.choices[0].delta.content
        return llm.ChatChunk(
            choices=[llm.Choice(delta=llm.ChoiceDelta(content=content))]
        )
            
    def __aiter__(self):
        return self

def get_llm_provider(provider: str, model: str, api_key: str):
    """Get LLM instance based on provider"""
    if provider == 'groq':
        return GroqLLM(model=model or "llama-3.3-70b-versatile", api_key=api_key)
    elif provider == 'openai':
        # Fallback to OpenAI if needed
        from livekit.plugins import openai as openai_plugin
        return openai_plugin.LLM(model=model or "gpt-4", api_key=api_key)
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")
