from rest_framework import serializers, status
from asgiref.sync import async_to_sync

from apps.mcpdatabase.models import DatabaseConnection
from apps.shared.mcp_tools.sql_server import DbConnectionPool
from apps.shared.addons.validations import raise_validation_error


class MCPDatabaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = DatabaseConnection
        fields = (
            "id", 
            "database_type",
            "database_username",
            "host",
            "port",
            "database_name",
            "assistant",
            "is_active",
            "password_encrypted",
            "created_time",
            "updated_time",
        )

        read_only_fields = ("created_time", "updated_time")


class MCPDatabaseConnectionSerializer(serializers.Serializer):
    def validate(self, attrs):
        mcp_database_id = self.context.get("mcp_database_id")
        if not mcp_database_id:
            raise serializers.ValidationError("MCP Database ID is required")
        try:
            mcp_database = DatabaseConnection.objects.get(id=mcp_database_id)
        except DatabaseConnection.DoesNotExist:
            raise serializers.ValidationError("MCP Database not found")
    
        if mcp_database.database_type == "postgresql":
            database_url = f"postgresql://{mcp_database.database_username}:{mcp_database.password_encrypted}@{mcp_database.host}:{mcp_database.port}/{mcp_database.database_name}"
            db_connection_pool = DbConnectionPool()
            print(database_url)
            async_to_sync(db_connection_pool.pool_connect)(database_url)
            if db_connection_pool.last_error:
                raise_validation_error(message=db_connection_pool.last_error,code=status.HTTP_400_BAD_REQUEST)
        return attrs