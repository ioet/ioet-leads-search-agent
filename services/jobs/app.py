from services.common.http import create_app
from services.jobs.handler import router

app = create_app("jobs-service")
app.include_router(router)
