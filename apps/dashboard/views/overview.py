from django.db.models import Count, F, Q, Sum
from django.utils import timezone
from rest_framework.views import APIView

from apps.assistant.models import Assistant, Conversation, Message
from apps.dashboard.serializers.overview import (
    DashboardEnhancedStatsSerializer,
    DashboardSerializer,
    DashboardStatisticsSerializer,
)
from apps.payment.models import Transaction
from apps.shared.addons.enums import SenderTypes
from apps.shared.addons.validations import success_response
from apps.shared.permissions import IsDashboardUser
from apps.user.models import User


class DashboardView(APIView):
    serializer_class = DashboardSerializer
    permission_classes = [IsDashboardUser]

    def get(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        return success_response(data=serializer.data, message="Dashboard data retrieved successfully", code=200)


class DashboardEnhancedStatsView(APIView):
    permission_classes = [IsDashboardUser]

    def get(self, request, *args, **kwargs):
        serializer = DashboardEnhancedStatsSerializer(data={})
        serializer.is_valid(raise_exception=True)
        return success_response(
            data=serializer.to_representation(None),
            message="Enhanced dashboard stats retrieved",
            code=200
        )


class DashboardStatisticsView(APIView):
    serializer_class = DashboardStatisticsSerializer
    permission_classes = [IsDashboardUser]

    def get(self, request, *args, **kwargs):
        date_filter = request.query_params.get("date_filter")
        type_filter = request.query_params.get("type_filter")
        serializer = self.serializer_class(
            data=request.data,
            context={"date_filter": date_filter, "type_filter": type_filter}
        )
        serializer.is_valid(raise_exception=True)
        return success_response(data=serializer.data, message="Dashboard statistics retrieved successfully", code=200)


class DashboardAICostBreakdownView(APIView):
    permission_classes = [IsDashboardUser]

    def get(self, request, *args, **kwargs):
        period = request.query_params.get('period', '30d')
        now = timezone.now().date()
        if period == '7d':
            start = now - timezone.timedelta(days=7)
        elif period == '6m':
            start = now - timezone.timedelta(days=180)
        elif period == '1y':
            start = now - timezone.timedelta(days=365)
        elif period == 'all':
            start = None
        else:
            start = now - timezone.timedelta(days=30)

        qs = Message.objects.filter(sender=SenderTypes.ASSISTANT.value)
        if start:
            qs = qs.filter(created_time__date__gte=start)

        by_assistant = (
            qs.values(
                assistant_name=F('conversation__assistant__name'),
                assistant_id=F('conversation__assistant__id'),
            )
            .annotate(
                total_input_tokens=Sum('input_tokens'),
                total_output_tokens=Sum('output_tokens'),
                message_count=Count('id'),
            )
            .order_by('-total_input_tokens')
        )

        results = []
        for row in by_assistant:
            inp = row['total_input_tokens'] or 0
            out = row['total_output_tokens'] or 0
            cost = (inp / 1000000 * 2.5) + (out / 1000000 * 10)
            results.append({
                'assistant_id': str(row['assistant_id']),
                'assistant_name': row['assistant_name'],
                'input_tokens': inp,
                'output_tokens': out,
                'message_count': row['message_count'],
                'estimated_cost': f'${cost:.2f}',
            })

        total_input = sum(r['input_tokens'] for r in results)
        total_output = sum(r['output_tokens'] for r in results)
        total_cost = (total_input / 1000000 * 2.5) + (total_output / 1000000 * 10)

        return success_response(
            data={
                'period': period,
                'total_input_tokens': total_input,
                'total_output_tokens': total_output,
                'total_estimated_cost': f'${total_cost:.2f}',
                'by_assistant': results,
            },
            message='AI cost breakdown retrieved',
            code=200
        )


class DashboardGlobalSearch(APIView):
    permission_classes = [IsDashboardUser]

    def get(self, request):
        q = request.query_params.get('q', '').strip()
        if len(q) < 2:
            return success_response(data={'results': []}, message='Query too short', code=200)

        results = []

        users = User.objects.filter(
            Q(username__icontains=q) | Q(first_name__icontains=q) |
            Q(last_name__icontains=q) | Q(email__icontains=q) |
            Q(phone_number__icontains=q)
        )[:5]
        for u in users:
            results.append({
                'type': 'user',
                'id': str(u.id),
                'title': f'{u.first_name or ""} {u.last_name or ""}'.strip() or u.username,
                'subtitle': u.email or u.phone_number,
                'url': f'/users/{u.id}',
            })

        assistants = Assistant.objects.filter(
            Q(name__icontains=q) | Q(company_name__icontains=q)
        )[:5]
        for a in assistants:
            results.append({
                'type': 'assistant',
                'id': str(a.id),
                'title': a.name,
                'subtitle': a.company_name,
                'url': f'/assistants/{a.id}',
            })

        conversations = Conversation.objects.filter(
            Q(client_full_name__icontains=q) | Q(username__icontains=q) |
            Q(assistant__name__icontains=q)
        )[:5]
        for c in conversations:
            results.append({
                'type': 'conversation',
                'id': str(c.id),
                'title': c.client_full_name or c.username or 'Unknown',
                'subtitle': f'{c.assistant.name} - {c.platform}',
                'url': f'/conversations/{c.id}',
            })

        transactions = Transaction.objects.filter(
            Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q) |
            Q(user__email__icontains=q) | Q(transaction_id__icontains=q)
        )[:5]
        for t in transactions:
            results.append({
                'type': 'transaction',
                'id': str(t.id),
                'title': f'{t.amount} {t.currency} - {t.status}',
                'subtitle': t.user.username if t.user else 'Unknown',
                'url': '/transactions',
            })

        return success_response(data={'results': results}, message='Search completed', code=200)
