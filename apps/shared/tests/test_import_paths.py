import sys

from django.test import SimpleTestCase

INTERNAL = (
    "shared", "assistant", "user", "integration",
    "payment", "dashboard", "blog", "landing",
)


class SingleImportPathTests(SimpleTestCase):
    def test_internal_apps_are_not_importable_without_the_apps_prefix(self):
        for name in INTERNAL:
            with self.subTest(module=name):
                with self.assertRaises(ModuleNotFoundError):
                    __import__(name)

    def test_no_app_module_is_loaded_under_a_bare_top_level_name(self):
        loaded = sorted(
            m for m in sys.modules
            if m.split(".")[0] in INTERNAL
        )
        self.assertEqual(loaded, [], f"duplicate module objects loaded: {loaded}")

    def test_singletons_have_one_identity(self):
        from apps.assistant.services.conversation import conversation_service
        from apps.assistant.services.conversation import (
            conversation_service as service_again,
        )
        from apps.shared.addons.redis import redis_client

        from apps.shared.addons.redis import redis_client as redis_again
        from apps.shared.ai_service.agent import agent
        from apps.shared.ai_service.agent import agent as agent_again

        self.assertIs(redis_client, redis_again)
        self.assertIs(agent, agent_again)
        self.assertIs(conversation_service, service_again)
