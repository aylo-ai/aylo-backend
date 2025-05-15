from starlette.websockets import WebSocket
from typing import Dict, Any, Optional
import json
import base64

from apps.assistant.models import Conversation, Message
# from apps.shared.addons.utils import speech_to_text

def test_speech_to_text(*args, **kwargs):
    return "Assalomu alyekum boy ota yaxshimizmi charchamasdan"

class WebSocketService:
    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self.is_connected: bool = False
        self.client_id: Optional[str] = None
        self.conversation_id: str

    async def initialize_connection(self) -> None:
        """Initialize the WebSocket connection and accept it."""
        try:
            await self.websocket.accept()
            self.is_connected = True
            self.client_id = id(self.websocket)
            print(f"WebSocket connection established. Client ID: {self.client_id}")
        except Exception as e:
            print(f"Failed to initialize WebSocket connection: {str(e)}")
            raise

    async def handle_message(self, message: str) -> None:

        try:
            # Parse the message as JSON
            data = json.loads(message)
            
            # Process the message based on its type
            message_type = data.get('type')
            payload = data.get('payload', {})
            
            if message_type == 'ping':
                await self.send_message({'type': 'pong', 'payload': {'status': 'ok'}})

            elif message_type == 'audio':
                await self.handle_audio_transcription(payload)

            elif message_type == 'text':
                await self.process_message(message_type, payload)
                
        except json.JSONDecodeError:
            print(f"Invalid JSON message received: {message}")
            await self.send_error("Invalid message format")
        except Exception as e:
            print(f"Error processing message: {str(e)}")
            await self.send_error("Internal server error")

    async def handle_audio_transcription(self, payload: Dict[str, Any]) -> None:
        try:
            audio_base64 = payload.get('message')
            language = payload.get('language', 'uz')
            
            if not audio_base64:
                await self.send_error("No audio data provided")
                return
            
            audio_bytes = base64.b64decode(audio_base64)
            print(f"Audio bytes: {audio_bytes}")
            
            # Get transcription
            transcription = test_speech_to_text(audio_bytes, language)
            
            # Send response back to client
            await self.send_message({
                'type': 'audio',
                'payload': {
                    'message': transcription,
                    'language': language
                }
            })
            
        except Exception as e:
            print(f"Error processing audio: {str(e)}")
            await self.send_error("Failed to process audio")

    async def process_message(self, message_type: str, payload: Dict[str, Any]) -> None:
        # Add your message processing logic here
        print(f"Processing message type: {message_type}")
        # Example: Echo the message back
        await self.send_message({
            'type': 'text',
            'payload': {
                "data": payload.get('data'),
                'data': payload
            }
        })

    async def send_message(self, data: Dict[str, Any]) -> None:
        try:
            if not self.is_connected:
                raise ConnectionError("WebSocket is not connected")
            
            #stroring message in database
            audio_bytes = base64.b64decode(data.get('payload').get('audio'))

            message = Message.objects.create(
                conversation=self.conversation_id,
                sender='assistant',
                audio_file=None,
                message_type=None
            )
            from django.core.files.base import ContentFile
            from django.utils.text import slugify

            file_name = f"audio_{slugify(self.conversation_id)}_{message.id}.mp3"
            message.audio_file.save(file_name, ContentFile(audio_bytes))
            message.save()
            
            message = json.dumps(data)
            await self.websocket.send_text(message)
        except Exception as e:
            print(f"Error sending message: {str(e)}")
            raise

    async def send_error(self, error_message: str) -> None:
        await self.send_message({
            'type': 'error',
            'payload': {
                'message': error_message
            }
        })

    async def close_connection(self) -> None:
        """Close the WebSocket connection."""
        try:
            if self.is_connected:
                await self.websocket.close()
                self.is_connected = False
                print(f"WebSocket connection closed. Client ID: {self.client_id}")
        except Exception as e:
            print(f"Error closing WebSocket connection: {str(e)}")
            raise

    async def start(self) -> None:
        """
        Start the WebSocket service and handle messages.
        This method should be called to start processing messages.
        """
        try:
            await self.initialize_connection()
            
            while self.is_connected:
                try:
                    # Wait for a message from the client
                    message = await self.websocket.receive_text()
                    await self.handle_message(message)
                except Exception as e:
                    break
                    
        except Exception as e:
            print(f"WebSocket service error: {str(e)}")
        finally:
            await self.close_connection()
