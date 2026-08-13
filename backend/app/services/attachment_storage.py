"""本地附件存储服务：保存、删除与路径解析。"""

from pathlib import Path
from uuid import uuid4

from app.core.config import get_settings

# backend/app/services/attachment_storage.py -> 向上两级得到 backend 根目录
BACKEND_DIR = Path(__file__).resolve().parents[2]


class AttachmentStorage:
    """本地文件系统附件存储，接口保持可替换。"""

    def __init__(self, root: Path) -> None:
        self.root = root

    @classmethod
    def from_settings(cls) -> "AttachmentStorage":
        """按配置构造，相对路径基于 backend 目录解析。"""
        configured = Path(get_settings().attachment_dir)
        root = configured if configured.is_absolute() else BACKEND_DIR / configured
        return cls(root)

    def save(self, data: bytes, extension: str) -> str:
        """保存图片字节并返回相对文件名。"""
        self.root.mkdir(parents=True, exist_ok=True)
        file_name = f"{uuid4().hex}{extension}"
        (self.root / file_name).write_bytes(data)
        return file_name

    def resolve(self, relative_path: str) -> Path:
        """把相对文件名解析为绝对路径，并拒绝越界访问。"""
        target = (self.root / relative_path).resolve()
        if not target.is_relative_to(self.root.resolve()):
            raise ValueError("非法附件路径")
        return target

    def delete(self, relative_path: str) -> None:
        """删除附件文件（不存在则忽略）。"""
        self.resolve(relative_path).unlink(missing_ok=True)
