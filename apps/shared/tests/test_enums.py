import ast
import collections
import inspect

from django.test import SimpleTestCase

from apps.shared.addons import enums


class EnumModuleStructureTests(SimpleTestCase):
    def module_class_names(self):
        tree = ast.parse(inspect.getsource(enums))
        return [
            node.name
            for node in tree.body
            if isinstance(node, ast.ClassDef)
        ]

    def test_no_enum_is_declared_twice(self):
        names = self.module_class_names()
        duplicates = sorted(
            name for name, count in collections.Counter(names).items() if count > 1
        )

        self.assertEqual(
            duplicates, [],
            msg=(
                "These enums are declared more than once in "
                "shared/addons/enums.py; the later definition silently wins: "
                f"{duplicates}"
            ),
        )

    def test_every_enum_has_unique_values(self):
        offenders = {}
        for name in self.module_class_names():
            enum_class = getattr(enums, name, None)
            if enum_class is None or not hasattr(enum_class, "choices"):
                continue
            values = [member.value for member in enum_class]
            if len(values) != len(set(values)):
                offenders[name] = values

        self.assertEqual(offenders, {})


class LeadStatusesTests(SimpleTestCase):
    def test_values_are_the_ones_clients_expect(self):
        self.assertEqual(
            [member.value for member in enums.LeadStatuses],
            ["new", "engaged", "partial_info", "qualified", "rejected", "unreachable"],
        )

    def test_the_shadowed_values_are_gone(self):
        for dead in ("REGISTERED", "DELIVERED", "LOST"):
            self.assertFalse(
                hasattr(enums.LeadStatuses, dead),
                msg=f"LeadStatuses.{dead} is back — the duplicate class may have returned",
            )
