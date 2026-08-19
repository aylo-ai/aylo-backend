import redis as redis_lib
from django.conf import settings
from django.db import connection
from rest_framework.views import APIView

from apps.shared.addons.validations import success_response
from apps.shared.permissions import IsAdmin


class DashboardSystemHealthView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request, *args, **kwargs):
        health = {
            'database': {'status': 'unknown', 'detail': ''},
            'redis': {'status': 'unknown', 'detail': ''},
            'celery': {'status': 'unknown', 'detail': ''},
            'storage': {'status': 'unknown', 'detail': ''},
        }

        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            health['database'] = {'status': 'healthy', 'detail': 'PostgreSQL connected'}
        except Exception as e:
            health['database'] = {'status': 'unhealthy', 'detail': str(e)}

        try:
            r = redis_lib.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                password=settings.REDIS_PASSWORD,
                socket_timeout=3,
            )
            r.ping()
            info = r.info('memory')
            used_memory = info.get('used_memory_human', 'N/A')
            health['redis'] = {'status': 'healthy', 'detail': f'Connected, memory: {used_memory}'}
        except Exception as e:
            health['redis'] = {'status': 'unhealthy', 'detail': str(e)}

        try:
            from config.celery import app as celery_app
            inspector = celery_app.control.inspect(timeout=3)
            active = inspector.active()
            if active is not None:
                worker_count = len(active)
                task_count = sum(len(tasks) for tasks in active.values())
                health['celery'] = {
                    'status': 'healthy',
                    'detail': f'{worker_count} worker(s), {task_count} active task(s)',
                    'workers': list(active.keys()),
                }
            else:
                health['celery'] = {'status': 'unhealthy', 'detail': 'No workers responding'}
        except Exception as e:
            health['celery'] = {'status': 'unhealthy', 'detail': str(e)}

        try:
            from django.core.files.storage import default_storage
            health['storage'] = {'status': 'healthy', 'detail': type(default_storage).__name__}
        except Exception as e:
            health['storage'] = {'status': 'unhealthy', 'detail': str(e)}

        overall = 'healthy' if all(s['status'] == 'healthy' for s in health.values()) else 'degraded'
        return success_response(
            data={'overall': overall, 'services': health},
            message='System health check completed',
            code=200
        )
