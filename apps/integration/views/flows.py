from django.utils.translation import gettext_lazy as _
from rest_framework import generics, permissions
from rest_framework.exceptions import NotFound

from apps.integration.models import (
    CommentResponseButton,
    Flow,
    InstagramCommentResponse,
    Step,
    Transition,
)
from apps.integration.serializers import (
    CommentResponseButtonSerializer,
    InstagramCommentResponseFlowSerializer,
    StepSerializer,
    TransitionSerializer,
)
from apps.integration.views.mixins import (
    IntegrationOwnedQuerysetMixin,
    owned_integrations,
)
from apps.shared.addons.validations import error_response, success_response


class InstagramCommentResponseFlowListCreateView(IntegrationOwnedQuerysetMixin,
                                                 generics.ListCreateAPIView):
    owner_path = "comment_response__integration"
    queryset = Flow.objects.all()
    serializer_class = InstagramCommentResponseFlowSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return super().get_queryset().filter(comment_response_id=self.kwargs.get('pk'))

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["comment_response_id"] = self.kwargs.get("pk")
        return context

    def create(self, request, *args, **kwargs):
        if not InstagramCommentResponse.objects.filter(
            id=self.kwargs.get("pk"),
            integration__in=owned_integrations(request.user),
        ).exists():
            raise NotFound()
        return super().create(request, *args, **kwargs)


class InstagramFlowTransitionListCreateView(IntegrationOwnedQuerysetMixin,
                                            generics.ListCreateAPIView):
    owner_path = "from_to__flow__comment_response__integration"
    queryset = Transition.objects.all()
    serializer_class = TransitionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def _owned_flow(self):
        return Flow.objects.filter(
            id=self.kwargs.get("pk"),
            comment_response__integration__in=owned_integrations(self.request.user),
        ).first()

    def get_queryset(self):
        return super().get_queryset().filter(from_to__flow_id=self.kwargs.get("pk"))

    def create(self, request, *args, **kwargs):
        flow_id = self.kwargs.get("pk")
        if self._owned_flow() is None:
            raise NotFound()
        is_many = isinstance(request.data, list)
        serializer = self.get_serializer(data=request.data, many=is_many)
        serializer.is_valid(raise_exception=True)

        def _validate_transition(datum):
            from_step = datum.get("from_to")
            to_step = datum.get("to_step")
            from_step_id = getattr(from_step, "id", from_step)
            to_step_id = getattr(to_step, "id", to_step)

            if from_step:
                if not Step.objects.filter(id=from_step_id, flow_id=flow_id).exists():
                    raise ValueError("from_to step does not belong to this flow")
            if to_step:
                if not Step.objects.filter(id=to_step_id, flow_id=flow_id).exists():
                    raise ValueError("to_step does not belong to this flow")
        try:
            if is_many:
                for item in serializer.validated_data:
                    _validate_transition(item)
            else:
                _validate_transition(serializer.validated_data)
        except ValueError as e:
            return error_response(message=str(e), code=400)

        self.perform_create(serializer)
        return success_response(data=serializer.data)


class TransitionRetrieveUpdateDestroyView(IntegrationOwnedQuerysetMixin, generics.RetrieveUpdateDestroyAPIView):
    owner_path = "from_to__flow__comment_response__integration"
    queryset = Transition.objects.all()
    serializer_class = TransitionSerializer
    permission_classes = [permissions.IsAuthenticated]


    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        from_to = serializer.validated_data.get("from_to") or instance.from_to
        to_step = serializer.validated_data.get("to_step") or instance.to_step
        if to_step and from_to.flow_id != to_step.flow_id:
            return error_response(message=_("Steps must belong to the same flow"), code=400)
        self.perform_update(serializer)
        return success_response(message=_("Transition muvaffaqiyatli o'zgartirildi"), data=serializer.data, code=200)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return success_response(message=_("Transition muvaffaqiyatli o'chirildi"), code=204)


class FlowRetrieveUpdateDestroyView(IntegrationOwnedQuerysetMixin, generics.RetrieveUpdateDestroyAPIView):
    owner_path = "comment_response__integration"
    queryset = Flow.objects.all()
    serializer_class = InstagramCommentResponseFlowSerializer
    permission_classes = [permissions.IsAuthenticated]


    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(message=_("Flow muvaffaqiyatli olindi"), data=serializer.data, code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return success_response(message=_("Flow muvaffaqiyatli o'zgartirildi"), data=serializer.data, code=200)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return success_response(message=_("Flow muvaffaqiyatli o'chirildi"), code=204)


class StepRetrieveUpdateDestroyView(IntegrationOwnedQuerysetMixin, generics.RetrieveUpdateDestroyAPIView):
    owner_path = "flow__comment_response__integration"
    queryset = Step.objects.all()
    serializer_class = StepSerializer
    permission_classes = [permissions.IsAuthenticated]


    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(message=_("Step muvaffaqiyatli olindi"), data=serializer.data, code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        extra_buttons = request.data.pop("extra_buttons", None)
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        if extra_buttons is not None:
            instance.extra_button.clear()
            for btn in extra_buttons:
                btn_obj = CommentResponseButton.objects.create(**btn)
                instance.extra_button.add(btn_obj)
        return success_response(message=_("Step muvaffaqiyatli o'zgartirildi"), data=self.get_serializer(instance).data, code=200)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return success_response(message=_("Step muvaffaqiyatli o'chirildi"), code=204)


class CommentResponseButtonListCreateView(generics.ListCreateAPIView):
    queryset = CommentResponseButton.objects.all()
    serializer_class = CommentResponseButtonSerializer
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return success_response(message=_("Tugmalar muvaffaqiyatli olindi"), data=serializer.data, code=200)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return success_response(message=_("Tugma muvaffaqiyatli yaratildi"), data=serializer.data, code=201)


class CommentResponseButtonRetrieveUpdateDestroyView(IntegrationOwnedQuerysetMixin, generics.RetrieveUpdateDestroyAPIView):
    owner_path = "steps__flow__comment_response__integration"
    queryset = CommentResponseButton.objects.all()
    serializer_class = CommentResponseButtonSerializer
    permission_classes = [permissions.IsAuthenticated]


    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(message=_("Tugma muvaffaqiyatli olindi"), data=serializer.data, code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return success_response(message=_("Tugma muvaffaqiyatli o'zgartirildi"), data=serializer.data, code=200)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return success_response(message=_("Tugma muvaffaqiyatli o'chirildi"), code=204)
