# Project working agreements

Standing instructions for this repo. Follow these on every task.

## Always: report changes when a task is done
After completing any task, write a dated change report to
`docs/reports/YYYY-MM-DD-<topic>.md`. Cover: the issues found, the fix per issue,
files changed, new tests, and any open items needing a decision. Group by severity
for security work, and keep it scannable (tables). This is part of "done", not an
extra step to be asked for.

## Always: remove dead and unused code
Do not leave dead code behind. As part of every change:
- Delete functions, classes, methods, and branches that have no callers.
- Remove unused imports, variables, parameters, and settings.
- Remove commented-out code and leftover debug `print()` statements.
- Verify "unused" with a search (e.g. `grep -rn <name> apps/`) before deleting, so
  a dynamic or string-based caller isn't missed.
- Prefer deleting over commenting out. Git history is the archive.

## Useful facts
- **Run tests** with the venv and `--keepdb` (avoids the destroy-test-DB prompt):
  `.venv/bin/python manage.py test <app.path> --keepdb`
- **Dual import paths**: modules can be imported as both `shared.x` and
  `apps.shared.x` (and `user.views` vs `apps.user.views`), producing two distinct
  module objects. When patching in tests, patch the path the running code actually
  uses (e.g. `user.views.foo`, since urls do `import user.views`).
- Commit only when asked; if on `main`, branch first.
