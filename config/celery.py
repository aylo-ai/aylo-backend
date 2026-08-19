from __future__ import absolute_import, unicode_literals

import os

from celery import Celery
from kombu import Queue

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('repli')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

app.conf.task_routes = {
    'apps.integration.tasks.process_message_task': {'queue': 'ai'},
    'apps.integration.tasks.process_instagram_message': {'queue': 'ai'},
    'apps.integration.tasks.process_collected_messages': {'queue': 'ai'},
    'apps.integration.tasks.process_voice_task': {'queue': 'ai'},
    'apps.integration.tasks.process_photo_task': {'queue': 'ai'},
    'apps.integration.tasks.process_shared_post_message': {'queue': 'ai'},
    'apps.integration.tasks.process_instagram_comment': {'queue': 'ai'},
    'apps.integration.tasks.process_instagram_comment_message': {'queue': 'ai'},
    'apps.integration.tasks.handle_postback_event_task': {'queue': 'ai'},
    'apps.integration.tasks.send_step_message_task': {'queue': 'ai'},
    'apps.payment.tasks.process_monthly_subscriptions': {'queue': 'billing'},
    'apps.integration.tasks.send_broadcast_task': {'queue': 'broadcast'},
    'apps.integration.tasks.send_message_integration_task': {'queue': 'broadcast'},
    'apps.integration.tasks.update_billz_products_hourly': {'queue': 'sync'},
    'apps.integration.tasks.fetch_and_save_billz_products': {'queue': 'sync'},
    'apps.assistant.tasks.daily_statistics_assistant': {'queue': 'sync'},
    'apps.assistant.tasks.process_follow_ups': {'queue': 'sync'},
    'apps.assistant.tasks.index_assistant_file': {'queue': 'sync'},
}

app.conf.task_queues = tuple(
    Queue(name) for name in ('celery', 'default', 'ai', 'billing', 'broadcast', 'sync')
)

app.conf.task_default_queue = 'default'
app.conf.task_acks_late = True
app.conf.task_reject_on_worker_lost = True
app.conf.worker_prefetch_multiplier = 1
