"""AWS Lambda entrypoint for icp-service."""

from mangum import Mangum

from services.common.secrets import load_app_secret_into_environ

load_app_secret_into_environ()

from services.icp.app import app

handler = Mangum(app, lifespan="off")
