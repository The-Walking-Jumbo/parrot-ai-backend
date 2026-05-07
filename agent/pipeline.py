from livekit.agents import JobContext, pipeline
from livekit.plugins import deepgram, openai, silero
from agent.tools import AgentTools

class VoicePipeline:
    def __init__(self, ctx: JobContext):
        self.ctx = ctx

    async def start(self):
        initial_ctx = pipeline.AgentContext(
            allow_swappable_models=True,
        )

        # Basic setup placeholder
        # In a real app, you'd fetch config from DB based on SIP attributes or job metadata
        pass
