"""Every internal module must have exactly one importable path.

`apps/` used to be appended to `sys.path`, so `shared.addons.redis` and
`apps.shared.addons.redis` were two distinct module objects — each with its own
`redis_client`, `conversation_service`, `instagram_service` and `agent`. Patching
one left the other live, and at runtime two halves of the codebase could hold
different instances of what is meant to be a singleton.
"""
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
        """A duplicate would show up in sys.modules under the bare name."""
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

        # Re-importing through the same (only) path must yield the same object.
        from apps.shared.addons.redis import redis_client as redis_again
        from apps.shared.ai_service.agent import agent
        from apps.shared.ai_service.agent import agent as agent_again

        self.assertIs(redis_client, redis_again)
        self.assertIs(agent, agent_again)
        self.assertIs(conversation_service, service_again)
