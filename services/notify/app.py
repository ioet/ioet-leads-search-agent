from services.notify.handler import router
from services.common.http import create_app

app = create_app("notify-service")
app.include_router(router)
