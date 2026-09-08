from services.hubspot.handler import router
from services.common.http import create_app

app = create_app("hubspot-service")
app.include_router(router)
