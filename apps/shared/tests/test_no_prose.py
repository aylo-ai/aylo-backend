import io
import pathlib
import re
import tokenize

from django.test import SimpleTestCase

ROOT = pathlib.Path(__file__).resolve().parents[3]

ROOTS = ("apps", "config")

SKIP_DIRS = {"migrations", "__pycache__", ".venv", "node_modules"}

ALLOWED_DIRECTIVE = re.compile(
    r"^#\s*(noqa|type:|pragma|fmt:\s*(on|off)|nosec|pylint|flake8|isort|mypy|"
    r"coding[:=]|!)",
)

MAX_COMMENTS = 38

MAX_DOCSTRING_LINES = 0


def _sources():
    for name in ROOTS:
        for path in sorted((ROOT / name).rglob("*.py")):
            if SKIP_DIRS & set(path.parts):
                continue
            yield path


def _prose(path):
    src = path.read_text(encoding="utf-8")
    comments = []
    docstrings = []
    previous = tokenize.INDENT
    for token in tokenize.generate_tokens(io.StringIO(src).readline):
        if token.type == tokenize.COMMENT:
            if not ALLOWED_DIRECTIVE.match(token.string.strip()):
                comments.append((token.start[0], token.string.strip()))
        elif token.type == tokenize.STRING and previous in (
            tokenize.INDENT,
            tokenize.NEWLINE,
            tokenize.NL,
            tokenize.DEDENT,
            tokenize.ENCODING,
        ):
            docstrings.append((token.start[0], token.string.count("\n") + 1))
        if token.type not in (tokenize.NL, tokenize.COMMENT):
            previous = token.type
    return comments, docstrings


class NoProseTests(SimpleTestCase):
    def test_no_source_file_carries_a_comment(self):
        offenders = []
        for path in _sources():
            comments, _ = _prose(path)
            for line, text in comments:
                offenders.append(
                    f"{path.relative_to(ROOT)}:{line}: {text[:70]}"
                )

        self.assertEqual(
            offenders,
            [],
            "CLAUDE.md §4: no comments. Delete these, or put the reasoning in "
            "the commit message or docs/reports/. Only machine-read directives "
            "(noqa, type:, pragma, fmt:) are allowed.\n" + "\n".join(offenders[:40]),
        )

    def test_no_source_file_carries_a_docstring(self):
        offenders = []
        total = 0
        for path in _sources():
            _, docstrings = _prose(path)
            for line, length in docstrings:
                total += length
                offenders.append(f"{path.relative_to(ROOT)}:{line} ({length} lines)")

        self.assertEqual(
            total,
            MAX_DOCSTRING_LINES,
            "CLAUDE.md §4: no docstrings. Name things so they do not need one.\n"
            + "\n".join(offenders[:40]),
        )

    def test_the_allowed_directives_are_still_the_only_exemption(self):
        kept = 0
        for path in _sources():
            src = path.read_text(encoding="utf-8")
            for token in tokenize.generate_tokens(io.StringIO(src).readline):
                if token.type == tokenize.COMMENT and ALLOWED_DIRECTIVE.match(
                    token.string.strip()
                ):
                    kept += 1

        self.assertLessEqual(
            kept,
            MAX_COMMENTS,
            f"{kept} tool directives found, expected at most {MAX_COMMENTS}. "
            "If a real directive was added, raise MAX_COMMENTS. If prose was "
            "disguised as a directive to dodge the other two tests, delete it.",
        )
