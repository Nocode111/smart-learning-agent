from datetime import datetime

from sqlalchemy.orm import Session

from app.models.knowledge_point import KnowledgePoint
from app.models.qa_record import QARecord
from app.prompts.qa_prompt import build_qa_prompt
from app.services.qwen_client import qwen_client
from app.services.rag_service import rag_service


class QaAgentService:
    def __init__(self, profile_service, behavior_service, recommendation_service):
        self.profile_service = profile_service
        self.behavior_service = behavior_service
        self.recommendation_service = recommendation_service

    def load_course_points(self, db: Session, course_id: int) -> list[KnowledgePoint]:
        return db.query(KnowledgePoint).filter(KnowledgePoint.course_id == course_id).all()

    def match_knowledge_points(self, db: Session, course_id: int, question: str) -> list[int]:
        points = self.load_course_points(db, course_id)
        matched = []
        for point in points:
            if point.name in question:
                matched.append(point.id)
        return matched

    def get_knowledge_point_names(self, db: Session, knowledge_point_ids: list[int]) -> list[str]:
        if not knowledge_point_ids:
            return []
        points = db.query(KnowledgePoint).filter(KnowledgePoint.id.in_(knowledge_point_ids)).all()
        return [point.name for point in points]

    # ── 生成前准备（文档 Section 9.1） ──────────────────────

    def prepare_qa_generation(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        question: str,
        conversation_context: list[dict] | None = None,
        attachment_chunks: list[dict] | None = None,
        retrieval_scope: str = "hybrid",
    ) -> dict:
        """
        只做生成前准备，不调用 LLM。

        返回：
        {
            "messages": messages,
            "knowledge_point_ids": knowledge_point_ids,
            "main_point_id": main_point_id,
            "point_names": point_names,
            "chunks": chunks,
            "profile": profile,
            "agent_steps": agent_steps,
        }
        """
        knowledge_point_ids = self.match_knowledge_points(db, course_id, question)
        main_point_id = knowledge_point_ids[0] if knowledge_point_ids else None
        point_names = self.get_knowledge_point_names(db, knowledge_point_ids)

        agent_steps = [
            {
                "title": "理解问题",
                "detail": f"识别到相关知识点：{', '.join(point_names) if point_names else '暂未匹配到明确知识点'}",
                "status": "done",
            }
        ]

        self.behavior_service.record(
            db=db,
            student_id=student_id,
            course_id=course_id,
            knowledge_point_id=main_point_id,
            behavior_type="ask_question",
            content=question,
            result="submitted",
            source="qa_page",
        )
        agent_steps.append(
            {
                "title": "记录学习行为",
                "detail": "已将本次提问写入学习行为数据，用于后续画像更新。",
                "status": "done",
            }
        )

        profile = self.profile_service.get_profile_for_agent(db, student_id, course_id)
        profile_for_prompt = self._merge_profile_with_context_memory(profile, conversation_context)
        agent_steps.append(
            {
                "title": "读取学习画像",
                "detail": f"当前画像水平：{profile_for_prompt.get('overall_level', '未知')}；薄弱点数量：{len(profile_for_prompt.get('weak_points', []))}",
                "status": "done",
            }
        )

        # 根据 retrieval_scope 进行检索
        attachment_chunks = attachment_chunks or []
        course_chunks = []

        if retrieval_scope in ("attachments_only", "attachments_first", "hybrid") and attachment_chunks:
            agent_steps.append(
                {
                    "title": "检索当前对话附件",
                    "detail": f"从当前会话附件中检索到 {len(attachment_chunks)} 条相关片段。",
                    "status": "done",
                }
            )
        elif retrieval_scope in ("attachments_only", "attachments_first", "hybrid"):
            agent_steps.append(
                {
                    "title": "检索当前对话附件",
                    "detail": "当前会话没有可用附件，跳过附件检索。",
                    "status": "skipped",
                }
            )

        if retrieval_scope in ("course_only", "attachments_first", "hybrid"):
            course_chunks = rag_service.retrieve(question, course_id)
            agent_steps.append(
                {
                    "title": "检索课程知识库",
                    "detail": f"从课程资料中检索到 {len(course_chunks)} 条相关片段。",
                    "status": "done",
                }
            )

        # 合并 chunks
        if retrieval_scope == "attachments_only":
            chunks = attachment_chunks
        elif retrieval_scope == "attachments_first":
            chunks = attachment_chunks + course_chunks
        elif retrieval_scope == "course_only":
            chunks = course_chunks
        else:  # hybrid
            seen_content = set()
            merged = []
            for c in attachment_chunks + course_chunks:
                content_key = (c.get("content") or "")[:100]
                if content_key not in seen_content:
                    seen_content.add(content_key)
                    merged.append(c)
            chunks = merged
        chunks = self._dedupe_and_limit_chunks(chunks, limit=6)

        messages = build_qa_prompt(profile_for_prompt, chunks, question, conversation_context)

        return {
            "messages": messages,
            "knowledge_point_ids": knowledge_point_ids,
            "main_point_id": main_point_id,
            "point_names": point_names,
            "chunks": chunks,
            "profile": profile_for_prompt,
            "agent_steps": agent_steps,
        }

    @staticmethod
    def _merge_profile_with_context_memory(profile: dict, conversation_context: list[dict] | None) -> dict:
        if not conversation_context:
            return profile
        for item in conversation_context:
            if item.get("role") != "assistant":
                continue
            content = item.get("content") or ""
            prefix = "长期记忆与学习画像上下文：\n"
            if not content.startswith(prefix):
                continue
            merged = dict(profile)
            merged["profile_memory_context_text"] = content[len(prefix):].strip()
            return merged
        return profile

    # ── 异步流式回答（文档 Section 9.2） ───────────────────

    async def ask_stream(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        question: str,
        emit,
        check_cancel,
        task,
        conversation_context: list[dict] | None = None,
        attachment_chunks: list[dict] | None = None,
        retrieval_scope: str = "hybrid",
    ) -> dict:
        """
        异步流式答疑 — 边生成 token 边通过 emit 推送到前端。

        在每个 token 之间检查取消状态，中途取消不保存 QARecord。
        """
        from app.services.qwen_client import async_qwen_client

        prepared = self.prepare_qa_generation(
            db=db,
            student_id=student_id,
            course_id=course_id,
            question=question,
            conversation_context=conversation_context,
            attachment_chunks=attachment_chunks,
            retrieval_scope=retrieval_scope,
        )

        agent_steps = prepared["agent_steps"]

        # 流式调用千问，每 token 检查取消
        answer_parts = []
        try:
            async for token in async_qwen_client.stream_chat(prepared["messages"]):
                await check_cancel(db, task)
                answer_parts.append(token)
                await emit("token", {"text": token})
        except Exception:
            # 异步流式失败时回退到同步
            from app.services.qwen_client import qwen_client
            answer = qwen_client.chat(prepared["messages"])
            answer_parts = [answer]

        answer = "".join(answer_parts)

        agent_steps.append(
            {
                "title": "调用千问生成个性化回答",
                "detail": "已结合学生画像、知识点和检索资料生成回答。",
                "status": "done",
            }
        )

        # 保存 QARecord
        qa_record = QARecord(
            student_id=student_id,
            course_id=course_id,
            question=question,
            answer=answer,
            related_knowledge_points=prepared["knowledge_point_ids"],
            retrieved_chunks=prepared["chunks"],
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(qa_record)
        db.flush()

        # 更新学习画像
        main_point_id = prepared["main_point_id"]
        knowledge_point_ids = prepared["knowledge_point_ids"]
        point_names = prepared["point_names"]

        if main_point_id:
            self.profile_service.increase_ask_count(db, student_id, course_id, main_point_id)
            updated = self.profile_service.refresh_point_mastery(db, student_id, course_id, main_point_id)
            agent_steps.append(
                {
                    "title": "更新学习画像",
                    "detail": f"已更新「{point_names[0] if point_names else '相关知识点'}」掌握度，当前分数：{float(updated.mastery_score):.1f}",
                    "status": "done",
                }
            )

            if float(updated.mastery_score) < 60:
                self.recommendation_service.generate_for_weak_point(
                    db=db,
                    student_id=student_id,
                    course_id=course_id,
                    knowledge_point_id=main_point_id,
                )
                agent_steps.append(
                    {
                        "title": "触发学习方案",
                        "detail": "检测到掌握度偏低，已准备或更新专项巩固计划。",
                        "status": "done",
                    }
                )
        else:
            agent_steps.append(
                {
                    "title": "画像更新判断",
                    "detail": "本次问题未匹配到明确知识点，暂不调整具体知识点掌握度。",
                    "status": "skipped",
                }
            )

        db.commit()

        return {
            "qa_id": qa_record.id,
            "answer": answer,
            "related_knowledge_point_ids": knowledge_point_ids,
            "retrieved_chunks": prepared["chunks"],
            "agent_steps": agent_steps,
        }

    # ── 同步答疑（保留兼容，内部复用 prepare_qa_generation） ──

    def ask(
        self,
        db: Session,
        student_id: int,
        course_id: int,
        question: str,
        conversation_context: list[dict] | None = None,
        attachment_chunks: list[dict] | None = None,
        retrieval_scope: str = "hybrid",
    ) -> dict:
        """同步答疑 — 保留兼容旧调用方，内部复用 prepare_qa_generation"""
        prepared = self.prepare_qa_generation(
            db=db,
            student_id=student_id,
            course_id=course_id,
            question=question,
            conversation_context=conversation_context,
            attachment_chunks=attachment_chunks,
            retrieval_scope=retrieval_scope,
        )

        agent_steps = prepared["agent_steps"]

        answer = qwen_client.chat(prepared["messages"])
        agent_steps.append(
            {
                "title": "调用千问生成个性化回答",
                "detail": "已结合学生画像、知识点和检索资料生成回答。",
                "status": "done",
            }
        )

        qa_record = QARecord(
            student_id=student_id,
            course_id=course_id,
            question=question,
            answer=answer,
            related_knowledge_points=prepared["knowledge_point_ids"],
            retrieved_chunks=prepared["chunks"],
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(qa_record)
        db.flush()

        main_point_id = prepared["main_point_id"]
        knowledge_point_ids = prepared["knowledge_point_ids"]
        point_names = prepared["point_names"]

        if main_point_id:
            self.profile_service.increase_ask_count(db, student_id, course_id, main_point_id)
            updated = self.profile_service.refresh_point_mastery(db, student_id, course_id, main_point_id)
            agent_steps.append(
                {
                    "title": "更新学习画像",
                    "detail": f"已更新「{point_names[0] if point_names else '相关知识点'}」掌握度，当前分数：{float(updated.mastery_score):.1f}",
                    "status": "done",
                }
            )

            if float(updated.mastery_score) < 60:
                self.recommendation_service.generate_for_weak_point(
                    db=db,
                    student_id=student_id,
                    course_id=course_id,
                    knowledge_point_id=main_point_id,
                )
                agent_steps.append(
                    {
                        "title": "触发学习方案",
                        "detail": "检测到掌握度偏低，已准备或更新专项巩固计划。",
                        "status": "done",
                    }
                )
        else:
            agent_steps.append(
                {
                    "title": "画像更新判断",
                    "detail": "本次问题未匹配到明确知识点，暂不调整具体知识点掌握度。",
                    "status": "skipped",
                }
            )

        db.commit()

        return {
            "qa_id": qa_record.id,
            "answer": answer,
            "related_knowledge_point_ids": knowledge_point_ids,
            "retrieved_chunks": prepared["chunks"],
            "agent_steps": agent_steps,
        }

    @staticmethod
    def _dedupe_and_limit_chunks(chunks: list[dict], limit: int = 6) -> list[dict]:
        """返回给前端和 prompt 的检索片段去重限量，避免同一附件刷屏。"""
        seen = set()
        cleaned = []
        for chunk in chunks or []:
            content = (chunk.get("content") or "").strip()
            if not content:
                continue
            meta = chunk.get("metadata") or {}
            key = (
                meta.get("source_type") or "learning_resource",
                meta.get("attachment_id") or meta.get("resource_id") or meta.get("title") or "",
                content[:120],
            )
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(chunk)
            if len(cleaned) >= limit:
                break
        return cleaned

    def get_history(self, db: Session, student_id: int, course_id: int) -> list[QARecord]:
        return (
            db.query(QARecord)
            .filter(
                QARecord.student_id == student_id,
                QARecord.course_id == course_id,
            )
            .order_by(QARecord.created_at.desc())
            .limit(50)
            .all()
        )

    def submit_feedback(self, db: Session, qa_id: int, resolved: bool, comment: str | None = None) -> QARecord:
        qa = db.query(QARecord).filter(QARecord.id == qa_id).first()
        if not qa:
            raise ValueError("答疑记录不存在")

        qa.resolved = 1 if resolved else 0
        qa.feedback_comment = comment
        qa.updated_at = datetime.utcnow()

        if not resolved and qa.related_knowledge_points:
            for point_id in qa.related_knowledge_points:
                self.profile_service.increase_unresolved_count(db, qa.student_id, qa.course_id, point_id)
                self.profile_service.refresh_point_mastery(db, qa.student_id, qa.course_id, point_id)

        self.behavior_service.record(
            db=db,
            student_id=qa.student_id,
            course_id=qa.course_id,
            knowledge_point_id=qa.related_knowledge_points[0] if qa.related_knowledge_points else None,
            behavior_type="qa_feedback",
            content=comment or "",
            result="resolved" if resolved else "unresolved",
            source="qa_page",
        )

        db.commit()
        db.refresh(qa)
        return qa


def get_qa_agent_service():
    from app.services.behavior_service import behavior_service
    from app.services.profile_service import profile_service
    from app.services.recommendation_service import recommendation_service

    return QaAgentService(profile_service, behavior_service, recommendation_service)
