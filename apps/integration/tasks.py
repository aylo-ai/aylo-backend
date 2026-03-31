import requests
import time
import json
import os
import tempfile
import logging
import pytz
from datetime import datetime

from django.db import transaction
from celery import shared_task


from apps.shared.ai_service.openai_client import client
from apps.shared.addons.enums import SenderTypes, ConversationStatuses, IntegrationTypes
from apps.assistant.models import Assistant, Lead, Conversation
from shared.addons.redis import publish_message_to_ws, redis_client
from shared.addons.instagram import instagram_service
from shared.addons.telegram import send_telegram_message, send_telegram_action
from apps.shared.ai_service.assistant import assistant_service
from apps.shared.ai_service.conversation import conversation_service
from .models import (Integration,
                    InstagramMedia, InstagramCommentResponse, Flow,
                    Step, Transition, InstagramUserState, Broadcast)

logger = logging.getLogger(__name__)

WAIT_SECONDS = 2

@shared_task(bind=True, max_retries=3, default_retry_delay=5)
def process_message_task(self, chat_id, user_message, bot_token, chat_username=None, username=None, audio_file=None, input_tokens=None, output_tokens=None):
    assistant = Assistant.objects.filter(integrations__api_token=bot_token).first()
    if not assistant:
        logging.warning(f"[-] No assistant found for bot_token: {bot_token}")
        return

    if user_message == '/start':
        conversation_service.handle_start_command(chat_id, assistant, bot_token, chat_username, username)
        return

    conversation = conversation_service.get_or_create_conversation(chat_id, assistant, token=bot_token, chat_username=chat_username, username=username)
    if conversation.status == ConversationStatuses.ESCALATED.value or not assistant.is_active:
        data = conversation_service.create_message(conversation=conversation, sender=SenderTypes.USER.value, content=user_message, 
                              audio_file=audio_file, input_tokens=input_tokens, output_tokens=output_tokens)
        publish_message_to_ws(conversation.id, user_message, sender="user", data=data, assistant_id=assistant.id)
        return

    send_telegram_action(chat_id, bot_token)

    data = conversation_service.create_message(conversation=conversation, sender=SenderTypes.USER.value, content=user_message, audio_file=audio_file, input_tokens=input_tokens, output_tokens=output_tokens)
    publish_message_to_ws(conversation_id=conversation.id, message=user_message, sender='user', data=data, assistant_id=assistant.id)

    # Cancel any pending follow-ups since user responded
    from apps.assistant.utils import cancel_pending_follow_ups
    cancel_pending_follow_ups(conversation.id)

    response_message = assistant_service.generate_response(user_input=user_message, assistent=assistant, conversation=conversation)
    
    logger.info(f"[+] Response message: {response_message}")

    if response_message:
        send_telegram_message(chat_id, response_message, bot_token)
        

@shared_task(bind=True, max_retries=3, default_retry_delay=5)
def process_instagram_message(self, account_id, combined_message, user_message, audio_file=None):
    assistant = Assistant.objects.filter(integrations__instagram_account_id=account_id).first()
    if not assistant:
        return
    
    integration = assistant.integrations.filter(integration_type="instagram", instagram_account_id=account_id).first()
    if not integration:
        logging.warning("[-] No Instagram integration found for the given account_id")
        return
    sender_id = user_message[0].get("sender", {}).get("id")
    logging.info(f"Sender id: {sender_id}")

    if not sender_id:
        return
    input_tokens = 0
    output_tokens = 0
    if audio_file:
        combined_message,input_tokens,output_tokens = conversation_service.process_instagram_audio(audio_file, assistant.language)
    if not combined_message:
        logging.info("[-] No message content to process")
        return
    conversation = conversation_service.get_or_create_conversation(sender_id, assistant, platform="instagram", chat_username=None)
    if conversation.client_full_name is None:
        conversation.client_full_name = get_user_info(integration.api_token, sender_id).get("username", None)
        conversation.save()
    if conversation.status == ConversationStatuses.ESCALATED.value or not assistant.is_active:
        data = conversation_service.create_message(conversation=conversation, sender=SenderTypes.USER.value, content=combined_message, 
                              audio_file=audio_file, input_tokens=input_tokens, output_tokens=output_tokens)
        publish_message_to_ws(conversation.id, combined_message, sender="user", data=data, assistant_id=assistant.id)
        return
    data = conversation_service.create_message(conversation=conversation, sender=SenderTypes.USER.value, content=combined_message,
                          audio_file=audio_file, input_tokens=input_tokens, output_tokens=output_tokens)
    publish_message_to_ws(conversation.id, combined_message, sender="user", data=data, assistant_id=assistant.id)

    # Cancel any pending follow-ups since user responded
    from apps.assistant.utils import cancel_pending_follow_ups
    cancel_pending_follow_ups(conversation.id)

    if assistant.ai_enabled:
        response_message = assistant_service.generate_response(user_input=combined_message, assistent=assistant, conversation=conversation)
        if response_message:
            instagram_service.send_message(account_id, integration.api_token, sender_id, response_message)


@shared_task(bind=True, max_retries=3, default_retry_delay=5)
def process_shared_post_message(self, account_id, shared_url, user_text, messaging):
    """Process a shared Instagram post in DM — fetch post details and include as context for AI."""
    assistant = Assistant.objects.filter(integrations__instagram_account_id=account_id).first()
    if not assistant:
        logging.warning(f"[-] No assistant found for account_id: {account_id}")
        return

    integration = assistant.integrations.filter(
        integration_type="instagram", instagram_account_id=account_id
    ).first()
    if not integration:
        logging.warning("[-] No Instagram integration found")
        return

    sender_id = messaging[0].get("sender", {}).get("id")
    if not sender_id:
        return

    # Try to fetch post details
    post_context = ""
    if shared_url and integration.api_token:
        # Try to find media ID from URL and get details
        media_id = instagram_service.extract_media_id_from_url(
            shared_url, integration.api_token, account_id
        )
        if media_id:
            media_details = instagram_service.get_media_details(integration.api_token, media_id)
            if media_details:
                caption = media_details.get("caption", "")
                media_type = media_details.get("media_type", "")
                post_context = f"\n\n[Klient quyidagi Instagram postni yubordi]\nPost turi: {media_type}\nPost matni: {caption}\nPost havolasi: {shared_url}"

    # Build the combined message
    if user_text and post_context:
        combined_message = f"{user_text}{post_context}"
    elif post_context:
        combined_message = f"Klient quyidagi post haqida so'ramoqda.{post_context}"
    elif user_text:
        combined_message = user_text
    else:
        combined_message = f"Klient Instagram post yubordi: {shared_url}"

    conversation = conversation_service.get_or_create_conversation(
        sender_id, assistant, platform="instagram", chat_username=None
    )
    if conversation.client_full_name is None:
        conversation.client_full_name = get_user_info(integration.api_token, sender_id).get("username", None)
        conversation.save()

    if conversation.status == ConversationStatuses.ESCALATED.value or not assistant.is_active:
        data = conversation_service.create_message(
            conversation=conversation, sender=SenderTypes.USER.value, content=combined_message
        )
        publish_message_to_ws(conversation.id, combined_message, sender="user", data=data, assistant_id=assistant.id)
        return

    data = conversation_service.create_message(
        conversation=conversation, sender=SenderTypes.USER.value, content=combined_message
    )
    publish_message_to_ws(conversation.id, combined_message, sender="user", data=data, assistant_id=assistant.id)

    if assistant.ai_enabled:
        response_message = assistant_service.generate_response(
            user_input=combined_message, assistent=assistant, conversation=conversation
        )
        if response_message:
            instagram_service.send_message(account_id, integration.api_token, sender_id, response_message)


@shared_task
def send_message_integration_task(integration_id, message):
    integration = Integration.objects.get(id=integration_id)
    conversations = Conversation.objects.filter(assistant=integration.assistant, platform=integration.integration_type)
    if integration.integration_type == IntegrationTypes.TELEGRAM.value:
        for conversation in conversations:
            send_telegram_message(conversation.user_id, message, integration.api_token)
    if integration.integration_type == IntegrationTypes.INSTAGRAM.value:
        for conversation in conversations:
            instagram_service.send_message(account_id=conversation.user_id, access_token=integration.api_token, recipient_id=conversation.user_id, message=message)


@shared_task(bind=True, max_retries=2, default_retry_delay=10)
def send_broadcast_task(self, broadcast_id):
    try:
        broadcast = Broadcast.objects.select_related('integration').get(id=broadcast_id)
    except Broadcast.DoesNotExist:
        logging.error(f"[-] Broadcast not found: {broadcast_id}")
        return

    integration = broadcast.integration
    broadcast.status = 'sending'
    broadcast.save(update_fields=['status'])

    # Get conversations
    if integration.assistant:
        conversations = Conversation.objects.filter(
            assistant=integration.assistant,
            platform=integration.integration_type
        )
    else:
        conversations = Conversation.objects.filter(
            assistant__integrations__instagram_account_id=integration.instagram_account_id,
            platform='instagram'
        )

    sent = 0
    failed = 0
    for conversation in conversations:
        try:
            if integration.integration_type == IntegrationTypes.TELEGRAM.value:
                send_telegram_message(conversation.user_id, broadcast.message, integration.api_token)
                sent += 1
                # Rate limit: Telegram allows ~30 msgs/sec, stay safe at ~25/sec
                time.sleep(0.04)
            elif integration.integration_type == IntegrationTypes.INSTAGRAM.value:
                success = instagram_service.send_message(
                    account_id=integration.instagram_account_id,
                    access_token=integration.api_token,
                    recipient_id=conversation.user_id,
                    message=broadcast.message
                )
                if success:
                    sent += 1
                else:
                    failed += 1
                # Rate limit: Instagram messaging API limits
                time.sleep(0.1)
        except Exception as e:
            logger.error(f"Broadcast send failed for {conversation.user_id}: {e}")
            failed += 1

        # Update counts periodically
        if (sent + failed) % 10 == 0:
            broadcast.sent_count = sent
            broadcast.failed_count = failed
            broadcast.save(update_fields=['sent_count', 'failed_count'])

    broadcast.sent_count = sent
    broadcast.failed_count = failed
    broadcast.status = 'completed'
    broadcast.save(update_fields=['sent_count', 'failed_count', 'status'])
        


@shared_task(bind=True, max_retries=3, default_retry_delay=5)
def process_voice_task(self, chat_id, voice_file_id, bot_token):
    assistant = Assistant.objects.filter(integrations__api_token=bot_token).first()
    if not assistant:
        logging.warning("[+] Assistant not found")
        return

    file_info_url = f"https://api.telegram.org/bot{bot_token}/getFile?file_id={voice_file_id}"
    file_info_resp = requests.get(file_info_url)
    file_path = file_info_resp.json()["result"]["file_path"]
    file_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"

    audio_bytes_ogg = requests.get(file_url).content
    audio_bytes_mp3 = conversation_service.convert_ogg_to_mp3(audio_bytes_ogg)

    language_code = assistant.language or "uz"
    transcribed_text, input_tokens, output_tokens = conversation_service.speech_to_text(audio_bytes_mp3, language=language_code)

    process_message_task.delay(chat_id=chat_id, user_message=transcribed_text, bot_token=bot_token, audio_file=audio_bytes_mp3, input_tokens=input_tokens, output_tokens=output_tokens)

@shared_task(bind=True, max_retries=3, default_retry_delay=5)
def process_photo_task(self, chat_id, photo_file_id, bot_token, chat_username=None, username=None):
    assistant = Assistant.objects.filter(integrations__api_token=bot_token).first()
    if not assistant:
        logging.warning("[+] Assistant not found")
        return

    try:
        # Get file info from Telegram
        file_info_url = f"https://api.telegram.org/bot{bot_token}/getFile?file_id={photo_file_id}"
        file_info_resp = requests.get(file_info_url)
        file_info_resp.raise_for_status()
        file_path = file_info_resp.json()["result"]["file_path"]
        file_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
        
        image_analysis = assistant_service.gemini.picture_analysis(file_url, language=assistant.language)
        
        if not image_analysis or image_analysis.startswith("I couldn't") or image_analysis.startswith("I encountered"):
            send_telegram_message(chat_id, "I couldn't analyze the image. Please try again.", bot_token)
            return
        
        conversation = conversation_service.get_or_create_conversation(
            chat_id, assistant, token=bot_token, chat_username=chat_username, username=username
        )
        
        if conversation.status == ConversationStatuses.ESCALATED.value or not assistant.is_active:
            data = conversation_service.create_message(
                conversation=conversation, 
                sender=SenderTypes.USER.value, 
                content=f"[Image] {image_analysis}"
            )
            publish_message_to_ws(conversation.id, image_analysis, sender="user", data=data, assistant_id=assistant.id)
            return
        
        send_telegram_action(chat_id, bot_token)
        
        data = conversation_service.create_message(
            conversation=conversation, 
            sender=SenderTypes.USER.value, 
            content=f"[Image] {image_analysis}"
        )
        publish_message_to_ws(conversation_id=conversation.id, message=image_analysis, sender='user', data=data, assistant_id=assistant.id)
        
        response_message = assistant_service.generate_response(
            user_input=image_analysis, 
            assistent=assistant, 
            conversation=conversation
        )
        
        logger.info(f"[+] Photo response message: {response_message}")
        
        if response_message:
            send_telegram_message(chat_id, response_message, bot_token)
            
    except Exception as e:
        logging.error(f"Error processing photo: {e}")
        import traceback
        logging.error(f"Traceback: {traceback.format_exc()}")
        send_telegram_message(chat_id, "I encountered an error while processing the image. Please try again.", bot_token)

@shared_task(bind=True, max_retries=2, default_retry_delay=5)
def process_instagram_comment(self, account_id, comment_data):
    logging.info(f"[+] Processing Instagram comment for account_id: {account_id}")
    
    integration = Integration.objects.filter(instagram_account_id=account_id).first()
    if not integration:
        logging.warning("[-] Integration not found")
        return

    media_id = comment_data.get("media",{}).get("id")
    comment_id = comment_data.get("id")
    comment_text = comment_data.get("text", "").strip()
    commenter_id = comment_data.get("from", {}).get("id")
    parent_id = comment_data.get("parent_id", None)

    if not all([media_id, comment_id, comment_text, commenter_id]):
        logging.warning("[-] Missing required comment data")
        return
    
    if parent_id is None:

        media = InstagramMedia.objects.filter(media_id=media_id).first()
        if media:
            # 1a. Respond to all comments if flag is set
            response = InstagramCommentResponse.objects.filter(instagram_media=media).first()
            if response.is_respond_to_all_comments:
                logger.info("Media-specific: Respond to all comments")
                flow = Flow.objects.filter(comment_response=response)
                if response.comment_message_template and not integration.is_comment_response:
                    instagram_service.send_comment_reply(integration.api_token, comment_id, response.comment_message_template)
                #if flow exists do not reply from private message
                if response.private_message_template and not flow.exists():
                    instagram_service.send_private_reply(integration.api_token, account_id, comment_id, response.private_message_template)

                if flow.exists():
                    logger.info("Actual flow exists in that way and integartion is found")
                    instagram_service.send_postback(account_id=account_id, access_token=integration.api_token, recipient_comment_id=comment_id, data=flow.first(), commenter_id=commenter_id)


            else:
                logger.info("Media-specific: Respond to all comments")
                trigger_words = [tw.trigger_word.lower() for tw in response.trigger_words.all()]
                if comment_text.strip().lower() in trigger_words:
                    logger.info(f"Media-specific trigger match: {trigger_words}")
                    flow = Flow.objects.filter(comment_response=response)

                    if response.comment_message_template and not integration.is_comment_response:
                        instagram_service.send_comment_reply(integration.api_token, comment_id, response.comment_message_template)
                    if response.private_message_template and not flow.exists():
                        instagram_service.send_private_reply(integration.api_token, account_id, comment_id, response.private_message_template)
                    if flow.exists():
                        logger.info("Actual flow exists in that way and integartion is found")
                        instagram_service.send_postback(account_id=account_id, access_token=integration.api_token, recipient_comment_id=comment_id, data=flow.first(), commenter_id=commenter_id)
        else:
            latest_response = InstagramCommentResponse.objects.filter(integration=integration).order_by("-created_time").first()
            logger.info("Incoming new lasted post for comment response")
            if latest_response and not latest_response.instagram_media.exists():
                access_token = integration.api_token
                url = "https://graph.instagram.com/v23.0/me/media"
                params = {
                    "access_token": access_token,
                    "fields": "id,media_type,media_url,username,timestamp,caption,comments_count,like_count,permalink,thumbnail_url,children{media_type,media_url}"
                }
                response = requests.get(url, params=params)
                if response.status_code == 200:
                    media_first = response.json()['data'][0]
                    media_ts_str = media_first["timestamp"] 
                    media_ts = datetime.strptime(media_ts_str, "%Y-%m-%dT%H:%M:%S%z")
                    # Convert to Asia/Tashkent timezone
                    media_ts_tashkent = media_ts.astimezone(pytz.timezone("Asia/Tashkent"))
                    logger.info(f"Time {media_ts_tashkent} and {latest_response.created_time}")
                    if media_ts_tashkent > latest_response.created_time:
                        if latest_response.is_respond_to_all_comments:

                            flow = Flow.objects.filter(comment_response=latest_response)
                            if latest_response.comment_message_template and not integration.is_comment_response:
                                    instagram_service.send_comment_reply(integration.api_token, comment_id, latest_response.comment_message_template)
                            # validate that flow does not exists
                            if latest_response.private_message_template and not flow.exists():
                                    instagram_service.send_private_reply(integration.api_token, account_id, comment_id, latest_response.private_message_template)
                            if flow.exists():
                                logger.info("Actual flow exists in that way and integartion is found")
                                instagram_service.send_postback(account_id=account_id, access_token=integration.api_token, recipient_comment_id=comment_id, data=flow.first(),commenter_id=commenter_id)

                        else:
                            logger.info("Media comment response only for specific comment")
                            trigger_words = [tw.trigger_word.lower() for tw in latest_response.trigger_words.all()]
                            if comment_text.strip().lower() in trigger_words:

                                flow = Flow.objects.filter(comment_response=latest_response)
                                logger.info(f"Media-specific trigger match: {trigger_words}")
                                if latest_response.comment_message_template and not integration.is_comment_response:
                                    instagram_service.send_instagram_comment_reply(integration.api_token, comment_id, latest_response.comment_message_template)
                                if latest_response.private_message_template and not flow.exists():
                                    instagram_service.send_instagram_private_reply(integration.api_token, account_id, comment_id, latest_response.private_message_template)
                                if flow.exists():
                                    logger.info("Actual flow exists in that way and integartion is found")
                                    instagram_service.send_instagram_postback(account_id=account_id, access_token=integration.api_token, recipient_comment_id=comment_id, data=flow.first(),commenter_id=commenter_id)
                        media_data = InstagramMedia.objects.create(
                            media_id=media_first.get('id'),
                            media_type=media_first.get('media_type', None),
                            media_url=media_first.get('media_url', None),
                            username=media_first.get('username', None),
                            timestamp=media_first.get('timestamp', None),
                            caption=media_first.get('caption', None),
                            comments_count=media_first.get('comments_count', None),
                            like_count=media_first.get('like_count', None),
                            children=media_first.get('children', None)
                        )
                        latest_response.instagram_media.add(media_data)
        if integration.is_comment_response:
            logger.info("Integration is comment response and new media is received")
            process_instagram_comment_message.delay(account_id=account_id, message=comment_text, comment_id=comment_id, integration_id=integration.id, media_id=media_id)
            return
    logger.info(f"Media {media_id} has parent_id: {parent_id}")

@shared_task
def process_collected_messages(chat_id, bot_token=None, messaging=None, chat_username=None, username=None, account_id=None):
    user_key = f"messages:{chat_id}"
    last_seen_key = f"last_seen:{chat_id}"
    # Check if we should wait longer
    last_seen = float(redis_client.get(last_seen_key) or 0)
    if time.time() - last_seen < WAIT_SECONDS:
        return  # Another message came in recently, skip for now

    messages = redis_client.lrange(user_key, 0, -1)
    if not messages:
        return
    combined_message = ", ".join(m for m in messages)

    # Clean up Redis
    redis_client.delete(user_key)
    redis_client.delete(last_seen_key)

    # Call your existing task
    if bot_token:
        process_message_task.delay(chat_id, combined_message, bot_token,chat_username, username)
    else:
        # Prefer provided account_id; otherwise derive from messaging recipient
        resolved_account_id = account_id
        try:
            if resolved_account_id is None and messaging:
                resolved_account_id = messaging[0].get("recipient", {}).get("id")
        except Exception:
            resolved_account_id = None
        # Fallback: if still None, use chat_id (legacy behavior)
        resolved_account_id = resolved_account_id or chat_id
        process_instagram_message.delay(account_id=resolved_account_id, combined_message=combined_message, user_message=messaging)

def get_user_info(access_token, user_id):
    url = f"https://graph.instagram.com/v23.0/{user_id}"
    params = {
        "access_token": access_token,
        "fields": "id, username"
    }
    response = requests.get(url, params=params)
    return response.json()


@shared_task
def handle_postback_event_task(msg, access_token):
    sender_id = msg.get("sender", {}).get("id")
    account_id = msg.get("recipient", {}).get("id")
    postback = msg.get("postback", {}) or {}
    payload = postback.get("payload") 

    logger.info(f"Handling postback event: {payload} from user: {sender_id}")

    if not payload or not sender_id:
        logger.warning("Missing payload or sender_id")
        return
    inline_button_id = payload.split(":")[1]
    logger.info(f"incomming inline_button {inline_button_id}")
    user_state = InstagramUserState.objects.filter(account_id=account_id, user_id=sender_id).first()
    if user_state is None:
        logger.warning(f"User state was not initialized yet {user_state}")
        return 
    
    #checking user that he subscribed or not
    status_subscription = instagram_service.checking_followers(access_token=access_token, recipient_id=sender_id)
    #based on the subscrition send another way
    transition = Transition.objects.filter(from_to=user_state.current_step, action_subscription=status_subscription['is_user_follow_business'], 
                                           button_text__id=inline_button_id).first()
    if transition is None:
        logger.warning(f"Transicition was not create or not found for this step {transition}")
        return
    if transition.to_step is None:
        logger.warning("Transition to step is not given")
        return
    try:
        with transaction.atomic():
            # Increment the current step count (users who reached this step)
            transition.to_step.count += 1
            transition.to_step.save()
            
            # Also increment flow total count (total interactions in this flow)
            transition.to_step.flow.total_count += 1
            transition.to_step.flow.save()
    except Exception as e:
        logger.warning(f"Error updating user state: {e}")
    send_step_message_task.delay(transition.to_step.id, account_id, sender_id, access_token)


@shared_task
def send_step_message_task(step_id, account_id, recipient_id, access_token):
    try:
        step = Step.objects.get(id=step_id)
    except Step.DoesNotExist:
        logger.warning(f"Step {step_id} not found")
        return

    buttons = list(step.extra_button.all())
    
    try:
        if buttons:
            # Use postback for messages with buttons
            resp = send_instagram_postback_next(
                account_id=account_id,
                access_token=access_token,
                recipient_comment_id=recipient_id,
                step_id=step.id
            )
        else:
            # Use regular message for text-only messages
            resp = instagram_service.send_message(
                account_id=account_id,
                access_token=access_token,
                recipient_id=recipient_id,
                message=step.message_content
            )
        logger.info(f"Sent step message: {step.message_content}, status: {getattr(resp, 'status_code', None)}")
    except Exception as e:
        logger.warning(f"Error sending step message: {e}")

def send_instagram_postback_next(account_id: str, access_token: str, recipient_comment_id: str, step_id: int):
    url = "https://graph.instagram.com/v23.0/me/messages"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
    }
    next_step = Step.objects.filter(id=step_id).first()
    # Build buttons list
    if next_step:
        btns_payload = []
        for b in next_step.extra_button.all():
            btns_payload.append(instagram_service.build_button_payload(b))

        logger.info(f"All buttons are ready {btns_payload}")
        image_url = None
        if next_step.message_image:
            image_url = next_step.message_image.url
        event = {
            "recipient": {
                "id": recipient_comment_id
            },
            "message": {
                "attachment": {
                    "type": "template",
                    "payload": {
                        "template_type": "generic",
                        "elements": [
                            {
                                "title": next_step.message_content,
                                "image_url": image_url,
                                "buttons": btns_payload
                            },
                        ]
                                }
                            }
                        }
                }

        resp = requests.post(url, json=event, headers=headers)
        if resp.status_code == 200:
            InstagramUserState.objects.filter(
                                            account_id=account_id,
                                            user_id=recipient_comment_id
                                            ).update(current_step=next_step)
        logger.info(resp.json())
        logger.info("Sending instagram message for postback")
        logger.info(resp)



@shared_task
def process_instagram_comment_message(account_id, message, comment_id, integration_id, media_id=None):
    logger.info("Process instagram comment message")
    integration = Integration.objects.filter(id=integration_id).first()
    if not integration:
        logger.warning("Integration not found")
        return

    try:
        assistant = integration.assistant
        if not assistant:
            logger.warning("No assistant found for integration")
            return
            
        # Get or create conversation for this comment
        conversation = conversation_service.get_or_create_conversation(
            user_id=comment_id, 
            assistant=assistant, 
            platform="instagram", 
            chat_username=None
        )
        if media_id:
            instagram_comment_responses = InstagramCommentResponse.objects.filter(instagram_media__media_id=media_id).first()
            if instagram_comment_responses:
                instagram_service.send_comment_reply(access_token=integration.api_token, comment_id=comment_id, message=instagram_comment_responses.comment_message_template)
                
        # Process the comment message through AI if enabled
        if assistant.ai_enabled and assistant.is_active:
            response_message = assistant_service.generate_response(
                user_input=message, assistent=assistant, conversation=conversation
            )
            
            instagram_service.send_private_reply(access_token=integration.api_token, account_id=account_id, comment_id=comment_id, message=response_message)
            
    except Exception as e:
        logger.warning(f"Error processing Instagram comment: {e}")
        import traceback
        traceback.print_exc()


@shared_task
def create_amocrm_lead(lead_id, integration_id):
    try:
        logger.info(f"Creating amoCRM lead for Lead ID: {lead_id}")
        
        # Get the lead
        lead = Lead.objects.filter(id=lead_id).first()
        if not lead:
            logger.warning(f"Lead {lead_id} not found")
            return
        
        # Get the amoCRM integration
        from apps.integration.models import Integration
        from apps.shared.addons.enums import IntegrationTypes
        
        integration = Integration.objects.filter(
            id=integration_id,
            integration_type=IntegrationTypes.AMOCRM.value
        ).first()
        
        if not integration:
            logger.warning(f"amoCRM integration {integration_id} not found")
            return
        
        pipeline_id = int(integration.metadata.get('pipeline_id'))
        if not pipeline_id:
            logger.warning(f"Pipeline not set for integration {integration_id}")
            return
        
        subdomain = integration.metadata.get('subdomain','repli.amocrm.ru') if integration.metadata else 'repli.amocrm.ru'
        access_token = integration.api_token
        
        # Prepare lead data for amoCRM
        lead_data = {
            'name': lead.full_name or lead.username or 'New Lead',
            'price': 0,  # You can set a default price or get it from lead data
            'pipeline_id': pipeline_id,
        }
        
        # Add contact info if available
        if lead.phone_number:
            lead_data['phone'] = lead.phone_number
        if lead.email:
            lead_data['email'] = lead.email

        
        lead_payload = {
            'name': lead_data['name'],
            'price': lead_data['price'],
            'pipeline_id': lead_data['pipeline_id'],
        }
        
        # Add contacts if available
        if lead_data.get('phone') or lead_data.get('email'):
            contacts = []
            if lead_data.get('phone'):
                contacts.append({
                    'field_code': 'PHONE',
                    'values': [{'value': lead_data['phone']}]
                })
            if lead_data.get('email'):
                contacts.append({
                    'field_code': 'EMAIL',
                    'values': [{'value': lead_data['email']}]
                })
            lead_payload['contacts'] = contacts
        
        # Make API call to amoCRM
        create_url = f"https://{subdomain}/api/v4/leads"
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        
        response = requests.post(create_url, headers=headers, json=[lead_payload])
        
        if response.status_code in [200, 201]:
            result = response.json()
            created_lead = result.get('_embedded', {}).get('leads', [{}])[0]
            amocrm_lead_id = created_lead.get('id')
            
            # Store amoCRM lead ID in the local lead metadata
            lead.metadata = lead.metadata or {}
            lead.metadata['amocrm_lead_id'] = amocrm_lead_id
            lead.metadata['amocrm_pipeline_id'] = pipeline_id
            lead.save()
            
            logger.info(f"Lead created in amoCRM with ID: {amocrm_lead_id}")
        else:
            logger.warning(f"Failed to create lead in amoCRM: {response.text}")
            
    except Exception as e:
        logger.warning(f"Error creating amoCRM lead: {e}")
        import traceback
        traceback.print_exc()


def extract_relevant_fields(product):
    # Extract color from custom_fields
    color = None
    size = None
    for field in product.get('custom_fields', []):
        if field.get('custom_field_system_name') == 'ЦВЕТ':
            color = field.get('custom_field_value')
        elif field.get('custom_field_system_name') == 'РАЗМЕР':
            size = field.get('custom_field_value')
    
    # Extract shop names and prices
    shops = []
    for shop_price in product.get('shop_prices', []):
        shops.append({
            'shop_name': shop_price.get('shop_name', ''),
            'retail_price': shop_price.get('retail_price', 0),
            'retail_currency': shop_price.get('retail_currency', 'UZS')
        })
    
    # Extract category names
    categories = [cat.get('name', '') for cat in product.get('categories', [])]
    
    # Build simplified product
    simplified = {
        'id': product.get('id', ''),
        'name': product.get('name', ''),
        'product_name': product.get('name', ''),  # Alias for name
        'sku': product.get('sku', ''),
        'color': color,
        'size': size,
        'categories': categories,
        'brand_name': product.get('brand_name', ''),
        'shops': shops,
        'description': product.get('description', ''),
        'barcode': product.get('barcode', ''),
        'main_image_url': product.get('main_image_url', ''),
        'main_image_url_full': product.get('main_image_url_full', ''),
        'photos': product.get('photos', []),
    }
    
    return simplified


def get_all_billz_products(access_token):
    """
    Fetch all products from the Billz API with pagination support.
    Returns a list of all products with only relevant fields.
    """
    all_products = []
    page = 1
    limit = 1000  # Maximum items per page
    base_url = 'https://api-admin.billz.ai/v2/products'
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    logger.info("Fetching all Billz products...")
    
    while True:
        params = {
            "limit": limit,
            "page": page
        }
        
        try:
            response = requests.get(base_url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            # Extract products from response
            products = data.get('products', [])
            if not products:
                break
            
            # Extract only relevant fields from each product
            for product in products:
                simplified_product = extract_relevant_fields(product)
                all_products.append(simplified_product)
            
            logger.info(f"Fetched page {page}: {len(products)} products (Total: {len(all_products)})")
            
            # Check if there are more pages
            # If we got fewer products than the limit, we've reached the last page
            if len(products) < limit:
                break
            
            page += 1
            
        except requests.exceptions.RequestException as e:
            logger.warning(f"Error fetching page {page}: {str(e)}")
            break
    
    return all_products


@shared_task
def fetch_and_save_billz_products(integration_id: str):
    """
    Fetch all Billz products and save them to vector store.
    This task is called when Billz integration is created or updated.
    """
    try:
        integration = Integration.objects.filter(id=integration_id).first()
        if not integration or integration.integration_type != IntegrationTypes.BILLZ.value:
            logger.warning(f"Integration {integration_id} not found or not Billz type")
            return

        if not integration.api_token or not integration.assistant:
            logger.warning(f"Integration {integration_id} missing api_token or assistant")
            return
        
        assistant = integration.assistant
        
        # Fetch all products
        all_products = get_all_billz_products(integration.api_token)
        
        if not all_products:
            logger.warning(f"No products fetched for integration {integration_id}")
            return
        
        logger.info(f"Fetched {len(all_products)} products for integration {integration_id}")
        
        # Convert products to JSON string
        products_json = json.dumps(all_products, ensure_ascii=False, indent=2)
        
        # Create a unique filename for this assistant's products
        filename = f"billz_products_{assistant.id}_{int(time.time())}.json"
        
        # Save to temp file first
        temp_dir = tempfile.gettempdir()
        temp_file_path = os.path.join(temp_dir, filename)
        
        with open(temp_file_path, 'w', encoding='utf-8') as f:
            f.write(products_json)
        
        logger.info(f"Saved products to temp file: {temp_file_path}")
        
        # Ensure assistant has a vector store
        if not assistant.vector_id:
            success, message = assistant_service.create_assistant_and_vector_id(assistant, request=None)
            if not success:
                logger.warning(f"Failed to create vector store for assistant {assistant.id}: {message}")
                # Clean up temp file
                if os.path.exists(temp_file_path):
                    os.remove(temp_file_path)
                return
        
        # Get previous file_id from metadata if it exists
        metadata = integration.metadata or {}
        previous_file_id = metadata.get('billz_products_file_id')
        
        # Delete previous file from vector store if it exists
        if previous_file_id and assistant.vector_id:
            try:
                logger.info(f"Deleting previous Billz products file (file_id: {previous_file_id}) from vector store")
                client.vector_stores.files.delete(
                    vector_store_id=assistant.vector_id,
                    file_id=previous_file_id
                )
                logger.info(f"Successfully deleted previous Billz products file from vector store")
            except Exception as e:
                # If file doesn't exist anymore, that's okay - just log it
                logger.warning(f"Could not delete previous file (may not exist): {e}")
        
        openai_file_id = assistant_service.upload_knowledge_base_file(file_url=None, clear_text=products_json)
        
        if not openai_file_id:
            logger.warning(f"Failed to upload products to OpenAI for integration {integration_id}")
            # Clean up temp file
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
            return
        
        logger.info(f"Uploaded products to OpenAI with file_id: {openai_file_id}")
        
        # Add file to vector store
        if assistant.vector_id:
            try:
                batch = client.vector_stores.file_batches.create(
                    vector_store_id=assistant.vector_id,
                    file_ids=[openai_file_id]
                )
                
                # Poll until completion
                while True:
                    status = client.vector_stores.file_batches.retrieve(
                        vector_store_id=assistant.vector_id,
                        batch_id=batch.id
                    )
                    if status.status in ["completed", "failed"]:
                        break
                    time.sleep(0.5)
                
                if status.status == "completed":
                    logger.info(f"Products successfully added to vector store for assistant {assistant.id}")
                    
                    # Update integration metadata with new file_id
                    if not integration.metadata:
                        integration.metadata = {}
                    integration.metadata['billz_products_file_id'] = openai_file_id
                    integration.metadata['billz_products_updated_at'] = time.time()
                    integration.save(update_fields=['metadata'])
                    logger.info(f"Updated integration metadata with new file_id: {openai_file_id}")
                else:
                    logger.warning(f"Failed to add products to vector store: {status.status}")
            except Exception as e:
                logger.warning(f"Error adding products to vector store: {e}")
        
        # Clean up temp file
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
            logger.info(f"Cleaned up temp file: {temp_file_path}")
            
    except Exception as e:
        logger.warning(f"Error in fetch_and_save_billz_products: {e}")
        import traceback
        traceback.print_exc()


@shared_task
def update_billz_products_hourly():
    try:
        billz_integrations = Integration.objects.filter(
            integration_type=IntegrationTypes.BILLZ.value,
            is_active=True,
            assistant__isnull=False
        ).select_related('assistant')
        
        logger.info(f"Found {billz_integrations.count()} active Billz integrations to update")
        
        for integration in billz_integrations:
            if integration.api_token and integration.assistant:
                logger.info(f"Updating products for integration {integration.id} (assistant {integration.assistant.id})")
                fetch_and_save_billz_products.delay(str(integration.id))
            else:
                logger.warning(f"Skipping integration {integration.id} - missing api_token or assistant")
                
    except Exception as e:
        logger.warning(f"Error in update_billz_products_hourly: {e}")
        import traceback
        traceback.print_exc()