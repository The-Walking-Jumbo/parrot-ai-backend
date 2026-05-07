import asyncio
import logging
from livekit import rtc
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    WorkerOptions,
    cli,
    llm,
)
from livekit.agents.voice_assistant import VoiceAssistant
from livekit.plugins import deepgram, silero
import os
import json
from datetime import datetime, timezone
import uuid

from core.database import db_client
from core.security import decrypt_value
from agent.tools import execute_pre_call_tools, execute_post_call_tools
from agent.tts_providers import get_tts_provider
from agent.llm_providers import get_llm_provider

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vobiz-agent")

async def entrypoint(ctx: JobContext):
    """Main entry point for each LiveKit room"""
    
    logger.info(f"Agent connecting to room: {ctx.room.name}")
    
    # Parse room metadata to get assistant config
    metadata = json.loads(ctx.room.metadata or "{}")
    org_id = metadata.get("org_id")
    assistant_id = metadata.get("assistant_id")
    call_id = metadata.get("call_id")
    
    # Auto connect to the room
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    
    if not all([org_id, assistant_id, call_id]):
        logger.error("Missing required metadata in room")
        return
    
    # Load assistant config from database
    result = await db_client.execute(
        "SELECT * FROM assistants WHERE id = ?",
        [assistant_id]
    )
    
    if not result.rows:
        logger.error(f"Assistant {assistant_id} not found")
        return
    
    assistant_data = dict(zip(result.columns, result.rows[0]))
    
    # Load AI provider credentials
    providers = {}
    provider_results = await db_client.execute(
        "SELECT provider_type, api_key_encrypted FROM ai_providers WHERE org_id = ? AND is_active = 1",
        [org_id]
    )
    
    for row in provider_results.rows:
        ptype, encrypted_key = row
        providers[ptype] = decrypt_value(encrypted_key)
    
    # Execute pre-call tools
    try:
        await execute_pre_call_tools(assistant_id, metadata)
    except Exception as e:
        logger.error(f"Pre-call tools failed: {e}")
    
    # Setup STT (always Deepgram)
    stt = deepgram.STT(api_key=providers.get('deepgram'))
    
    # Setup LLM (Groq or OpenAI)
    llm_provider = assistant_data['llm_provider'] or 'groq'
    llm_instance = get_llm_provider(
        provider=llm_provider,
        model=assistant_data['llm_model'],
        api_key=providers.get(llm_provider)
    )
    
    # Setup TTS (dynamic: Sarvam, ElevenLabs, or Cartesia)
    tts_provider = assistant_data['tts_provider'] or 'sarvam'
    tts = get_tts_provider(
        provider=tts_provider,
        voice_id=assistant_data['voice_id'],
        api_key=providers.get(tts_provider)
    )
    
    # Create voice assistant
    assistant = VoiceAssistant(
        vad=silero.VAD.load(),
        stt=stt,
        llm=llm_instance,
        tts=tts,
        chat_ctx=llm.ChatContext().append(
            role="system",
            text=assistant_data['system_prompt'] or "You are a helpful assistant."
        ),
    )
    
    # Start assistant
    assistant.start(ctx.room)
    
    # Send first message if configured
    if assistant_data.get('first_message'):
        await assistant.say(assistant_data['first_message'])
    
    # Save transcript in real-time
    @assistant.on("user_speech_committed")
    async def on_user_speech(text: str):
        await save_transcript(call_id, "user", text)
    
    @assistant.on("agent_speech_committed")
    async def on_agent_speech(text: str):
        await save_transcript(call_id, "assistant", text)
    
    # Monitor for room close
    while ctx.room.connection_state in [rtc.ConnectionState.CONN_CONNECTED, rtc.ConnectionState.CONN_CONNECTING]:
        await asyncio.sleep(1)
    
    # Room closed - execute post-call tools
    try:
        transcript = await get_full_transcript(call_id)
        await execute_post_call_tools(assistant_id, call_id, transcript, metadata)
    except Exception as e:
        logger.error(f"Post-call tools failed: {e}")

async def save_transcript(call_id: str, speaker: str, text: str):
    """Save transcript entry to database"""
    transcript_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()
    
    await db_client.execute(
        "INSERT INTO transcripts (id, call_id, speaker, text, timestamp) VALUES (?, ?, ?, ?, ?)",
        [transcript_id, call_id, speaker, text, timestamp]
    )
    logger.info(f"Saved transcript: {speaker}: {text}")

async def get_full_transcript(call_id: str) -> str:
    """Get full transcript as formatted string"""
    result = await db_client.execute(
        "SELECT speaker, text FROM transcripts WHERE call_id = ? ORDER BY timestamp ASC",
        [call_id]
    )
    
    lines = []
    for row in result.rows:
        speaker, text = row
        lines.append(f"{speaker.upper()}: {text}")
    
    return "\n".join(lines)

if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
        )
    )
