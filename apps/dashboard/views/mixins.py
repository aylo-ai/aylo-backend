from apps.shared.addons.validations import success_response


class DashboardListMixin:
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
    create_message = ""

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=serializer.data, message=self.create_message, code=201)


class DashboardRetrieveMixin:
    retrieve_message = ""

    def retrieve(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_object())
        return success_response(data=serializer.data, message=self.retrieve_message, code=200)


class DashboardPartialUpdateMixin:
    update_message = ""

    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_object(), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=serializer.data, message=self.update_message, code=200)


class DashboardDestroyMixin:
    destroy_message = ""

    def destroy(self, request, *args, **kwargs):
        self.get_object().delete()
        return success_response(message=self.destroy_message, code=200)
