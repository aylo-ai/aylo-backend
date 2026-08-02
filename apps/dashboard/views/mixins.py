"""Response-shape mixins shared by the dashboard views.

Every dashboard endpoint answers through `success_response`, and the list /
retrieve / create / update / destroy bodies were copy-pasted across ~25 view
classes with nothing but the message text differing. These mixins hold the one
copy; a view supplies the message via the corresponding class attribute.

The shapes here are the *existing* contract — paginated lists return DRF's
paginated envelope, unpaginated lists return the `success_response` envelope,
and `update` is partial for every view that used these bodies.
"""
from apps.shared.addons.validations import success_response


class DashboardListMixin:
    """`list()` returning the paginated envelope, or `success_response`."""

    list_message = ""

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return success_response(data=serializer.data, message=self.list_message, code=200)


class DashboardStatsListMixin(DashboardListMixin):
    """`DashboardListMixin` plus a `stats` block on the paginated envelope.

    Stats are computed before pagination and describe the whole table, not the
    page — subclasses implement `get_list_stats`.
    """

    def get_list_stats(self, queryset):
        raise NotImplementedError

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        stats = self.get_list_stats(queryset)
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            response = self.get_paginated_response(serializer.data)
            response.data['stats'] = stats
            return response
        serializer = self.get_serializer(queryset, many=True)
        return success_response(data=serializer.data, message=self.list_message, code=200)


class DashboardCreateMixin:
    """`create()` answering 201 with the serialized object."""

    create_message = ""

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=serializer.data, message=self.create_message, code=201)


class DashboardRetrieveMixin:
    """`retrieve()` answering 200 with the serialized object."""

    retrieve_message = ""

    def retrieve(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_object())
        return success_response(data=serializer.data, message=self.retrieve_message, code=200)


class DashboardPartialUpdateMixin:
    """`update()` that is always partial, answering 200 with the new state."""

    update_message = ""

    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_object(), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=serializer.data, message=self.update_message, code=200)


class DashboardDestroyMixin:
    """`destroy()` answering 200 with a message and no body."""

    destroy_message = ""

    def destroy(self, request, *args, **kwargs):
        self.get_object().delete()
        return success_response(message=self.destroy_message, code=200)
