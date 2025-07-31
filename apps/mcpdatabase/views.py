from rest_framework import views, generics, permissions

from shared.addons.validations import success_response, error_response
from apps.mcpdatabase.models import DatabaseConnection
from apps.mcpdatabase.serializers import MCPDatabaseSerializer, MCPDatabaseConnectionSerializer

class MCPDatabaseView(generics.ListCreateAPIView):
    serializer_class = MCPDatabaseSerializer
    queryset = DatabaseConnection.objects.all()
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        assistant_id = self.kwargs.get("pk")
        return self.queryset.filter(assistant_id=assistant_id)
    
    def list(self, request, *args, **kwargs):
        serializer = self.serializer_class(self.get_queryset(), many=True)
        serializer_data = serializer.data
        return success_response(data=serializer_data, message="MCP Database list", code=200)
    
    def create(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=serializer.data, message="MCP Database created", code=201)


class MCPDatabaseConnectionView(views.APIView):
    serializer_class = MCPDatabaseConnectionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        mcp_database_id = self.kwargs.get("pk")
        context_data = {
            "mcp_database_id": mcp_database_id,
            "request": request
        }
        serializer = self.serializer_class(data=request.data, context=context_data)
        serializer.is_valid(raise_exception=True)
        return success_response(data=serializer.data, message="MCP Database connection", code=200)
    
    