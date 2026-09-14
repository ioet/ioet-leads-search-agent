"""AWS Lambda entrypoint for jobs-service."""

from mangum import Mangum

from services.common.secrets import load_app_secret_into_environ

load_app_secret_into_environ()

from services.jobs.app import app

handler = Mangum(app, lifespan="off")
