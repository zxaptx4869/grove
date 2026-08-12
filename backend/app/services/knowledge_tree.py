"""装修知识目录模板：Markdown 解析与树种子构建。"""

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Node

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
DECORATION_TEMPLATE_FILE = TEMPLATES_DIR / "decoration_knowledge_tree.md"


@dataclass
class TreeNodeSeed:
    """解析出的树节点种子（尚未落库）。"""

    name: str
    description: str | None = None
    children: list["TreeNodeSeed"] = field(default_factory=list)


def parse_knowledge_tree(text: str) -> list[TreeNodeSeed]:
    """解析模板 Markdown 为树。

    格式约定（与模板文件头部一致）：
    - 从 `## 知识目录` 标题行之后开始解析；
    - 每个节点一行：`- 名称 — 描述`，缩进两个空格为一级；
    - 无「 — 」时描述为空。
    """
    lines = text.splitlines()
    in_tree = False
    roots: list[TreeNodeSeed] = []
    stack: list[tuple[int, TreeNodeSeed]] = []
    root_level: int | None = None

    for raw in lines:
        if not in_tree:
            if raw.strip().startswith("## 知识目录"):
                in_tree = True
            continue

        stripped = raw.rstrip()
        if not stripped.strip() or not stripped.lstrip().startswith("- "):
            continue

        indent = len(stripped) - len(stripped.lstrip(" "))
        content = stripped.lstrip()[2:].strip()
        name, _, description = content.partition(" — ")
        if not name:
            continue

        if root_level is None:
            root_level = indent
        depth = (indent - root_level) // 2

        while stack and stack[-1][0] >= depth:
            stack.pop()

        node = TreeNodeSeed(name=name, description=description or None)
        if stack:
            stack[-1][1].children.append(node)
        else:
            roots.append(node)
        stack.append((depth, node))

    return roots


def load_decoration_template() -> list[TreeNodeSeed]:
    """读取并解析装修模板文件。"""
    return parse_knowledge_tree(DECORATION_TEMPLATE_FILE.read_text(encoding="utf-8"))


async def seed_project_nodes(
    db: AsyncSession, project_id: int, roots: list[TreeNodeSeed]
) -> int:
    """将树种子逐层落库（flush 获取父节点 id），返回创建的节点数。"""
    count = 0

    async def _create(parent_id: int | None, children: list[TreeNodeSeed]) -> None:
        nonlocal count
        for position, child in enumerate(children):
            node = Node(
                project_id=project_id,
                parent_id=parent_id,
                name=child.name,
                description=child.description,
                position=position,
            )
            db.add(node)
            await db.flush()
            count += 1
            await _create(node.id, child.children)

    await _create(None, roots)
    return count
