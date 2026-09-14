"""AWS Lambda entrypoint for agent-service."""

from mangum import Mangum

from services.common.secrets import load_app_secret_into_environ

load_app_secret_into_environ()

from services.agent.app import app

handler = Mangum(app, lifespan="off")
