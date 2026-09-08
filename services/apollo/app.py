from services.apollo.handler import router
from services.common.http import create_app

app = create_app("apollo-service")
app.include_router(router)
