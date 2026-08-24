"""Slash-aware repository path matching with recursive ``**`` support."""

from fnmatch import fnmatchcase
from functools import cache


def _parts(value: str) -> tuple[str, ...]:
    normalized = value.replace("\\", "/").strip("/")
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    return tuple(part for part in normalized.split("/") if part and part != ".")


def path_matches(path: str, pattern: str) -> bool:
    """Match one repository-relative path without letting ``*`` cross directories."""

    path_parts = _parts(path)
    pattern_parts = _parts(pattern)
    if not path_parts or not pattern_parts:
        return False
    if len(pattern_parts) == 1 and pattern_parts[0] != "**":
        return fnmatchcase(path_parts[-1], pattern_parts[0])

    @cache
    def match(path_index: int, pattern_index: int) -> bool:
        if pattern_index == len(pattern_parts):
            return path_index == len(path_parts)
        current = pattern_parts[pattern_index]
        if current == "**":
            return match(path_index, pattern_index + 1) or (
                path_index < len(path_parts) and match(path_index + 1, pattern_index)
            )
        return (
            path_index < len(path_parts)
            and fnmatchcase(path_parts[path_index], current)
            and match(path_index + 1, pattern_index + 1)
        )

    return match(0, 0)
