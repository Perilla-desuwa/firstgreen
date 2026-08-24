"""Cheap deterministic decomposition decision that runs before any planner call."""

import re

from firstgreen.planning.models import DecompositionDecision, RepositoryMap

DECOMPOSABLE_CONCEPTS = {
    "schema": {
        "schema",
        "model",
        "migration",
        "database",
        "table",
        "数据库",
        "数据表",
        "模型",
        "迁移",
        "字段",
    },
    "service": {
        "service",
        "logic",
        "behavior",
        "expiry",
        "expiration",
        "服务",
        "逻辑",
        "行为",
        "过期",
        "业务层",
    },
    "api": {
        "api",
        "endpoint",
        "route",
        "controller",
        "接口",
        "端点",
        "路由",
        "控制器",
    },
    "email": {
        "email",
        "mail",
        "template",
        "notification",
        "邮件",
        "模板",
        "通知",
        "消息",
    },
    "tests": {
        "test",
        "tests",
        "integration",
        "regression",
        "测试",
        "集成测试",
        "回归测试",
        "单元测试",
    },
    "docs": {"docs", "documentation", "readme", "文档", "说明", "使用指南"},
}
LOCAL_MARKERS = {
    "one file",
    "single function",
    "typo",
    "rename",
    "race condition",
    "单个文件",
    "一个文件",
    "单个函数",
    "错别字",
    "重命名",
}


def _tokens(issue: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z][a-zA-Z0-9_-]*", issue.lower()))


def relevant_paths(issue: str, repo_map: RepositoryMap, limit: int = 20) -> list[str]:
    tokens = _tokens(issue)
    scored: list[tuple[int, str]] = []
    for file in repo_map.files:
        pieces = set(re.split(r"[/_.-]", file.path.lower()))
        score = len(tokens & pieces)
        if score:
            scored.append((score, file.path))
    return [path for _, path in sorted(scored, key=lambda item: (-item[0], item[1]))[:limit]]


def decide_decomposition(issue: str, repo_map: RepositoryMap) -> DecompositionDecision:
    lowered = issue.lower()
    paths = relevant_paths(issue, repo_map)
    concepts = [
        name
        for name, markers in DECOMPOSABLE_CONCEPTS.items()
        if any(word in lowered for word in markers)
    ]
    matched_modules = {
        module.name
        for module in repo_map.modules
        if module.name.lower() in lowered
        or any(path.startswith(tuple(module.paths)) for path in paths)
    }
    local = any(marker in lowered for marker in LOCAL_MARKERS)
    if local or (len(concepts) <= 1 and len(matched_modules) <= 1):
        return DecompositionDecision(
            recommended_parallelism=1,
            decision="single_task",
            reason=(
                "Likely changes are concentrated in one module and do not expose an "
                "independently verifiable intermediate artifact."
            ),
            relevant_paths=paths,
        )
    parallelism = min(3, max(2, len(concepts) - 1), 5)
    return DecompositionDecision(
        recommended_parallelism=parallelism,
        decision="decompose",
        reason=(
            "The issue names separable implementation or verification artifacts across "
            f"{', '.join(concepts[:4])}."
        ),
        relevant_paths=paths,
    )
