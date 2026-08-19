import logging

from celery import shared_task
from django.db import transaction

from apps.integration.gateways.instagram import instagram_service

from ..models import InstagramUserState, Step, Transition

logger = logging.getLogger(__name__)


@shared_task(name="apps.integration.tasks.handle_postback_event_task")
def handle_postback_event_task(msg, access_token):
    sender_id = msg.get("sender", {}).get("id")
    account_id = msg.get("recipient", {}).get("id")
    postback = msg.get("postback", {}) or {}
    payload = postback.get("payload")

    logger.info("Handling postback event: %s from user: %s", payload, sender_id)

    if not payload or not sender_id:
        logger.warning("Missing payload or sender_id")
        return

    inline_button_id = payload.split(":")[1]
    logger.info("incoming inline_button %s", inline_button_id)

    user_state = InstagramUserState.objects.filter(account_id=account_id, user_id=sender_id).first()
    if user_state is None:
        logger.warning("User state was not initialized yet")
        return

    status_subscription = instagram_service.checking_followers(
        access_token=access_token, recipient_id=sender_id
    )
    transition = Transition.objects.filter(
        from_to=user_state.current_step,
        action_subscription=status_subscription['is_user_follow_business'],
        button_text__id=inline_button_id,
    ).first()
    if transition is None:
        logger.warning("Transition not found for step %s", user_state.current_step)
        return
    if transition.to_step is None:
        logger.warning("Transition to step is not given")
        return

    try:
        with transaction.atomic():
            transition.to_step.count += 1
            transition.to_step.save()
            transition.to_step.flow.total_count += 1
            transition.to_step.flow.save()
    except Exception as e:
        logger.warning("Error updating user state: %s", e)

    send_step_message_task.delay(transition.to_step.id, account_id, sender_id, access_token)


@shared_task(name="apps.integration.tasks.send_step_message_task")
def send_step_message_task(step_id, account_id, recipient_id, access_token):
    try:
        step = Step.objects.get(id=step_id)
    except Step.DoesNotExist:
        logger.warning("Step %s not found", step_id)
        return

    buttons = list(step.extra_button.all())

    try:
        if buttons:
            resp = instagram_service.send_step_template(
                access_token=access_token, recipient_id=recipient_id, step=step
            )
            if resp is not None and resp.status_code == 200:
                InstagramUserState.objects.filter(
                    account_id=account_id, user_id=recipient_id
                ).update(current_step=step)
        else:
            resp = instagram_service.send_message(
                account_id=account_id,
                access_token=access_token,
                recipient_id=recipient_id,
                message=step.message_content
            )
        logger.info("Sent step message: %s, status: %s", step.message_content,
                    getattr(resp, 'status_code', None))
    except Exception as e:
        logger.warning("Error sending step message: %s", e)
