from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import auth, orgs, providers, assistants, knowledge_base, calls, trunks, tools, callbacks, webhooks

app = FastAPI(title="VoBiz API", version="1.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
         "http://localhost:3000",
        "http://localhost:3001",
        "https://parrot-ai.twjlabs.com",  # add your deployed frontend URL here too
    ],  # In production, specify your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health check
@app.get("/health")
async def health():
    return {"status": "healthy"}

# Include routers
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(orgs.router, prefix="/api/v1/orgs", tags=["orgs"])
app.include_router(providers.router, prefix="/api/v1/orgs/{org_id}/providers", tags=["providers"])
app.include_router(assistants.router, prefix="/api/v1/orgs/{org_id}/assistants", tags=["assistants"])
app.include_router(knowledge_base.router, prefix="/api/v1/orgs/{org_id}/knowledge-base", tags=["knowledge-base"])
app.include_router(calls.router, prefix="/api/v1/orgs/{org_id}/calls", tags=["calls"])
app.include_router(trunks.router, prefix="/api/v1/orgs/{org_id}/trunks", tags=["trunks"])
app.include_router(tools.router, prefix="/api/v1/orgs/{org_id}", tags=["tools"])
app.include_router(callbacks.router, prefix="/api/v1/orgs/{org_id}/callbacks", tags=["callbacks"])
app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
