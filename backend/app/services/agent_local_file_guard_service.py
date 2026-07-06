"""
本地文件安全网关（文档 Section 10）

职责：
1. 判断功能是否开启
2. 解析白名单目录
3. 校验用户路径
4. 校验扩展名
5. 校验文件大小
6. 判断是否文本文件
7. 读取文本并识别编码
"""

import logging
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

# 危险扩展名黑名单（文档 Section 5.3）
DANGEROUS_EXTENSIONS = {
    ".exe", ".dll", ".bat", ".cmd", ".ps1", ".vbs", ".msi", ".reg",
    ".lnk", ".sys", ".zip", ".rar", ".7z",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp",
    ".pdf", ".docx", ".pptx", ".xlsx",
    ".env", ".pem", ".key", ".crt",
}


class AgentLocalFileGuardService:
    """本地文件安全网关"""

    def ensure_enabled(self):
        """确保功能已开启（文档 Section 10.1）"""
        if not settings.enable_local_file_agent:
            raise ValueError("本地文件修改功能未开启。请在后端配置 ENABLE_LOCAL_FILE_AGENT=true，并配置允许访问的目录。")

    def allowed_roots(self) -> list[Path]:
        """解析白名单目录列表（文档 Section 10.1）"""
        raw = settings.local_file_allowed_roots or ""
        roots = []
        for item in raw.split(";"):
            item = item.strip()
            if not item:
                continue
            resolved = Path(item).expanduser().resolve()
            if not resolved.exists():
                logger.warning("白名单目录不存在: %s", resolved)
                continue
            roots.append(resolved)
        if not roots:
            raise ValueError("未配置允许访问的本地目录（LOCAL_FILE_ALLOWED_ROOTS 为空或所有目录都不存在）")
        return roots

    def validate_path(self, user_path: str) -> dict:
        """
        校验用户提供的文件路径（文档 Section 10.1）

        返回:
        {
            "path": Path,
            "root": Path,
            "file_name": str,
            "file_ext": str,
            "file_size": int,
        }
        """
        self.ensure_enabled()

        if not user_path or len(user_path) > 500:
            raise ValueError("文件路径不合法")

        try:
            path = Path(user_path).expanduser().resolve(strict=True)
        except (OSError, FileNotFoundError):
            raise ValueError("没有找到这个文件，请检查路径是否正确。")

        if not path.is_file():
            raise ValueError("目标不是可修改的文件")

        # 白名单目录校验
        matched_root = None
        for root in self.allowed_roots():
            try:
                if path.is_relative_to(root):
                    matched_root = root
                    break
            except Exception:
                # is_relative_to 在某些 Python 版本可能抛异常
                try:
                    path.relative_to(root)
                    matched_root = root
                    break
                except ValueError:
                    continue

        if matched_root is None:
            raise ValueError("为了安全，我只能修改已配置允许目录内的文件。请把文件放到允许目录后再试。")

        # 扩展名校验
        ext = path.suffix.lower()
        if ext in DANGEROUS_EXTENSIONS:
            raise ValueError(f"不支持修改 {ext} 类型的文件。当前只支持文本类文件。")

        allowed_exts = {
            item.strip().lower()
            for item in settings.local_file_allowed_extensions.split(",")
            if item.strip()
        }
        if ext not in allowed_exts:
            raise ValueError(f"不支持修改 {ext} 类型文件。允许的类型：{', '.join(sorted(allowed_exts))}")

        # 文件大小校验
        size = path.stat().st_size
        if size > settings.local_file_max_size_bytes:
            max_kb = settings.local_file_max_size_bytes // 1024
            raise ValueError(f"这个文件超过当前支持大小（{max_kb}KB），建议你只提供需要修改的片段，或拆成小文件。")

        return {
            "path": path,
            "root": matched_root,
            "file_name": path.name,
            "file_ext": ext,
            "file_size": size,
        }

    @staticmethod
    def read_text_file(path: Path) -> tuple[str, str, str]:
        """
        读取文本文件并识别编码和换行符（文档 Section 10.2）

        返回: (text, encoding, newline)
        """
        raw = path.read_bytes()

        # 检查是否二进制文件
        null_count = raw[:4096].count(b"\x00")
        if null_count > 0:
            raise ValueError("疑似二进制文件，暂不支持修改。当前只支持纯文本文件。")

        for encoding in ("utf-8-sig", "utf-8", "gbk"):
            try:
                text = raw.decode(encoding)
                newline = "\r\n" if "\r\n" in text else "\n"
                return text, encoding, newline
            except UnicodeDecodeError:
                continue

        raise ValueError("当前文件编码无法识别，暂不支持修改。支持的编码：UTF-8（含 BOM）、GBK。")


agent_local_file_guard_service = AgentLocalFileGuardService()
