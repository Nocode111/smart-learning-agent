import re
from datetime import datetime, timedelta


class AgentReplyActionDetector:
    invitation_patterns = [
        "需要我",
        "要不要我",
        "是否需要",
        "你要不要",
        "你想不想",
        "要我帮你",
        "需要一起",
        "需要继续",
        "我可以继续",
        "我可以帮你",
    ]

    common_topic_terms = [
        "栈", "队列", "链表", "数组", "树", "二叉树", "图", "排序",
        "查找", "递归", "哈希", "堆", "时间复杂度", "空间复杂度",
        "动态规划", "贪心", "回溯", "分治",
    ]

    guided_practice_keywords = [
        "小练习", "练一下", "一起做", "做这个练习", "巩固一下", "检测一下",
    ]

    generate_exercise_keywords = [
        "出几道题", "生成练习题", "生成几道", "做几道题", "专项练习",
    ]

    continue_explanation_keywords = [
        "继续讲", "继续解释", "展开讲", "再讲细一点", "换个例子",
    ]

    code_example_keywords = [
        "代码示例", "写代码", "用代码", "Python", "Java", "伪代码",
    ]

    compare_keywords = [
        "对比", "区别", "比较", "放在一起看",
    ]

    def detect(
        self,
        assistant_text: str,
        last_topic: str | None = None,
        knowledge_point_ids: list[int] | None = None,
    ) -> dict | None:
        text = assistant_text or ""
        if not text.strip():
            return None

        invitation_sentence = self.extract_last_invitation_sentence(text)
        if not invitation_sentence:
            return None

        action_type, confirm_intent, payload = self.classify_invitation(invitation_sentence)
        if not action_type:
            return None

        topic = last_topic or self.extract_topic(text)
        now = datetime.utcnow()

        return {
            "type": action_type,
            "source": "assistant_reply_postprocess",
            "topic": topic,
            "knowledge_point_ids": knowledge_point_ids or [],
            "question": invitation_sentence,
            "confirm_intent": confirm_intent,
            "negative_intent": "cancel_pending_action",
            "payload": payload,
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=30)).isoformat(),
        }

    def extract_last_invitation_sentence(self, text: str) -> str | None:
        sentences = re.split(r"(?<=[。！？?!\n])", text)
        sentences = [s.strip() for s in sentences if s.strip()]
        for sentence in reversed(sentences[-5:]):
            if any(pattern in sentence for pattern in self.invitation_patterns):
                if "吗" in sentence or "？" in sentence or "?" in sentence:
                    return sentence
        return None

    def classify_invitation(self, sentence: str):
        if any(keyword in sentence for keyword in self.generate_exercise_keywords):
            return (
                "confirm_generate_exercise",
                "clarify_exercise_count",
                {
                    "default_question_count": 5,
                    "include_answer": True,
                    "include_explanation": True,
                },
            )

        if any(keyword in sentence for keyword in self.guided_practice_keywords):
            return (
                "confirm_guided_practice",
                "start_guided_practice",
                {
                    "practice_mode": "guided",
                    "default_question_count": 1,
                },
            )

        if any(keyword in sentence for keyword in self.code_example_keywords):
            return (
                "confirm_code_example",
                "provide_code_example",
                {},
            )

        if any(keyword in sentence for keyword in self.compare_keywords):
            return (
                "confirm_compare_explanation",
                "provide_compare_explanation",
                {},
            )

        if any(keyword in sentence for keyword in self.continue_explanation_keywords):
            return (
                "confirm_continue_explanation",
                "continue_explanation",
                {},
            )

        return None, None, None

    def extract_topic(self, text: str) -> str | None:
        matched = []
        for term in self.common_topic_terms:
            if term in text:
                matched.append(term)

        if not matched:
            return None

        if len(matched) == 1:
            return matched[0]

        return "和".join(matched[:3])


agent_reply_action_detector = AgentReplyActionDetector()
