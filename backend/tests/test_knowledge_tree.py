"""装修模板解析器测试。"""

from app.services.knowledge_tree import (
    DECORATION_TEMPLATE_FILE,
    TreeNodeSeed,
    parse_knowledge_tree,
)


def count_nodes(roots: list[TreeNodeSeed]) -> int:
    """统计树种子节点总数。"""
    return sum(1 + count_nodes(root.children) for root in roots)


def find_node(roots: list[TreeNodeSeed], name: str) -> TreeNodeSeed | None:
    """按名称查找节点（含递归）。"""
    for root in roots:
        if root.name == name:
            return root
        found = find_node(root.children, name)
        if found is not None:
            return found
    return None


def test_parse_decoration_template_counts() -> None:
    """模板解析应得到 149 个节点、7 个根节点。"""
    text = DECORATION_TEMPLATE_FILE.read_text(encoding="utf-8")

    roots = parse_knowledge_tree(text)

    assert count_nodes(roots) == 149
    assert len(roots) == 7


def test_parse_hierarchy_and_description() -> None:
    """层级与「名称 — 描述」应正确解析。"""
    text = DECORATION_TEMPLATE_FILE.read_text(encoding="utf-8")

    roots = parse_knowledge_tree(text)

    assert roots[0].name == "装修准备"
    assert roots[0].children[0].name == "需求确认"
    sofa = find_node(roots, "沙发")
    assert sofa is not None
    assert sofa.description is not None
    assert "单人沙发" in sofa.description


def test_parse_skips_metadata_header() -> None:
    """「## 知识目录」之前的元数据行不应成为节点。"""
    text = "\n".join(
        [
            "# 房子装修",
            "- 状态：规划中",
            "- 目录节点：149 个",
            "## 知识目录",
            "- 装修准备 — 描述",
        ]
    )

    roots = parse_knowledge_tree(text)

    assert len(roots) == 1
    assert roots[0].name == "装修准备"
