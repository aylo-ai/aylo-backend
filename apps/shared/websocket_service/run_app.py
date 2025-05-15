from starlette.applications import Starlette
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket
from starlette.responses import HTMLResponse

# Assuming your WebSocketService is here:
from apps.shared.websocket_service.main import WebSocketService
import logging

# Configure basic logging (optional, but good practice)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def websocket_endpoint(websocket: WebSocket):
    service = WebSocketService(websocket)
    await service.start()

routes = [
    WebSocketRoute("/ws/conversation/", endpoint=websocket_endpoint)
]

app = Starlette(routes=routes)