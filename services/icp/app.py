from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from services.common.http import create_app
from services.icp.handler import router

app = create_app("icp-service")
app.include_router(router)
