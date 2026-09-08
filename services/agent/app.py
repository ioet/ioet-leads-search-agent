from pathlib import Path

from dotenv import load_dotenv

# Load repo .env so Bedrock/skills vars are available when started via uvicorn directly.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from services.agent.handler import router
from services.common.http import create_app

app = create_app("agent-service")
app.include_router(router)
