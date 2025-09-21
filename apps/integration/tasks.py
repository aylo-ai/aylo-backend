import requests
import time
from celery import shared_task
from datetime import datetime
import pytz

from apps.shared.addons.enums import SenderTypes, ConversationStatuses
from shared.addons.instagram import send_instagram_message, send_instagram_private_reply, send_instagram_comment_reply, send_instagram_postback
from shared.addons.telegram import send_telegram_message, send_telegram_action
from shared.addons.utils import get_assistant_response_ai, handle_start_command, get_or_create_conversation, create_message, \
    speech_to_text, convert_ogg_to_mp3, process_instagram_audio
from apps.assistant.models import Assistant
from .models import TelegramGroupIntegration, Integration, InstagramMedia, InstagramCommentResponse, Flow, CommentResponseButton, Step, Transition, InstagramUserState
from shared.addons.redis import publish_message_to_ws, redis_client

WAIT_SECONDS = 5

@shared_task
def process_message_task(chat_id, user_message, bot_token, chat_username=None, username=None, audio_file=None, input_tokens=None, output_tokens=None):
    print(f"celery task is started with chat_id: {chat_id}, user_message: {user_message}, bot_token: {bot_token}")
    assistant = Assistant.objects.filter(integrations__api_token=bot_token).first()
    print(f"Assistant: {assistant}")
    if not assistant:
        print("No assistant found, skipping processing")
        return  # No assistant found, skip processing

    # Handle `/start` command
    if user_message == '/start':
        print(f"Handling start command for assistant: {assistant}")
        handle_start_command(chat_id, assistant, bot_token, chat_username, username)
        return

    # Handle regular messages
    conversation = get_or_create_conversation(chat_id, assistant, token=bot_token, chat_username=chat_username, username=username)
    print(f"Conversation: {conversation}")
    if conversation.status == ConversationStatuses.ESCALATED.value or not assistant.is_active:
        data = create_message(conversation=conversation, sender=SenderTypes.USER.value, content=user_message, 
                              audio_file=audio_file, input_tokens=input_tokens, output_tokens=output_tokens)
        publish_message_to_ws(conversation.id, user_message, sender="user", data=data, assistant_id=assistant.id)
        print(f"Message created for user: {user_message}")
        return

    response_data = None
    response_message = None
    #send typing action
    send_telegram_action(chat_id, bot_token)

    data = create_message(conversation=conversation, sender=SenderTypes.USER.value, content=user_message, audio_file=audio_file, input_tokens=input_tokens, output_tokens=output_tokens)
    publish_message_to_ws(conversation_id=conversation.id, message=user_message, sender='user', data=data, assistant_id=assistant.id)
    if assistant.ai_enabled:
        response_message, run_status, response_data = get_assistant_response_ai(user_message, 
                                                                                assistant.assistant_id, 
                                                                                conversation.thread_id,
                                                                                conversation=conversation
                                                                                )
        username = getattr(response_data, 'username', None)
        platform = getattr(response_data, 'platform', None)
        username_link = None
        if username:
            if platform and platform.lower() == "telegram":
                username_link = f"@{username}"
            elif platform and platform.lower() == "instagram":
                username_link = f"https://www.instagram.com/{username}"

        response_lines = [
                "🎉 *New Lead Created!*\n",
                f"👤 *Full Name: {response_data.full_name}  " if getattr(response_data, 'full_name', None) else None,
                f"📞 *Phone Number: {response_data.phone_number}  " if getattr(response_data, 'phone_number', None) not in [None, ""] else None,
                f"📧 *Email: {response_data.email}  " if getattr(response_data, 'email', None) not in [None, ""] else None,
                f"📦 *Interested Product: {response_data.product}  " if getattr(response_data, 'product', None) else None,
                f"📱 *Platform: {platform}  " if platform else None,
                f"🔗 *Username: {username_link}\n" if username_link else None,
                "\n✅ Please follow up accordingly."
            ]
        response_text = "\n".join([line for line in response_lines if line])
    print(f"Response message: {response_message}")

    # Send response to user
    print(f"Response data: {response_data}")
    if response_data:
        
        telegram_integration = assistant.integrations.filter(integration_type="telegram").first()
        telegram_groups = TelegramGroupIntegration.objects.filter(
            integration=telegram_integration
        ).all()
        for telegram_group in telegram_groups:
            send_telegram_message(telegram_group.group_id, response_text, bot_token)
            telegram_group.lead_count += 1
            telegram_group.save()
    if response_message:
        send_telegram_message(chat_id, response_message, bot_token)
        data = create_message(conversation=conversation, sender=SenderTypes.ASSISTANT.value, content=response_message, run_status=run_status)
        publish_message_to_ws(conversation.id, response_message, sender="assistant", assistant_id=assistant.id,data=data)

@shared_task
def process_instagram_message(account_id, combined_message, user_message, audio_file=None):
    print(f"celery task is started with account_id: {account_id}, user_message: {user_message}")
    assistant = Assistant.objects.filter(integrations__instagram_account_id=account_id).first()
    print(f"Assistant: {assistant}")
    if not assistant:
        return
    
    integration = assistant.integrations.filter(integration_type="instagram", instagram_account_id=account_id).first()
    print(f"Integration: {integration}")
    if not integration:
        return
    
    sender_id = user_message[0].get("sender", {}).get("id")
    print(f"Sender ID: {sender_id}")
    if not sender_id:
        return
    input_tokens = 0
    output_tokens = 0
    if audio_file:
        combined_message,input_tokens,output_tokens = process_instagram_audio(audio_file, assistant.language)
    print(f"Message text: {combined_message}")
    if not combined_message:
        return
    conversation = get_or_create_conversation(sender_id, assistant, platform="instagram", chat_username=None)
    if conversation.client_full_name is None:
        conversation.client_full_name = get_user_info(integration.api_token, sender_id).get("username", None)
        conversation.save()
    print(f"Conversation: {conversation}, thread_id: {conversation.thread_id}")
    if conversation.status == ConversationStatuses.ESCALATED.value or not assistant.is_active:
        data = create_message(conversation=conversation, sender=SenderTypes.USER.value, content=combined_message, 
                              audio_file=audio_file, input_tokens=input_tokens, output_tokens=output_tokens)
        print("publish message to web socket")
        publish_message_to_ws(conversation.id, combined_message, sender="user", data=data, assistant_id=assistant.id)
        return
    print("Sending message to web socket")
    data = create_message(conversation=conversation, sender=SenderTypes.USER.value, content=combined_message, 
                          audio_file=audio_file, input_tokens=input_tokens, output_tokens=output_tokens)
    publish_message_to_ws(conversation.id, combined_message, sender="user", data=data, assistant_id=assistant.id)

    response_message, run_status, response_data = get_assistant_response_ai(combined_message, assistant.assistant_id, conversation.thread_id, conversation=conversation)
    print(f"Assistant response in Instagram: {response_message}")
    # Handle lead creation if response_data exists
    username = getattr(response_data, 'username', None)
    platform = getattr(response_data, 'platform', None)
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
            print(f"Lead sent to telegram group: {telegram_group.group_id}")
    # handling wait message
    
    # send response to user
    send_instagram_message(account_id, integration.api_token, sender_id, response_message)
    print(f"starting to create message: {response_message}, conversation: {conversation}")
    data = create_message(conversation=conversation, sender=SenderTypes.ASSISTANT.value, content=response_message, run_status=run_status)
    print(f"Sent message to Instagram user: {sender_id} with message: {response_message}")
    publish_message_to_ws(conversation.id, response_message, sender="assistant", assistant_id=assistant.id, data=data)
    print("Sent message to web socket")

@shared_task
def process_voice_task(chat_id, voice_file_id, bot_token):
    print(f"Voice task started: {chat_id}, file_id: {voice_file_id}")

    assistant = Assistant.objects.filter(integrations__api_token=bot_token).first()
    if not assistant:
        return

    # Step 1: Get Telegram file URL
    file_info_url = f"https://api.telegram.org/bot{bot_token}/getFile?file_id={voice_file_id}"
    file_info_resp = requests.get(file_info_url)
    file_path = file_info_resp.json()["result"]["file_path"]

    file_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
    print(f"File URL: {file_url}, file_path: {file_path}")
    # Step 2: Download the audio file in ogg format
    audio_bytes_ogg = requests.get(file_url).content
    print(f"Audio bytes ogg: {audio_bytes_ogg}")
    audio_bytes_mp3 = convert_ogg_to_mp3(audio_bytes_ogg)
    print(f"Audio bytes mp3: {audio_bytes_mp3}")

    # Step 3: Use Gemini API (or any speech_to_text service)
    language_code = assistant.language or "uz"  # fallback
    print(f"Language code: {language_code}")
    transcribed_text, input_tokens, output_tokens = speech_to_text(audio_bytes_mp3, language=language_code)
    print(f"transcribed_text: {transcribed_text}")
    print(f"Transcribed text: {transcribed_text}")

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

    print(f"Comment ID: {comment_id}, Text: '{comment_text}', Commenter ID: {commenter_id}")

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
                print("[✓] Media-specific: Respond to all comments (is_respond_to_all_comments=True)")
                if response.comment_message_template:
                        send_instagram_comment_reply(integration.api_token, comment_id, response.comment_message_template)
                if response.private_message_template:
                        send_instagram_private_reply(integration.api_token, account_id, comment_id, response.private_message_template, response)
                flow = Flow.objects.filter(comment_response=response)
                if flow.exists():
                    print("[+] Actual flow exists in that way")
                    if integration.instagram_account_id == '17841461784331766':
                        print("[+] Actual flow exists in that way and integartion is found")
                        send_instagram_postback(account_id=account_id, access_token=integration.api_token, recipient_id=commenter_id, data=flow.first())


            else:
                print("[✓] Media-specific: Respond to all comments (is_respond_to_all_comments=False)")
                trigger_words = [tw.trigger_word.lower() for tw in response.trigger_words.all()]
                if comment_text.strip().lower() in trigger_words:
                    print(f"[✓] Media-specific trigger match: {trigger_words}")
                    if response.comment_message_template:
                        send_instagram_comment_reply(integration.api_token, comment_id, response.comment_message_template)
                    if response.private_message_template:
                        send_instagram_private_reply(integration.api_token, account_id, comment_id, response.private_message_template)
                    flow = Flow.objects.filter(comment_response=response)
                    if flow.exists():
                        print("[+] Actual flow exists in that way")
                        if integration.instagram_account_id == '17841461784331766':
                            print("[+] Actual flow exists in that way and integartion is found")
                            send_instagram_postback(account_id=account_id, access_token=integration.api_token, recipient_id=commenter_id, data=flow.first())
        else:       
            latest_response = InstagramCommentResponse.objects.filter(integration=integration).order_by("-created_time").first()
            print(latest_response)
            if latest_response and not latest_response.instagram_media.exists():
                access_token = integration.api_token
                url = "https://graph.instagram.com/v23.0/me/media"
                params = {
                    "access_token": access_token,
                    "fields": "id,media_type,media_url,username,timestamp,caption,comments_count,like_count,permalink,thumbnail_url,children{media_type,media_url}"
                }
                response = requests.get(url, params=params)
                print(response)
                if response.status_code == 200:
                    media_first = response.json()['data'][0]
                    media_ts_str = media_first["timestamp"]  # "2025-09-14T05:07:15+0000"
                    media_ts = datetime.strptime(media_ts_str, "%Y-%m-%dT%H:%M:%S%z")
                    # Convert to Asia/Tashkent timezone
                    media_ts_tashkent = media_ts.astimezone(pytz.timezone("Asia/Tashkent"))
                    print(f"Time {media_ts_tashkent} and {latest_response.created_time}")
                    if media_ts_tashkent > latest_response.created_time:
                        print("are good for it")
                        if latest_response.is_respond_to_all_comments:
                            print("[✓] Media-specific: Respond to all comments (is_respond_to_all_comments=True)")
                            if latest_response.comment_message_template:
                                    send_instagram_comment_reply(integration.api_token, comment_id, latest_response.comment_message_template)
                            if latest_response.private_message_template:
                                    send_instagram_private_reply(integration.api_token, account_id, comment_id, latest_response.private_message_template)


                        else:
                            print("[✓] Media-specific: Respond to all comments (is_respond_to_all_comments=False)")
                            trigger_words = [tw.trigger_word.lower() for tw in latest_response.trigger_words.all()]
                            if comment_text.strip().lower() in trigger_words:
                                print(f"[✓] Media-specific trigger match: {trigger_words}")
                                if latest_response.comment_message_template:
                                    send_instagram_comment_reply(integration.api_token, comment_id, latest_response.comment_message_template)
                                if latest_response.private_message_template:
                                    send_instagram_private_reply(integration.api_token, account_id, comment_id, latest_response.private_message_template)
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
                        print("created successfully")

            print("[!] No matching response found for this comment.")
    else:
        print(f"[+] Media {media_id} has parent_id: {parent_id}")

@shared_task
def process_collected_messages(chat_id, bot_token=None, messaging=None, chat_username=None, username=None):
    user_key = f"messages:{chat_id}"
    last_seen_key = f"last_seen:{chat_id}"
    print(f"chat_username: {chat_username}")
    print(f"username: {username}")
    # Check if we should wait longer
    last_seen = float(redis_client.get(last_seen_key) or 0)
    if time.time() - last_seen < WAIT_SECONDS:
        return  # Another message came in recently, skip for now

    messages = redis_client.lrange(user_key, 0, -1)
    if not messages:
        return

    combined_message = ", ".join(m for m in messages)
    print(f"Combined message: {combined_message}")

    # Clean up Redis
    redis_client.delete(user_key)
    redis_client.delete(last_seen_key)

    # Call your existing task
    if bot_token:
        process_message_task.delay(chat_id, combined_message, bot_token,chat_username, username)
    else:
        process_instagram_message.delay(account_id = chat_id, combined_message = combined_message, user_message = messaging)

def response_matches_comment(response, comment_text):
    for trigger in response.trigger_words.all():
        if trigger.trigger_word.lower() in comment_text.lower():
            return True
    return False

def get_user_info(access_token, user_id):
    url = f"https://graph.instagram.com/v23.0/{user_id}"
    params = {
        "access_token": access_token,
        "fields": "id, username"
    }
    response = requests.get(url, params=params)
    return response.json()


@shared_task
def handle_comment_event_task(entry, value, access_token):
    """
    Handle comment events and trigger flows
    """
    comment_id = value.get("id") or value.get("comment_id")
    sender = value.get("from", {})
    sender_id = sender.get("id")
    account_id = entry.get("id") or entry.get("account_id")
    comment_text = value.get("text", "").strip()

    print(f"[+] Handling comment event: {comment_text} from user: {sender_id}")

    # Find integration for this account
    integration = Integration.objects.filter(instagram_account_id=account_id).first()
    if not integration:
        print(f"[-] No integration found for account: {account_id}")
        return

    # Find comment response for this integration
    comment_response = InstagramCommentResponse.objects.filter(integration=integration).first()
    if not comment_response:
        print(f"[-] No comment response found for integration: {integration.id}")
        return

    # Check if comment should trigger a flow
    should_trigger_flow = False
    
    # Check trigger words
    if comment_response.is_respond_to_all_comments:
        should_trigger_flow = True
    else:
        trigger_words = [tw.trigger_word.lower() for tw in comment_response.trigger_words.all()]
        if any(word in comment_text.lower() for word in trigger_words):
            should_trigger_flow = True

    if should_trigger_flow:
        # Find flow for this comment response
        flow = Flow.objects.filter(comment_response=comment_response, is_active=True).first()
        if flow:
            print(f"[+] Triggering flow: {flow.title}")
            execute_flow_step_task.delay(flow.id, sender_id, account_id, comment_id, access_token)
        else:
            print(f"[-] No active flow found for comment response: {comment_response.id}")
    else:
        print(f"[-] Comment does not match trigger words: {comment_text}")


@shared_task
def execute_flow_step_task(flow_id, sender_id, account_id, comment_id, access_token):
    """Execute a flow step for a user"""
    try:
        flow = Flow.objects.get(id=flow_id)
    except Flow.DoesNotExist:
        print(f"[-] Flow {flow_id} not found")
        return

    # Get or create user state
    user_state, created = InstagramUserState.objects.get_or_create(
        account_id=str(account_id),
        user_id=str(sender_id),
        defaults={"current_step": None}
    )

    # Get current step or first step
    current_step = user_state.current_step
    if not current_step:
        current_step = flow.steps.order_by("id").first()
        if not current_step:
            print(f"[-] No steps found for flow: {flow.id}")
            return
        user_state.current_step = current_step
        user_state.save()

    print(f"[+] Executing step: {current_step.message_content}")

    # Get buttons for this step
    buttons = list(current_step.extra_button.all())

    # Get image URL if exists
    image_url = None
    if current_step.message_image:
        try:
            image_url = current_step.message_image.url
        except Exception:
            image_url = None

    # Send message with or without buttons
    try:
        if buttons:
            # Use postback for messages with buttons
            resp = send_instagram_postback(
                account_id=account_id,
                access_token=access_token,
                recipient_comment_id=comment_id,
                title=current_step.message_content,
                image_url=image_url,
                buttons=buttons
            )
        else:
            # Use regular message for text-only messages
            resp = send_instagram_message(
                account_id=account_id,
                access_token=access_token,
                recipient_id=comment_id,
                message=current_step.message_content
            )
        print(f"[+] Sent step message: {current_step.message_content}, status: {getattr(resp, 'status_code', None)}")
    except Exception as e:
        print(f"[-] Error sending message: {e}")


@shared_task
def handle_postback_event_task(msg, access_token):
    """
    Handle postback events (button clicks) and advance flow
    """
    sender_id = msg.get("sender", {}).get("id")
    account_id = msg.get("recipient", {}).get("id")
    postback = msg.get("postback", {}) or {}
    payload = postback.get("payload") or postback.get("data") or ""

    print(f"[+] Handling postback event: {payload} from user: {sender_id}")

    if not payload or not sender_id:
        print("[-] Missing payload or sender_id")
        return

    # Parse payload "inline_button:{id}"
    if payload.startswith("inline_button:"):
        btn_id = payload.split("inline_button:")[1]
        try:
            btn_obj = CommentResponseButton.objects.get(id=btn_id)
            print(f"[+] Found button: {btn_obj.text}")
        except CommentResponseButton.DoesNotExist:
            print(f"[-] Button {btn_id} not found")
            return

        # Find user state
        try:
            user_state = InstagramUserState.objects.get(account_id=str(account_id), user_id=str(sender_id))
            print(f"[+] Found user state for {sender_id}")
        except InstagramUserState.DoesNotExist:
            print(f"[-] User state not found for {account_id}:{sender_id}")
            return

        # Find transition for this button from current step
        transition = Transition.objects.filter(
            from_to=user_state.current_step, 
            button_text=btn_obj
        ).first()

        if not transition:
            print(f"[-] No transition found for button {btn_obj.text} from step {user_state.current_step.id}")
            return

        # Move to next step
        next_step = transition.to_step
        if next_step:
            print(f"[+] Moving to next step: {next_step.message_content}")
            
            # Update user state
            user_state.current_step = next_step
            user_state.save()

            # Send next step message
            send_step_message_task.delay(next_step.id, account_id, sender_id, access_token)
        else:
            # End of flow
            print(f"[+] User {sender_id} reached end of flow")
            user_state.current_step = None
            user_state.save()


@shared_task
def send_step_message_task(step_id, account_id, recipient_id, access_token):
    """Send a step message with buttons"""
    try:
        step = Step.objects.get(id=step_id)
    except Step.DoesNotExist:
        print(f"[-] Step {step_id} not found")
        return

    buttons = list(step.extra_button.all())
    
    # Get image URL if exists
    image_url = None
    if step.message_image:
        try:
            image_url = step.message_image.url
        except Exception:
            image_url = None

    try:
        if buttons:
            # Use postback for messages with buttons
            resp = send_instagram_postback(
                account_id=account_id,
                access_token=access_token,
                recipient_comment_id=recipient_id,
                title=step.message_content,
                image_url=image_url,
                buttons=buttons
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