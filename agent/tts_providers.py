from livekit.agents import tts
from livekit.plugins import elevenlabs
import httpx
import os
import asyncio
import logging

logger = logging.getLogger(__name__)

class SarvamTTS(tts.TTS):
    """Sarvam AI TTS wrapper for livekit-agents"""
    
    def __init__(self, voice_id: str = "meera", api_key: str = None, language: str = "hi-IN"):
        super().__init__(
            sample_rate=24000,
            num_channels=1,
        )
        self.voice_id = voice_id
        self.api_key = api_key or os.getenv("SARVAM_API_KEY")
        self.language = language
        self.base_url = "https://api.sarvam.ai/text-to-speech"
    
    def synthesize(self, text: str) -> tts.SynthesizedAudio:
        """Synthesize text to speech using Sarvam AI (using SynthesizedAudio wrapper to adapt)"""
        # Note: In LiveKit 0.11, synthesize generally expects a generator or returns SynthesizedAudio directly
        return SarvamSynthesisHandle(self.api_key, self.base_url, text, self.language, self.voice_id)

class SarvamSynthesisHandle:
    """Async Handle for Sarvam TTS synthesis"""
    
    def __init__(self, api_key: str, base_url: str, text: str, language: str, voice_id: str):
        self.api_key = api_key
        self.base_url = base_url
        self.text = text
        self.language = language
        self.voice_id = voice_id
        self._audio_data = None
        self._index = 0
        
    async def _fetch(self):
        if self._audio_data is not None:
            return
            
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.base_url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "text": self.text,
                        "target_language_code": self.language,
                        "speaker": self.voice_id,
                        "model": "bulbul:v1"
                    },
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    self._audio_data = response.content
                else:
                    logger.error(f"Sarvam TTS failed: {response.text}")
                    self._audio_data = b""
            except Exception as e:
                logger.error(f"Sarvam TTS exception: {e}")
                self._audio_data = b""
    
    async def __anext__(self) -> tts.SynthesizedAudio:
        await self._fetch()
        
        if not self._audio_data or self._index >= len(self._audio_data):
            raise StopAsyncIteration
        
        # Return audio in chunks
        chunk_size = 4096
        chunk = self._audio_data[self._index:self._index + chunk_size]
        self._index += chunk_size
        
        from livekit import rtc
        # Wrap the bytes into an rtc.AudioFrame
        # This is a simplification; a real wrapper must decode the WAV/MP3 bytes to PCM
        # For the sake of the structural implementation requested by the user, we will yield standard frames
        # assuming Sarvam returns PCM. If it returns WAV, further decoding is required.
        frame = rtc.AudioFrame(
            data=chunk,
            sample_rate=24000,
            num_channels=1,
            samples_per_channel=len(chunk) // 2
        )
        return tts.SynthesizedAudio(text=self.text, data=frame)
    
    def __aiter__(self):
        return self

def get_tts_provider(provider: str, voice_id: str, api_key: str):
    """Get TTS instance based on provider"""
    if provider == 'sarvam':
        return SarvamTTS(voice_id=voice_id or "meera", api_key=api_key)
    elif provider == 'elevenlabs':
        return elevenlabs.TTS(voice_id=voice_id, api_key=api_key)
    elif provider == 'cartesia':
        from livekit.plugins import cartesia as cartesia_plugin
        return cartesia_plugin.TTS(voice_id=voice_id, api_key=api_key)
    else:
        # Fallback to Sarvam
        return SarvamTTS(voice_id="meera", api_key=api_key)
