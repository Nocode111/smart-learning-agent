"""
本地文件修改服务（文档 Section 11）

职责：
1. 从用户消息中获取文件路径和修改要求
2. 调用安全网关校验
3. 读取原文件
4. 调用 LLM 生成修改后内容
5. 生成 diff
6. 保存 operation 记录
7. 保存 artifact 文件
8. 确认时备份并写入
9. 支持取消和恢复
"""

import difflib
import hashlib
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.models.agent_local_file import AgentLocalFileOperation
from app.services.agent_local_file_guard_service import agent_local_file_guard_service

logger = logging.getLogger(__name__)


class AgentLocalFileEditService:
    """本地文件修改服务"""

    # ── hash 工具 ───────────────────────────────────────────

    @staticmethod
    def sha256_text(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    # ── artifact 路径 ───────────────────────────────────────

    @staticmethod
    def _make_artifact_dir(operation_uuid: str) -> Path:
        """创建 operation 对应的 artifact 目录"""
        base = Path(settings.local_file_artifact_dir)
        if not base.is_absolute():
            base = Path.cwd() / base
        today = datetime.utcnow().strftime("%Y%m%d")
        artifact_dir = base / "backups" / today / operation_uuid
        artifact_dir.mkdir(parents=True, exist_ok=True)
        return artifact_dir

    # ── 写入审计事件（文档 Section 6.2） ──────────────────────

    @staticmethod
    def _record_event(db: Session, operation_id: int, event_type: str, message: str = None, metadata: dict = None):
        """写入审计事件到 agent_local_file_operation_events 表"""
        try:
            from sqlalchemy import text
            db.execute(
                text(
                    "INSERT INTO agent_local_file_operation_events "
                    "(operation_id, event_type, message, metadata_json, created_at) "
                    "VALUES (:op_id, :event_type, :message, :metadata_json, :created_at)"
                ),
                {
                    "op_id": operation_id,
                    "event_type": event_type,
                    "message": message,
                    "metadata_json": json.dumps(metadata, ensure_ascii=False) if metadata else None,
                    "created_at": datetime.utcnow(),
                },
            )
            db.commit()
        except Exception:
            # 审计表可能尚未创建，不阻塞主流程
            db.rollback()
            logger.debug("审计事件写入跳过（表可能未创建）: %s", event_type)

    # ── Diff 生成（文档 Section 11.4） ───────────────────────

    @staticmethod
    def build_unified_diff(file_name: str, original_text: str, modified_text: str) -> str:
        """使用 difflib 生成 unified diff"""
        original_lines = original_text.splitlines(keepends=True)
        modified_lines = modified_text.splitlines(keepends=True)
        return "".join(difflib.unified_diff(
            original_lines,
            modified_lines,
            fromfile=f"{file_name} (before)",
            tofile=f"{file_name} (after)",
            lineterm="",
        ))

    # ================================================================
    # 创建修改预览（文档 Section 11.1）
    # ================================================================

    def create_preview(
        self,
        db: Session,
        student_id: int,
        course_id: int | None,
        conversation_id: int | None,
        task_id: int | None,
        user_message_id: int | None,
        assistant_message_id: int | None,
        file_path: str,
        instruction: str,
    ) -> dict:
        """
        创建文件修改预览。

        流程:
        1. validate_path
        2. read_text_file
        3. sha256(original_text)
        4. call_llm_generate_modified_content
        5. 校验 modified_content
        6. sha256(modified_content)
        7. difflib.unified_diff
        8. 创建 operation_uuid
        9. 保存 artifact 文件
        10. 写入 agent_local_file_operations
        11. 返回前端展示数据
        """
        # 1. 校验路径
        validated = agent_local_file_guard_service.validate_path(file_path)
        path = validated["path"]
        root = validated["root"]

        # 2. 读取文件
        original_text, encoding, newline = agent_local_file_guard_service.read_text_file(path)

        # 3. 计算原始 hash
        original_sha256 = self.sha256_text(original_text)

        # 4. 调用 LLM 生成修改后内容
        from app.prompts.local_file_edit_prompt import build_local_file_edit_prompt
        from app.services.qwen_client import qwen_client

        messages = build_local_file_edit_prompt(
            file_name=path.name,
            instruction=instruction,
            original_text=original_text,
        )

        llm_output = qwen_client.chat(
            messages=messages,
            temperature=0.1,
        )

        # 5. 解析并校验 LLM 输出（文档 Section 11.3）
        modified_text, summary = self._parse_llm_output(llm_output, original_text, instruction)

        # 6. 计算修改后 hash
        proposed_sha256 = self.sha256_text(modified_text)

        # 7. 生成 diff
        diff_text = self.build_unified_diff(path.name, original_text, modified_text)

        # 8. 创建 operation_uuid
        operation_uuid = f"op_{uuid.uuid4().hex[:16]}"

        # 9. 保存 artifact 文件
        artifact_dir = self._make_artifact_dir(operation_uuid)

        original_snapshot_path = artifact_dir / "original_snapshot.txt"
        original_snapshot_path.write_text(original_text, encoding="utf-8")

        proposed_content_path = artifact_dir / "proposed_content.txt"
        proposed_content_path.write_text(modified_text, encoding="utf-8")

        diff_path = artifact_dir / "preview.diff"
        diff_path.write_text(diff_text, encoding="utf-8")

        # 10. 写入数据库
        operation = AgentLocalFileOperation(
            operation_uuid=operation_uuid,
            student_id=student_id,
            course_id=course_id,
            conversation_id=conversation_id,
            task_id=task_id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            status="preview_ready",
            original_path=str(path),
            resolved_path=str(path),
            workspace_root=str(root),
            file_name=path.name,
            file_ext=validated["file_ext"],
            file_size=validated["file_size"],
            encoding=encoding,
            newline=newline,
            instruction=instruction,
            summary=summary,
            original_sha256=original_sha256,
            proposed_sha256=proposed_sha256,
            artifact_dir=str(artifact_dir),
            original_snapshot_path=str(original_snapshot_path),
            proposed_content_path=str(proposed_content_path),
            diff_path=str(diff_path),
        )
        db.add(operation)
        db.flush()

        # 写入审计事件
        self._record_event(db, operation.id, "preview_created", "修改预览已生成")

        db.commit()

        # 11. 返回前端展示数据
        display_path = str(path)  # 本地开发环境可以展示完整路径

        return {
            "operation_uuid": operation_uuid,
            "status": "preview_ready",
            "file_name": path.name,
            "file_ext": validated["file_ext"],
            "display_path": display_path,
            "file_size": validated["file_size"],
            "instruction": instruction,
            "summary": summary,
            "original_sha256": original_sha256,
            "proposed_sha256": proposed_sha256,
            "diff_text": diff_text,
        }

    # ── LLM 输出解析与校验（文档 Section 11.3） ───────────────

    def _parse_llm_output(self, llm_output: str, original_text: str, instruction: str) -> tuple[str, str]:
        """
        解析并校验 LLM 输出的 JSON。

        返回: (modified_content, summary)
        """
        # 解析 JSON
        llm_output = (llm_output or "").strip()
        parsed = None
        try:
            parsed = json.loads(llm_output)
        except json.JSONDecodeError:
            # 尝试截取 { 到 }
            start = llm_output.find("{")
            end = llm_output.rfind("}")
            if start >= 0 and end > start:
                try:
                    parsed = json.loads(llm_output[start:end + 1])
                except json.JSONDecodeError:
                    pass

        if not parsed or not isinstance(parsed, dict):
            raise ValueError("我没有成功生成可靠的修改预览，请你把修改要求说得更具体一些。")

        modified_content = parsed.get("modified_content", "")
        summary = parsed.get("summary", "")

        if not isinstance(modified_content, str) or not modified_content.strip():
            raise ValueError("模型返回了空内容，已拒绝修改。请重新尝试。")

        # 长度校验
        max_len = max(len(original_text) * 3, len(original_text) + 20000)
        if len(modified_content) > max_len:
            raise ValueError("模型生成内容异常过长，已拒绝修改。请更明确地描述你想改什么。")

        # 大幅删减警告
        if len(modified_content) < len(original_text) * 0.3:
            delete_hints = ["删除", "去掉", "移除", "清空", "删掉", "不要了"]
            if not any(hint in instruction for hint in delete_hints):
                raise ValueError("模型生成内容异常过短，已拒绝修改。如果确实想大幅删减内容，请明确说明。")

        return modified_content, summary

    # ================================================================
    # 查询操作详情
    # ================================================================

    def get_operation(self, db: Session, operation_uuid: str, student_id: int) -> dict:
        """查询操作详情，带 owner 校验"""
        op = self._get_operation_for_user(db, operation_uuid, student_id)

        # 读取 diff 文件内容
        diff_text = None
        if op.diff_path:
            diff_file = Path(op.diff_path)
            if diff_file.exists():
                diff_text = diff_file.read_text(encoding="utf-8")

        return {
            "operation_uuid": op.operation_uuid,
            "status": op.status,
            "file_name": op.file_name,
            "file_ext": op.file_ext,
            "display_path": op.original_path,  # 本地开发环境
            "file_size": op.file_size,
            "instruction": op.instruction,
            "summary": op.summary,
            "original_sha256": op.original_sha256,
            "proposed_sha256": op.proposed_sha256,
            "diff_text": diff_text,
            "error_message": op.error_message,
        }

    @staticmethod
    def _get_operation_for_user(db: Session, operation_uuid: str, student_id: int) -> AgentLocalFileOperation:
        """查询 operation 并校验 owner"""
        op = db.query(AgentLocalFileOperation).filter(
            AgentLocalFileOperation.operation_uuid == operation_uuid
        ).first()
        if not op:
            raise ValueError("修改操作不存在")
        if op.student_id != student_id:
            raise ValueError("无权查看该修改操作")
        return op

    # ================================================================
    # 确认写入（文档 Section 11.5）
    # ================================================================

    def confirm_operation(
        self,
        db: Session,
        operation_uuid: str,
        student_id: int,
        expected_original_sha256: str,
    ) -> dict:
        """
        确认修改并写入文件。

        流程:
        1. 查询 operation
        2. 校验 owner
        3. 校验 status == preview_ready
        4. 校验 expected_original_sha256
        5. 重新读取当前原文件并计算 hash
        6. 比对 hash 防覆盖
        7. 创建备份
        8. 写临时文件 + os.replace 原子替换
        9. 更新 operation 状态
        10. 写入审计事件
        """
        op = self._get_operation_for_user(db, operation_uuid, student_id)

        if op.status != "preview_ready":
            raise ValueError("当前修改任务不能确认（状态不是 preview_ready）")

        if expected_original_sha256 != op.original_sha256:
            raise ValueError("确认信息已过期，请重新生成预览")

        # 重新读取当前文件
        if not Path(op.resolved_path).exists():
            op.status = "failed"
            op.error_message = "原文件已不存在"
            db.commit()
            raise ValueError("原文件已不存在，无法写入")

        current_text, current_encoding, current_newline = agent_local_file_guard_service.read_text_file(
            Path(op.resolved_path)
        )
        current_sha = self.sha256_text(current_text)

        if current_sha != op.original_sha256:
            raise ValueError("文件在预览后被其他程序修改过。为了避免覆盖新内容，请重新发起修改。")

        # 创建备份
        backup_path = self._create_backup(op, current_text)

        # 读取候选内容
        proposed_text = Path(op.proposed_content_path).read_text(encoding="utf-8")

        # 原子写入：先写临时文件，再 os.replace
        target = Path(op.resolved_path)
        tmp_path = target.with_suffix(target.suffix + ".agent_tmp")

        try:
            # 写临时文件
            encoding = op.encoding or "utf-8"
            newline = op.newline or "\n"
            tmp_path.write_text(proposed_text, encoding=encoding, newline="")

            # 原子替换
            os.replace(tmp_path, target)
        except OSError as exc:
            # 清理临时文件
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
            op.status = "failed"
            op.error_message = f"写入失败：{exc}。原文件没有被覆盖。"
            db.commit()
            self._record_event(db, op.id, "operation_failed", f"写入失败: {exc}")
            raise ValueError("写入文件失败，可能是文件正在被其他程序占用。原文件没有被覆盖。")

        # 更新 operation 状态
        applied_sha256 = self.sha256_text(proposed_text)
        op.status = "applied"
        op.backup_path = str(backup_path)
        op.applied_sha256 = applied_sha256
        op.applied_at = datetime.utcnow()
        op.confirmed_at = datetime.utcnow()
        db.commit()

        # 审计事件
        self._record_event(db, op.id, "backup_created", "备份已创建")
        self._record_event(db, op.id, "file_written", "文件已写入")

        return {
            "operation_uuid": op.operation_uuid,
            "status": "applied",
            "message": "文件已修改并完成备份",
            "applied_sha256": applied_sha256,
            "backup_created": True,
        }

    # ── 创建备份 ──────────────────────────────────────────────

    def _create_backup(self, op: AgentLocalFileOperation, current_text: str) -> Path:
        """备份原文件到 artifact 目录"""
        backup_dir = Path(op.artifact_dir) / "backup"
        backup_dir.mkdir(parents=True, exist_ok=True)

        backup_file = backup_dir / f"{op.file_name}.bak"
        backup_file.write_text(current_text, encoding="utf-8")

        # 写入 metadata
        metadata = {
            "operation_uuid": op.operation_uuid,
            "original_path": op.resolved_path,
            "original_sha256": op.original_sha256,
            "backup_sha256": self.sha256_text(current_text),
            "created_at": datetime.utcnow().isoformat(),
        }
        meta_file = backup_dir / "metadata.json"
        meta_file.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

        return backup_file

    # ================================================================
    # 取消修改（文档 Section 11.6）
    # ================================================================

    def cancel_operation(
        self,
        db: Session,
        operation_uuid: str,
        student_id: int,
        reason: str = "user_cancel",
    ) -> dict:
        """取消修改预览，不动文件"""
        op = self._get_operation_for_user(db, operation_uuid, student_id)

        if op.status not in ("preview_ready",):
            raise ValueError("当前修改任务不能取消（状态不是 preview_ready）")

        op.status = "canceled"
        op.canceled_reason = reason
        op.canceled_at = datetime.utcnow()
        db.commit()

        self._record_event(db, op.id, "operation_canceled", f"用户取消: {reason}")

        return {
            "operation_uuid": op.operation_uuid,
            "status": "canceled",
            "message": "已取消，本地文件没有被修改",
        }

    # ================================================================
    # 恢复备份（文档 Section 11.7）
    # ================================================================

    def restore_operation(
        self,
        db: Session,
        operation_uuid: str,
        student_id: int,
        expected_current_sha256: str | None = None,
    ) -> dict:
        """从备份恢复文件"""
        op = self._get_operation_for_user(db, operation_uuid, student_id)

        if op.status not in ("applied", "failed"):
            raise ValueError("当前修改任务不能恢复（状态不是 applied 或 failed）")

        if not op.backup_path or not Path(op.backup_path).exists():
            raise ValueError("备份文件不存在，无法恢复")

        # 校验当前文件 hash（如果前端传了预期值）
        if op.resolved_path and Path(op.resolved_path).exists():
            current_text, _, _ = agent_local_file_guard_service.read_text_file(Path(op.resolved_path))
            current_sha = self.sha256_text(current_text)

            if expected_current_sha256 and expected_current_sha256 != current_sha:
                raise ValueError("文件在确认后被其他程序修改过，恢复可能覆盖新内容。如需强制恢复，请重新操作。")

        # 读取备份
        backup_text = Path(op.backup_path).read_text(encoding="utf-8")

        # 写入目标文件
        target = Path(op.resolved_path)
        tmp_path = target.with_suffix(target.suffix + ".agent_tmp")

        try:
            encoding = op.encoding or "utf-8"
            newline = op.newline or "\n"
            tmp_path.write_text(backup_text, encoding=encoding, newline="")

            os.replace(tmp_path, target)
        except OSError as exc:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
            raise ValueError(f"恢复备份失败：{exc}。原文件未被修改。")

        op.status = "restored"
        op.restored_at = datetime.utcnow()
        db.commit()

        self._record_event(db, op.id, "restore_applied", "已从备份恢复")

        return {
            "operation_uuid": op.operation_uuid,
            "status": "restored",
            "message": "已从备份恢复",
        }

    # ================================================================
    # 功能配置（文档 Section 12.5）
    # ================================================================

    @staticmethod
    def get_config() -> dict:
        """返回当前功能配置"""
        enabled = settings.enable_local_file_agent
        roots = []
        if enabled:
            try:
                roots = [str(r) for r in agent_local_file_guard_service.allowed_roots()]
            except ValueError:
                roots = []
        extensions = [
            item.strip()
            for item in settings.local_file_allowed_extensions.split(",")
            if item.strip()
        ]
        return {
            "enabled": enabled,
            "allowed_roots": roots,
            "allowed_extensions": extensions,
            "max_size_bytes": settings.local_file_max_size_bytes,
        }


agent_local_file_edit_service = AgentLocalFileEditService()
