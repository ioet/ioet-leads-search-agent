from services.skills.handler import router
from services.common.http import create_app

app = create_app("skills-service")
app.include_router(router)
