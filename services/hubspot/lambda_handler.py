"""AWS Lambda entrypoint for hubspot-service."""

from mangum import Mangum

from services.common.secrets import load_app_secret_into_environ

load_app_secret_into_environ()

from services.hubspot.app import app

handler = Mangum(app, lifespan="off")
