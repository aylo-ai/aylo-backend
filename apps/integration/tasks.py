import requests
import time
import json
import os
import tempfile
import pytz
from datetime import datetime

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction

from apps.shared.ai_service.openai_client import client
from apps.shared.addons.enums import SenderTypes, ConversationStatuses, IntegrationTypes
from apps.assistant.models import Assistant, AssistantFileUpload, Lead
from shared.addons.redis import publish_message_to_ws, redis_client
from celery import shared_task
from shared.ai_service.helper import distill_company_kb_from_texts,  upload_knowledge_base_file
from shared.addons.instagram import (send_instagram_message, send_instagram_private_reply, 
                                        send_instagram_comment_reply, send_instagram_postback, 
                                        checking_instagram_followers, build_button_payload, send_instagram_photo)
from shared.addons.telegram import send_telegram_message, send_telegram_action, send_telegram_photo
from shared.addons.utils import (get_assistant_response_ai, handle_start_command,   
                                get_or_create_conversation, create_message, 
                                speech_to_text, convert_ogg_to_mp3, process_instagram_audio)
from shared.mcp_server.main_mcp import run_assistant_response_ai_mcp_sync
from .models import (TelegramGroupIntegration, Integration, 
                    InstagramMedia, InstagramCommentResponse, Flow, 
                    Step, Transition, InstagramUserState)

WAIT_SECONDS = 5

@shared_task
def process_message_task(chat_id, user_message, bot_token, chat_username=None, username=None, audio_file=None, input_tokens=None, output_tokens=None):
    assistant = Assistant.objects.filter(integrations__api_token=bot_token).first()
    if not assistant:
        print("[-] No assistant found, skipping processing")
        return  # No assistant found, skip processing

    # Handle `/start` command
    if user_message == '/start':
        handle_start_command(chat_id, assistant, bot_token, chat_username, username)
        return

    conversation = get_or_create_conversation(chat_id, assistant, token=bot_token, chat_username=chat_username, username=username)
    if conversation.status == ConversationStatuses.ESCALATED.value or not assistant.is_active:
        data = create_message(conversation=conversation, sender=SenderTypes.USER.value, content=user_message, 
                              audio_file=audio_file, input_tokens=input_tokens, output_tokens=output_tokens)
        publish_message_to_ws(conversation.id, user_message, sender="user", data=data, assistant_id=assistant.id)
        return

    response_data = None
    response_message = None
    send_telegram_action(chat_id, bot_token)

    data = create_message(conversation=conversation, sender=SenderTypes.USER.value, content=user_message, audio_file=audio_file, input_tokens=input_tokens, output_tokens=output_tokens)
    publish_message_to_ws(conversation_id=conversation.id, message=user_message, sender='user', data=data, assistant_id=assistant.id)
    billz_integration = assistant.integrations.filter(integration_type=IntegrationTypes.BILLZ.value).first()
    entities = None
    intent = None
    if billz_integration:
        response_message, run_status, response_data, entities, intent = run_assistant_response_ai_mcp_sync(
            message_content=user_message, 
            assistant_id=assistant.assistant_id, 
            thread_id=conversation.thread_id, 
            billz_api_token=billz_integration.api_token,
            conversation=conversation
        )
    else:   
        response_message, run_status, response_data = get_assistant_response_ai(user_message, 
                                                                                    assistant.assistant_id, 
                                                                                    conversation.thread_id,
                                                                                    conversation=conversation
                                                                                    )
        
    username = getattr(response_data, 'username', None) if response_data else None
    platform = getattr(response_data, 'platform', None) if response_data else None
    username_link = None
    if username:
        if platform and platform.lower() == "telegram":
            username_link = f"@{username}"
        elif platform and platform.lower() == "instagram":
            username_link = f"https://www.instagram.com/{username}"

    if response_data:
        response_lines = [
                "🎉 *New Lead Created!*\n",
                f"👤 *Full Name: {response_data.full_name}  " if getattr(response_data, 'full_name', None) else None,
                f"📞 *Phone Number: {response_data.phone_number}  " if getattr(response_data, 'phone_number', None) not in [None, ""] else None,
                f"📧 *Email: {response_data.email}  " if getattr(response_data, 'email', None) not in [None, ""] else None,
                f"📦 *Interested Product: {response_data.product}  " if getattr(response_data, 'product', None) else None,
                f"📱 *Platform: {platform}  " if platform else None,
                f"🔗 *Username: {username_link}\n" if username_link else None,
                f"🆔 *Artikul:* {response_data.metadata.get('sku', None)}\n" if response_data.metadata and response_data.metadata.get('sku', None) else None,
                "\n✅ Please follow up accordingly."
            ]
        response_text = "\n".join([line for line in response_lines if line])
    else:
        response_text = None

    print(f"[+] Response data: {response_data}")
    if response_data:
        telegram_integration = assistant.integrations.filter(integration_type="telegram").first()
        telegram_groups = TelegramGroupIntegration.objects.filter(
            integration=telegram_integration
        ).all()
        for telegram_group in telegram_groups:
            send_telegram_message(telegram_group.group_id, response_text, bot_token)
            telegram_group.lead_count += 1
            telegram_group.save()

        if response_data:
            amocrm_integration = assistant.integrations.filter(integration_type="amocrm").first()
            if amocrm_integration and amocrm_integration.metadata.get('pipeline_id'):
                print(f"[+] Triggering amoCRM lead creation for Lead ID: {response_data.id}")
                create_amocrm_lead.delay(response_data.id, amocrm_integration.id)
            
    if response_message:
        send_telegram_message(chat_id, response_message, bot_token)
        data = create_message(conversation=conversation, sender=SenderTypes.ASSISTANT.value, content=response_message, run_status=run_status)
        publish_message_to_ws(conversation.id, response_message, sender="assistant", assistant_id=assistant.id,data=data)

    # Send entity-specific messages (e.g., product recommendation cards)
    if entities and intent == "product_recommendation":
        entity_list = entities if isinstance(entities, list) else [entities]
        text_lines = []

        for idx, ent in enumerate(entity_list, start=1):
            if not isinstance(ent, dict):
                continue

            # Keep image_url for possible future use; do not send it now
            _image_url = (
                ent.get("image_url")
                or ent.get("main_image_url")
                or ent.get("main_image_url_full")
            )

            # Build a simple "key: value" summary using all non-image fields
            detail_pairs = []
            for key, value in ent.items():
                if key in {"image_url", "main_image_url", "main_image_url_full", "sku"}:
                    continue
                if value in [None, ""]:
                    continue
                detail_pairs.append(f"{key.capitalize()}: {value}")

            if not detail_pairs:
                continue
            # Render each field on its own line for clarity
            text_line = f"\n{idx}." + "\n".join(detail_pairs)

            if _image_url:
                send_telegram_photo(chat_id, _image_url, bot_token, caption=text_line)
            else:
                text_lines.append(text_line)

        if text_lines:
            send_telegram_message(chat_id, "\n".join(text_lines), bot_token)

@shared_task
def process_instagram_message(account_id, combined_message, user_message, audio_file=None):
    assistant = Assistant.objects.filter(integrations__instagram_account_id=account_id).first()
    if not assistant:
        return
    
    integration = assistant.integrations.filter(integration_type="instagram", instagram_account_id=account_id).first()
    if not integration:
        print("[-] Integration not found")
        return
    sender_id = user_message[0].get("sender", {}).get("id")
    print(f"Sender ID: {sender_id}")

    if account_id in  ['17841461784331766', "17841460285897235"]:
        if combined_message == "Obuna bo'ldim":
            integration = Integration.objects.filter(instagram_account_id=account_id).first()
            if integration:
                send_instagram_message(account_id, integration.api_token, sender_id, "https://t.me/investorlikqollanmasi")
                print("[+] Obuna bo'ldingiz. link foydalanuvchiga yuborildi")
                return 
            else:
                print("[-] Integration not foun for sending request link to user")
                return
    
    if not sender_id:
        return
    input_tokens = 0
    output_tokens = 0
    if audio_file:
        combined_message,input_tokens,output_tokens = process_instagram_audio(audio_file, assistant.language)
    if not combined_message:
        print("[-] No message is recived from user")
        return
    conversation = get_or_create_conversation(sender_id, assistant, platform="instagram", chat_username=None)
    if conversation.client_full_name is None:
        conversation.client_full_name = get_user_info(integration.api_token, sender_id).get("username", None)
        conversation.save()
    if conversation.status == ConversationStatuses.ESCALATED.value or not assistant.is_active:
        data = create_message(conversation=conversation, sender=SenderTypes.USER.value, content=combined_message, 
                              audio_file=audio_file, input_tokens=input_tokens, output_tokens=output_tokens)
        publish_message_to_ws(conversation.id, combined_message, sender="user", data=data, assistant_id=assistant.id)
        return
    data = create_message(conversation=conversation, sender=SenderTypes.USER.value, content=combined_message, 
                          audio_file=audio_file, input_tokens=input_tokens, output_tokens=output_tokens)
    publish_message_to_ws(conversation.id, combined_message, sender="user", data=data, assistant_id=assistant.id)
    response_data = None
    billz_integration = assistant.integrations.filter(integration_type=IntegrationTypes.BILLZ.value).first()
    entities = None
    intent = None
    if assistant.ai_enabled:
        if billz_integration:
            response_message, run_status, response_data, entities, intent = run_assistant_response_ai_mcp_sync(
                message_content=combined_message, 
                assistant_id=assistant.assistant_id, 
                thread_id=conversation.thread_id, 
                billz_api_token=billz_integration.api_token,
                conversation=conversation
            )
        else:
            response_message, run_status, response_data = get_assistant_response_ai(combined_message, assistant.assistant_id, conversation.thread_id, conversation=conversation)
        username = getattr(response_data, 'username', None)
        platform = getattr(response_data, 'platform', None)
        username_link = None
        if username:
            if platform and platform.lower() == "telegram":
                username_link = f"@{username}"
            elif platform and platform.lower() == "instagram":
                username_link = f"https://www.instagram.com/{username}"
                
        send_instagram_message(account_id, integration.api_token, sender_id, response_message)
        data = create_message(conversation=conversation, sender=SenderTypes.ASSISTANT.value, content=response_message, run_status=run_status)
        publish_message_to_ws(conversation.id, response_message, sender="assistant", assistant_id=assistant.id, data=data)

    if response_data:
        # Check if there's an amoCRM integration and create lead there
        amocrm_integration = assistant.integrations.filter(integration_type="amocrm").first()
        if amocrm_integration and amocrm_integration.metadata.get('pipeline_id'):
            print(f"[+] Triggering amoCRM lead creation for Lead ID: {response_data.id}")
            create_amocrm_lead.delay(response_data.id, amocrm_integration.id)
        
        response_lines = [
                "🎉 *New Lead Created!*\n",
                f"👤 *Full Name: {response_data.full_name}  " if getattr(response_data, 'full_name', None) else None,
                f"📞 *Phone Number: {response_data.phone_number}  " if getattr(response_data, 'phone_number', None) not in [None, ""] else None,
                f"📧 *Email: {response_data.email}  " if getattr(response_data, 'email', None) not in [None, ""] else None,
                f"📦 *Interested Product: {response_data.product}  " if getattr(response_data, 'product', None) else None,
                f"📱 *Platform: {platform}  " if platform else None,
                f"🔗 *Username: {username_link}\n" if username_link else None,
                f"🆔 *Artikul:* {response_data.metadata.get('sku', None)}\n" if response_data.metadata and response_data.metadata.get('sku', None) else None,
                "\n✅ Please follow up accordingly."
            ]
        response_text = "\n".join([line for line in response_lines if line])
        # Send lead notification to Telegram groups if configured
        telegram_integration = assistant.integrations.filter(integration_type="telegram").first()
        telegram_groups = TelegramGroupIntegration.objects.filter(
            integration=telegram_integration
        ).all()
        for telegram_group in telegram_groups:
            send_telegram_message(telegram_group.group_id, response_text, telegram_integration.api_token)
            telegram_group.lead_count += 1
            telegram_group.save()
            print(f"[+] Lead sent to telegram group: {telegram_group.group_id}")
    if entities and intent == "product_recommendation":
        entity_list = entities if isinstance(entities, list) else [entities]
        text_lines = []

        for idx, ent in enumerate(entity_list, start=1):
            if not isinstance(ent, dict):
                continue

            # Keep image_url for possible future use; do not send it now
            _image_url = (
                ent.get("image_url")
                or ent.get("main_image_url")
                or ent.get("main_image_url_full")
            )

            # Build a simple "key: value" summary using all non-image fields
            detail_pairs = []
            for key, value in ent.items():
                if key in {"image_url", "main_image_url", "main_image_url_full"}:
                    continue
                if value in [None, ""]:
                    continue
                if key == "sku":
                    detail_pairs.append(f"🆔 *Artikul:* {value}")
                    continue
                detail_pairs.append(f"{key.capitalize()}: {value}")

            if not detail_pairs:
                continue
            # Render each field on its own line for clarity
            text_line = f"\n{idx}." + "\n".join(detail_pairs)

            if _image_url:
                response = send_instagram_photo(account_id, integration.api_token, sender_id, _image_url)
                if response.status_code == 200:
                    print("[+] Image sent to Instagram")
                else:
                    print(f"[-] Failed to send image to Instagram: {response.text}")
                response = send_instagram_message(account_id, integration.api_token, sender_id, text_line)
                if response.status_code == 200:
                    print("[+] Message sent to Instagram")
                    return
                else:
                    print(f"[-] Failed to send message to Instagram: {response.text}")
                    return
            else:
                text_lines.append(text_line)

        if text_lines:
            send_instagram_message(account_id, integration.api_token, sender_id, "\n".join(text_lines))
   

@shared_task
def process_voice_task(chat_id, voice_file_id, bot_token):
    assistant = Assistant.objects.filter(integrations__api_token=bot_token).first()
    if not assistant:
        print("[-] Assistant not found")
        return

    # Step 1: Get Telegram file URL
    file_info_url = f"https://api.telegram.org/bot{bot_token}/getFile?file_id={voice_file_id}"
    file_info_resp = requests.get(file_info_url)
    file_path = file_info_resp.json()["result"]["file_path"]
    file_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"

    # Step 2: Download the audio file in ogg format
    audio_bytes_ogg = requests.get(file_url).content
    audio_bytes_mp3 = convert_ogg_to_mp3(audio_bytes_ogg)

    # Step 3: Use Gemini API (or any speech_to_text service)
    language_code = assistant.language or "uz"
    transcribed_text, input_tokens, output_tokens = speech_to_text(audio_bytes_mp3, language=language_code)

    # Step 4: Trigger the regular message processor
    process_message_task.delay(chat_id=chat_id, user_message=transcribed_text, bot_token=bot_token, audio_file=audio_bytes_mp3, input_tokens=input_tokens, output_tokens=output_tokens)

@shared_task
def process_instagram_comment(account_id, comment_data):
    """Process Instagram comment and send private reply"""
    print(f"[+] Processing Instagram comment for account_id: {account_id}")
    
    integration = Integration.objects.filter(instagram_account_id=account_id).first()
    if not integration:
        print("[-] Integration not found")
        return

    # Extract incoming comment data
    media_id = comment_data.get("media",{}).get("id")
    comment_id = comment_data.get("id")
    comment_text = comment_data.get("text", "").strip()
    commenter_id = comment_data.get("from", {}).get("id")
    parent_id = comment_data.get("parent_id", None)

    if not all([media_id, comment_id, comment_text, commenter_id]):
        print("[-] Missing required comment data")
        return
    
    # Step 1: Check if the specific media has is_respond_to_all_comments=True
    if parent_id is None:

        media = InstagramMedia.objects.filter(media_id=media_id).first()
        if media:
            # 1a. Respond to all comments if flag is set
            response = InstagramCommentResponse.objects.filter(instagram_media=media).first()
            if response.is_respond_to_all_comments:
                print("[+] Media-specific: Respond to all comments")
                flow = Flow.objects.filter(comment_response=response)
                if response.comment_message_template and not integration.is_comment_response:
                        send_instagram_comment_reply(integration.api_token, comment_id, response.comment_message_template)
                #if flow exists do not reply from private message
                if response.private_message_template and not flow.exists():
                        send_instagram_private_reply(integration.api_token, account_id, comment_id, response.private_message_template)
                
                if flow.exists():
                    print("[+] Actual flow exists in that way and integartion is found")
                    send_instagram_postback(account_id=account_id, access_token=integration.api_token, recipient_comment_id=comment_id, data=flow.first(),commenter_id=commenter_id)


            else:
                print("[+] Media-specific: Respond to all comments")
                trigger_words = [tw.trigger_word.lower() for tw in response.trigger_words.all()]
                if comment_text.strip().lower() in trigger_words:
                    print(f"[+] Media-specific trigger match: {trigger_words}")
                    flow = Flow.objects.filter(comment_response=response)

                    if response.comment_message_template and not integration.is_comment_response:
                        send_instagram_comment_reply(integration.api_token, comment_id, response.comment_message_template)
                    if response.private_message_template and not flow.exists():
                        send_instagram_private_reply(integration.api_token, account_id, comment_id, response.private_message_template)
                    if flow.exists():
                        print("[+] Actual flow exists in that way and integartion is found")
                        send_instagram_postback(account_id=account_id, access_token=integration.api_token, recipient_comment_id=comment_id, data=flow.first(), commenter_id=commenter_id)
        else:       
            latest_response = InstagramCommentResponse.objects.filter(integration=integration).order_by("-created_time").first()
            print("[+ Incoming new lasted post for comment response]")
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
                    print(f"Time {media_ts_tashkent} and {latest_response.created_time}")
                    if media_ts_tashkent > latest_response.created_time:
                        if latest_response.is_respond_to_all_comments:

                            flow = Flow.objects.filter(comment_response=latest_response)
                            if latest_response.comment_message_template and not integration.is_comment_response:
                                    send_instagram_comment_reply(integration.api_token, comment_id, latest_response.comment_message_template)
                            # validate that flow does not exists
                            if latest_response.private_message_template and not flow.exists():
                                    send_instagram_private_reply(integration.api_token, account_id, comment_id, latest_response.private_message_template)
                            if flow.exists():
                                print("[+] Actual flow exists in that way and integartion is found")
                                send_instagram_postback(account_id=account_id, access_token=integration.api_token, recipient_comment_id=comment_id, data=flow.first(),commenter_id=commenter_id)

                        else:
                            print("[+] Media comment response only for specific comment")
                            trigger_words = [tw.trigger_word.lower() for tw in latest_response.trigger_words.all()]
                            if comment_text.strip().lower() in trigger_words:

                                flow = Flow.objects.filter(comment_response=latest_response)
                                print(f"[✓] Media-specific trigger match: {trigger_words}")
                                if latest_response.comment_message_template and not integration.is_comment_response:
                                    send_instagram_comment_reply(integration.api_token, comment_id, latest_response.comment_message_template)
                                if latest_response.private_message_template and not flow.exists():
                                    send_instagram_private_reply(integration.api_token, account_id, comment_id, latest_response.private_message_template)
                                if flow.exists():
                                    print("[+] Actual flow exists in that way and integartion is found")
                                    send_instagram_postback(account_id=account_id, access_token=integration.api_token, recipient_comment_id=comment_id, data=flow.first(),commenter_id=commenter_id)
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
            print("[+] Integration is comment response and new media is received")
            process_instagram_comment_message.delay(account_id=account_id, message=comment_text, comment_id=comment_id, integration_id=integration.id, media_id=media_id)
            return
    print(f"[+] Media {media_id} has parent_id: {parent_id}")

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

    print(f"[+] Handling postback event: {payload} from user: {sender_id}")

    if not payload or not sender_id:
        print("[-] Missing payload or sender_id")
        return
    inline_button_id = payload.split(":")[1]
    print(f"[+] incomming inline_button {inline_button_id}")
    user_state = InstagramUserState.objects.filter(account_id=account_id, user_id=sender_id).first()
    if user_state is None:
        print(f"[-] User state was not initialized yet {user_state}")
        return 
    
    #checking user that he subscribed or not
    status_subscription = checking_instagram_followers(access_token=access_token, recicipient_id=sender_id)
    #based on the subscrition send another way
    transition = Transition.objects.filter(from_to=user_state.current_step, action_subscription=status_subscription['is_user_follow_business'], 
                                           button_text__id=inline_button_id).first()
    if transition is None:
        print(f"[-] Transicition was not create or not found for this step {transition}")
        return
    if transition.to_step is None:
        print("[-]Transition to step is not given")
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
        print(f"[-] Error updating user state: {e}")
    send_step_message_task.delay(transition.to_step.id, account_id, sender_id, access_token)


@shared_task
def send_step_message_task(step_id, account_id, recipient_id, access_token):
    try:
        step = Step.objects.get(id=step_id)
    except Step.DoesNotExist:
        print(f"[-] Step {step_id} not found")
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
            resp = send_instagram_message(
                account_id=account_id,
                access_token=access_token,
                recipient_id=recipient_id,
                message=step.message_content
            )
        print(f"[+] Sent step message: {step.message_content}, status: {getattr(resp, 'status_code', None)}")
    except Exception as e:
        print(f"[-] Error sending step message: {e}")

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
            btns_payload.append(build_button_payload(b))

        print(f"All buttons are ready {btns_payload}")
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
        print(resp.json())
        print("[+] Sending instagram message for postback")
        print(resp)

def fetch_conversation_messages(access_token: str, conversation_id: str):
    messages = []
    base = f"https://graph.instagram.com/v23.0/{conversation_id}/messages"
    params = {
        "fields": "id,from,to,message",
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
    }

    next_url = base
    next_params = params

    while next_url:
        resp = requests.get(next_url, headers=headers, params=next_params)
        if resp.status_code != 200:
            break
        payload = resp.json() or {}
        page_items = payload.get("data", [])
        for item in page_items:
            if item.get("message") and item.get("message") != "": 
              messages.append(item.get("message"))

        paging = payload.get("paging", {})
        next_url = paging.get("next")
        next_params = None

    return messages

def fetch_all_conversations_with_messages(access_token: str):
    collected = []
    conv_url = "https://graph.instagram.com/v23.0/me/conversations"
    conv_params = {
        "fields": "id",
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
    }

    next_url = conv_url
    next_params = conv_params

    while next_url:
        resp = requests.get(next_url, headers=headers, params=next_params)
        if resp.status_code != 200:
            break
        payload = resp.json() or {}
        for conv in payload.get("data", []):
            conv_id = conv.get("id")
            if not conv_id:
                continue
            msgs = fetch_conversation_messages(
                access_token,
                conv_id,
            )
            if msgs:
              collected.append({
                "messages": msgs,
            })

        paging = payload.get("paging", {})
        next_url = paging.get("next")
        next_params = None
    return collected


@shared_task
def build_instagram_kb(integration_id: str):
    integration = Integration.objects.filter(id=integration_id).first()
    if not integration or integration.integration_type != "instagram":
        print("[-] Integration not found for Instagram")
        return
    
    if not integration.api_token or not integration.assistant:
        return

    convs = fetch_all_conversations_with_messages(integration.api_token)
    texts = []

    for c in convs:
        for t in c.get("messages", []):
            if isinstance(t, str) and t.strip():
                texts.append(t.strip())

    if not texts:
        return
    distilled = distill_company_kb_from_texts(texts, company_hint=integration.name)
    
    if not distilled:
        return
    file_content = SimpleUploadedFile(
        "instagram_knowledge_base.txt",
        distilled.encode("utf-8"),
        content_type="text/plain",
    )
    upload = AssistantFileUpload.objects.create(
        assistant=integration.assistant,
        file=file_content,
        filename="instagram_knowledge_base.txt",
    )
    # Upload distilled text directly to OpenAI and store file_id on upload
    try:
        openai_file_id = upload_knowledge_base_file(file_url=None, clear_text=distilled)
        if openai_file_id:
            upload.file_id = openai_file_id
            upload.save(update_fields=["file_id"])
            # Attach to vector store if exists
            if integration.assistant and integration.assistant.vector_id:
                batch = client.vector_stores.file_batches.create(
                    vector_store_id=integration.assistant.vector_id,
                    file_ids=[openai_file_id]
                )
                # poll until completion
                while True:
                    status = client.vector_stores.file_batches.retrieve(
                        vector_store_id=integration.assistant.vector_id,
                        batch_id=batch.id
                    )
                    if status.status in ["completed", "failed"]:
                        break
                    time.sleep(0.5)
                print("[+] Distilled KB attached to vector store")
            else:
                print("[-] Assistant has no vector store; stored file_id only")
        else:
            print("[-] Failed to upload distilled KB to OpenAI")
    except Exception as e:
        print(f"[-] Error attaching distilled KB to vector store: {e}")


@shared_task
def process_instagram_comment_message(account_id, message, comment_id, integration_id, media_id=None):
    print("[+] Process instagram comment message")
    integration = Integration.objects.filter(id=integration_id).first()
    if not integration:
        print("[-] Integration not found")
        return
    
    try:
        assistant = integration.assistant
        if not assistant:
            print("[-] No assistant found for integration ")
            return
            
        # Get or create conversation for this comment
        conversation = get_or_create_conversation(
            user_id=comment_id, 
            assistant=assistant, 
            platform="instagram", 
            chat_username=None
        )
        if media_id:
            instagram_comment_responses = InstagramCommentResponse.objects.filter(instagram_media__media_id=media_id).first()
            if instagram_comment_responses:
                send_instagram_comment_reply(access_token=integration.api_token, comment_id=comment_id, message=instagram_comment_responses.comment_message_template)
                
        # Process the comment message through AI if enabled
        response_data = None
        if assistant.ai_enabled:
            response_message, run_status, response_data = get_assistant_response_ai(
                message, assistant.assistant_id, conversation.thread_id, conversation=conversation
            )
            
            # Send response back as Instagram comment
            send_instagram_private_reply(access_token=integration.api_token, account_id=account_id, comment_id=comment_id, message=response_message)
            
            # Check if there's an amoCRM integration and create lead there
            if response_data:
                amocrm_integration = assistant.integrations.filter(integration_type="amocrm").first()
                if amocrm_integration and amocrm_integration.metadata.get('pipeline_id'):
                    # Get the created lead ID
                    from apps.assistant.models import Lead
                    lead = Lead.objects.filter(
                        assistant=assistant,
                        platform=conversation.platform,
                        username=conversation.client_full_name or conversation.username
                    ).order_by('-created_at').first()
                    
                    if lead:
                        print(f"[+] Triggering amoCRM lead creation for Lead ID: {lead.id}")
                        create_amocrm_lead.delay(lead.id, amocrm_integration.id)
            
    except Exception as e:
        print(f"[-] Error processing Instagram comment: {e}")
        import traceback
        traceback.print_exc()


@shared_task
def create_amocrm_lead(lead_id, integration_id):
    try:
        print(f"[+] Creating amoCRM lead for Lead ID: {lead_id}")
        
        # Get the lead
        lead = Lead.objects.filter(id=lead_id).first()
        if not lead:
            print(f"[-] Lead {lead_id} not found")
            return
        
        # Get the amoCRM integration
        from apps.integration.models import Integration
        from apps.shared.addons.enums import IntegrationTypes
        
        integration = Integration.objects.filter(
            id=integration_id,
            integration_type=IntegrationTypes.AMOCRM.value
        ).first()
        
        if not integration:
            print(f"[-] amoCRM integration {integration_id} not found")
            return
        
        pipeline_id = int(integration.metadata.get('pipeline_id'))
        if not pipeline_id:
            print(f"[-] Pipeline not set for integration {integration_id}")
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
        
        # Add custom fields if needed
        custom_fields = []

        # Create lead in amoCRM
        import requests
        
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
            
            print(f"[+] Lead created in amoCRM with ID: {amocrm_lead_id}")
        else:
            print(f"[-] Failed to create lead in amoCRM: {response.text}")
            
    except Exception as e:
        print(f"[-] Error creating amoCRM lead: {e}")
        import traceback
        traceback.print_exc()


def extract_relevant_fields(product):
    """
    Extract only relevant fields from product for OpenAI agent queries.
    Returns a simplified product object with only essential information.
    """
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
        'barcode': product.get('barcode', '')
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
    
    print("[+] Fetching all Billz products...")
    
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
            
            print(f"[+] Fetched page {page}: {len(products)} products (Total: {len(all_products)})")
            
            # Check if there are more pages
            # If we got fewer products than the limit, we've reached the last page
            if len(products) < limit:
                break
            
            page += 1
            
        except requests.exceptions.RequestException as e:
            print(f"[-] Error fetching page {page}: {str(e)}")
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
            print(f"[-] Integration {integration_id} not found or not Billz type")
            return
        
        if not integration.api_token or not integration.assistant:
            print(f"[-] Integration {integration_id} missing api_token or assistant")
            return
        
        assistant = integration.assistant
        
        # Fetch all products
        all_products = get_all_billz_products(integration.api_token)
        
        if not all_products:
            print(f"[-] No products fetched for integration {integration_id}")
            return
        
        print(f"[+] Fetched {len(all_products)} products for integration {integration_id}")
        
        # Convert products to JSON string
        products_json = json.dumps(all_products, ensure_ascii=False, indent=2)
        
        # Create a unique filename for this assistant's products
        filename = f"billz_products_{assistant.id}_{int(time.time())}.json"
        
        # Save to temp file first
        temp_dir = tempfile.gettempdir()
        temp_file_path = os.path.join(temp_dir, filename)
        
        with open(temp_file_path, 'w', encoding='utf-8') as f:
            f.write(products_json)
        
        print(f"[+] Saved products to temp file: {temp_file_path}")
        
        # Ensure assistant has a vector store
        if not assistant.vector_id:
            from shared.addons.ai_requests import create_assistant_and_vector_id
            success, message = create_assistant_and_vector_id(assistant, request=None)
            if not success:
                print(f"[-] Failed to create vector store for assistant {assistant.id}: {message}")
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
                print(f"[+] Deleting previous Billz products file (file_id: {previous_file_id}) from vector store")
                client.vector_stores.files.delete(
                    vector_store_id=assistant.vector_id,
                    file_id=previous_file_id
                )
                print(f"[+] Successfully deleted previous Billz products file from vector store")
            except Exception as e:
                # If file doesn't exist anymore, that's okay - just log it
                print(f"[!] Could not delete previous file (may not exist): {e}")
        
        # Upload to OpenAI using clear_text (more efficient than file URL)
        openai_file_id = upload_knowledge_base_file(file_url=None, clear_text=products_json)
        
        if not openai_file_id:
            print(f"[-] Failed to upload products to OpenAI for integration {integration_id}")
            # Clean up temp file
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
            return
        
        print(f"[+] Uploaded products to OpenAI with file_id: {openai_file_id}")
        
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
                    print(f"[+] Products successfully added to vector store for assistant {assistant.id}")
                    
                    # Update integration metadata with new file_id
                    if not integration.metadata:
                        integration.metadata = {}
                    integration.metadata['billz_products_file_id'] = openai_file_id
                    integration.metadata['billz_products_updated_at'] = time.time()
                    integration.save(update_fields=['metadata'])
                    print(f"[+] Updated integration metadata with new file_id: {openai_file_id}")
                else:
                    print(f"[-] Failed to add products to vector store: {status.status}")
            except Exception as e:
                print(f"[-] Error adding products to vector store: {e}")
        
        # Clean up temp file
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
            print(f"[+] Cleaned up temp file: {temp_file_path}")
            
    except Exception as e:
        print(f"[-] Error in fetch_and_save_billz_products: {e}")
        import traceback
        traceback.print_exc()


@shared_task
def update_billz_products_hourly():
    """
    Periodic task to update Billz products for all assistants with Billz integration.
    Runs every hour to keep product data up to date.
    """
    try:
        billz_integrations = Integration.objects.filter(
            integration_type=IntegrationTypes.BILLZ.value,
            is_active=True,
            assistant__isnull=False
        ).select_related('assistant')
        
        print(f"[+] Found {billz_integrations.count()} active Billz integrations to update")
        
        for integration in billz_integrations:
            if integration.api_token and integration.assistant:
                print(f"[+] Updating products for integration {integration.id} (assistant {integration.assistant.id})")
                fetch_and_save_billz_products.delay(str(integration.id))
            else:
                print(f"[-] Skipping integration {integration.id} - missing api_token or assistant")
                
    except Exception as e:
        print(f"[-] Error in update_billz_products_hourly: {e}")
        import traceback
        traceback.print_exc()