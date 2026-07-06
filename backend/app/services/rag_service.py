import logging

from sqlalchemy.orm import Session

from app.config import settings
from app.models.agent_attachment import AgentAttachment
from app.services.qwen_client import qwen_client
from app.vector_store.chroma_store import chroma_store

logger = logging.getLogger(__name__)


class RagService:
    def __init__(self):
        self.collection = chroma_store.get_collection()

    def split_text(self, text: str, chunk_size: int = 600) -> list[str]:
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        chunks = []
        for paragraph in paragraphs:
            if len(paragraph) <= chunk_size:
                chunks.append(paragraph)
            else:
                for i in range(0, len(paragraph), chunk_size):
                    chunks.append(paragraph[i : i + chunk_size])
        return chunks

    def index_resource(
        self,
        resource_id: int,
        course_id: int,
        knowledge_point_id: int | None,
        title: str,
        content: str,
        course_type: str = "teacher",
        owner_id: int | None = None,
    ):
        """索引资源，metadata 增加 course_type 和 owner_id（文档 Section 11.2）"""
        chunks = self.split_text(content)
        ids = []
        documents = []
        embeddings = []
        metadatas = []

        for index, chunk in enumerate(chunks):
            chunk_id = f"resource_{resource_id}_chunk_{index}"
            ids.append(chunk_id)
            documents.append(chunk)
            embeddings.append(qwen_client.embedding(chunk))
            metadatas.append(
                {
                    "resource_id": str(resource_id),
                    "course_id": str(course_id),
                    "knowledge_point_id": str(knowledge_point_id or ""),
                    "title": title,
                    "course_type": course_type,
                    "owner_id": str(owner_id or ""),
                }
            )

        self.collection.upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )

    def delete_resource_vectors(self, resource_id: int):
        """删除指定资源的所有向量 chunk（文档 Section 11.3）"""
        try:
            self.collection.delete(where={"resource_id": str(resource_id)})
        except Exception:
            # Chroma 删除失败不阻塞
            pass

    def retrieve(self, query: str, course_id: int, top_k: int | None = None) -> list[dict]:
        """检索课程资料。

        对话附件也带有 course_id，但它们是用户私有资料，不能被课程级检索返回。
        因此这里会过滤 source_type=conversation_attachment 的向量。
        """
        limit = top_k or settings.rag_top_k
        query_embedding = qwen_client.embedding(query)
        result = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=max(limit * 3, limit),
            where={"course_id": str(course_id)},
        )

        docs = result.get("documents", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]

        chunks = []
        for doc, meta, distance in zip(docs, metas, distances):
            if (meta or {}).get("source_type") == "conversation_attachment":
                continue
            chunks.append(
                {
                    "content": doc,
                    "metadata": meta,
                    "distance": distance,
                }
            )
            if len(chunks) >= limit:
                break
        return chunks


    # ── 附件索引方法（文档 Section 11.2） ──────────────────────────

    def index_attachment(
        self,
        attachment_id: int,
        conversation_id: int,
        student_id: int,
        course_id: int,
        title: str,
        file_name: str,
        content: str,
    ) -> list[dict]:
        """索引附件文本，metadata 包含 source_type 和隔离字段"""
        chunks = self.split_text(content)
        ids = []
        documents = []
        embeddings = []
        metadatas = []

        for index, chunk in enumerate(chunks):
            vector_id = f"attachment_{attachment_id}_chunk_{index}"
            ids.append(vector_id)
            documents.append(chunk)
            embeddings.append(qwen_client.embedding(chunk))
            metadatas.append({
                "source_type": "conversation_attachment",
                "attachment_id": str(attachment_id),
                "conversation_id": str(conversation_id),
                "student_id": str(student_id),
                "course_id": str(course_id),
                "title": title,
                "file_name": file_name,
            })

        self.collection.upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )

        return [
            {"vector_id": vector_id, "content": content, "metadata": metadata}
            for vector_id, content, metadata in zip(ids, documents, metadatas)
        ]

    @staticmethod
    def _active_attachment_ids(
        db: Session | None,
        attachment_ids: set[int],
        conversation_id: int,
        student_id: int,
        course_id: int,
    ) -> set[int]:
        """返回仍然 active + indexed 的附件 ID，防止使用已移除附件的残留向量。"""
        if not attachment_ids:
            return set()

        if db is None:
            # 兼容旧调用方；没有 db 时无法二次校验。
            return attachment_ids

        rows = (
            db.query(AgentAttachment.id)
            .filter(
                AgentAttachment.id.in_(list(attachment_ids)),
                AgentAttachment.conversation_id == conversation_id,
                AgentAttachment.student_id == student_id,
                AgentAttachment.course_id == course_id,
                AgentAttachment.status == "active",
                AgentAttachment.index_status == "indexed",
            )
            .all()
        )
        return {int(row[0]) for row in rows}

    @staticmethod
    def _filter_active_attachment_chunks(
        chunks: list[dict],
        active_ids: set[int],
        limit: int,
    ) -> list[dict]:
        filtered = []
        for chunk in chunks:
            meta = chunk.get("metadata") or {}
            try:
                attachment_id = int(meta.get("attachment_id"))
            except (TypeError, ValueError):
                continue
            if attachment_id not in active_ids:
                continue
            filtered.append(chunk)
            if len(filtered) >= limit:
                break
        return filtered

    def retrieve_attachments(
        self,
        query: str,
        conversation_id: int,
        student_id: int,
        course_id: int,
        top_k: int = 5,
        db: Session | None = None,
    ) -> list[dict]:
        """检索当前会话附件（文档 Section 11.3）"""
        query_embedding = qwen_client.embedding(query)
        result = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=max(top_k * 3, top_k),
            where={
                "$and": [
                    {"source_type": "conversation_attachment"},
                    {"conversation_id": str(conversation_id)},
                    {"student_id": str(student_id)},
                    {"course_id": str(course_id)},
                ]
            },
        )

        docs = result.get("documents", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]

        chunks = []
        for doc, meta, distance in zip(docs, metas, distances):
            chunks.append({
                "content": doc,
                "metadata": meta,
                "distance": distance,
            })

        attachment_ids = set()
        for chunk in chunks:
            try:
                attachment_ids.add(int((chunk.get("metadata") or {}).get("attachment_id")))
            except (TypeError, ValueError):
                continue
        active_ids = self._active_attachment_ids(
            db=db,
            attachment_ids=attachment_ids,
            conversation_id=conversation_id,
            student_id=student_id,
            course_id=course_id,
        )
        return self._filter_active_attachment_chunks(chunks, active_ids, top_k)

    def retrieve_by_attachment_ids(
        self,
        query: str,
        attachment_ids: list[int],
        conversation_id: int,
        student_id: int,
        course_id: int,
        top_k: int = 5,
        db: Session | None = None,
    ) -> list[dict]:
        """按指定附件ID检索（文档 Section 11.4）"""
        requested_ids = {int(item) for item in attachment_ids if item is not None}
        active_ids = self._active_attachment_ids(
            db=db,
            attachment_ids=requested_ids,
            conversation_id=conversation_id,
            student_id=student_id,
            course_id=course_id,
        )
        if not active_ids:
            return []

        all_chunks = []
        for attachment_id in active_ids:
            query_embedding = qwen_client.embedding(query)
            result = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where={
                    "$and": [
                        {"source_type": "conversation_attachment"},
                        {"attachment_id": str(attachment_id)},
                        {"conversation_id": str(conversation_id)},
                        {"student_id": str(student_id)},
                        {"course_id": str(course_id)},
                    ]
                },
            )

            docs = result.get("documents", [[]])[0]
            metas = result.get("metadatas", [[]])[0]
            distances = result.get("distances", [[]])[0]

            for doc, meta, distance in zip(docs, metas, distances):
                all_chunks.append({
                    "content": doc,
                    "metadata": meta,
                    "distance": distance,
                })

        sorted_chunks = sorted(all_chunks, key=lambda x: x.get("distance", 999))
        return self._filter_active_attachment_chunks(sorted_chunks, active_ids, top_k)

    def delete_attachment_vectors(self, attachment_id: int):
        """删除指定附件的所有向量（文档 Section 11.5）"""
        try:
            self.collection.delete(
                where={
                    "$and": [
                        {"source_type": "conversation_attachment"},
                        {"attachment_id": str(attachment_id)},
                    ]
                },
            )
        except Exception as exc:
            logger.warning("删除附件向量失败 attachment_id=%s: %s", attachment_id, exc)


rag_service = RagService()
