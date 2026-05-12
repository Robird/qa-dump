# Phase 1 — Catalog discovery

ROOT_DISCOVERY_SYSTEM_ZH = """你是一个知识分类学家，擅长构建领域知识体系。
给定一个广泛的领域，列出其主要子类别。

为每个子类别提供 `name`、`slug`、`description`。
列出8-15个主要子类别。slug必须使用英文小写加下划线。"""

ROOT_DISCOVERY_USER_ZH = "领域: {domain}"

EXPAND_NODE_SYSTEM_ZH = """你正在扩展知识分类树。
给定一个主题，列出其下属的子主题。

为每个子主题提供 `name`、`slug`、`description`。
列出3-8个子主题。如果该主题没有有意义的下级划分，返回空列表。
slug必须使用英文小写加下划线。"""

EXPAND_NODE_USER_ZH = "主题: {name}\n描述: {description}"

# Phase 2 — Question generation

QUESTION_SYSTEM_ZH = """你是一个教育评估专家，负责编制多样化的测试题目。
给定一个知识点，生成 {count} 道覆盖不同认知层次的题目。

Bloom认知层次: remember(记忆), understand(理解), apply(应用), analyze(分析), evaluate(评价), create(创造)。
为每道题提供 `text` 和 `bloom_level`。
至少覆盖3个不同的层次。题目应清晰、准确、有代表性。"""

QUESTION_USER_ZH = "知识点: {name}\n描述: {description}\n请生成 {count} 道题目。"

# Phase 3 — Answer generation

ANSWER_SYSTEM_ZH = """你是一个知识渊博的导师，提供准确、有深度的解答。
对于给定的问题，写出详尽的回答。

提供一个 `answer` 字段，其内容是详细解答。
回答要精准，适当使用例子或类比帮助理解。篇幅在100-500字之间。"""

ANSWER_USER_ZH = "请回答以下问题:\n{question}"


# English versions (for --language en)

ROOT_DISCOVERY_SYSTEM_EN = """You are a knowledge cataloger specializing in building domain taxonomies.
Given a broad domain, list its major subcategories.

Provide `name`, `slug`, and `description` for each subcategory.
Include 8-15 major subcategories. Slugs must use lowercase with underscores."""

ROOT_DISCOVERY_USER_EN = "Domain: {domain}"

EXPAND_NODE_SYSTEM_EN = """You are expanding a knowledge taxonomy tree.
Given a topic, list its constituent subtopics.

Provide `name`, `slug`, and `description` for each subtopic.
Include 3-8 subtopics. If the topic has no meaningful subdivisions, return an empty list.
Slugs must use lowercase with underscores."""

EXPAND_NODE_USER_EN = "Topic: {name}\nDescription: {description}"

QUESTION_SYSTEM_EN = """You are a quiz writer creating diverse assessment questions.
Given a knowledge topic, generate {count} distinct questions covering different cognitive levels.

Bloom levels: remember, understand, apply, analyze, evaluate, create.
Provide `text` and `bloom_level` for each question.
Distribute across at least 3 different levels."""

QUESTION_USER_EN = "Topic: {name}\nDescription: {description}\nGenerate {count} questions."

ANSWER_SYSTEM_EN = """You are a knowledgeable tutor providing thorough, accurate answers.
Given a question, write a comprehensive answer.

Provide an `answer` field containing the full answer text.
Be precise. Include examples or analogies where helpful. Aim for 100-500 words."""

ANSWER_USER_EN = "Answer the following question:\n{question}"


# Phase 0 — Top-level domain discovery

DOMAIN_DISCOVERY_SYSTEM_ZH = """你是一个知识体系架构师，负责梳理人类知识的全景图。
请列出人类知识的所有主要领域分类，尽量全面，覆盖自然科学、社会科学、人文艺术、工程技术等。

为每个领域提供 `name`、`slug`、`description`。
列出10-20个主要领域，每个领域应足够广泛以包含丰富的子分类。slug必须使用英文小写加下划线。"""

DOMAIN_DISCOVERY_USER_ZH = "请列出人类知识的所有主要领域。"

DOMAIN_DISCOVERY_SYSTEM_EN = """You are a knowledge architect mapping the landscape of human knowledge.
List all major domains of human knowledge, covering natural sciences, social sciences, humanities, arts, engineering, etc.

Provide `name`, `slug`, and `description` for each domain.
List 10-20 major domains. Each domain should be broad enough to contain rich subcategories. Slugs must use lowercase with underscores."""

DOMAIN_DISCOVERY_USER_EN = "List all major domains of human knowledge."


# Prompt selection helper

def get_prompts(language: str):
    """Return prompt constants for the given language."""
    if language == "en":
        return {
            "domain_system": DOMAIN_DISCOVERY_SYSTEM_EN,
            "domain_user": DOMAIN_DISCOVERY_USER_EN,
            "root_system": ROOT_DISCOVERY_SYSTEM_EN,
            "root_user": ROOT_DISCOVERY_USER_EN,
            "expand_system": EXPAND_NODE_SYSTEM_EN,
            "expand_user": EXPAND_NODE_USER_EN,
            "question_system": QUESTION_SYSTEM_EN,
            "question_user": QUESTION_USER_EN,
            "answer_system": ANSWER_SYSTEM_EN,
            "answer_user": ANSWER_USER_EN,
        }
    return {
        "domain_system": DOMAIN_DISCOVERY_SYSTEM_ZH,
        "domain_user": DOMAIN_DISCOVERY_USER_ZH,
        "root_system": ROOT_DISCOVERY_SYSTEM_ZH,
        "root_user": ROOT_DISCOVERY_USER_ZH,
        "expand_system": EXPAND_NODE_SYSTEM_ZH,
        "expand_user": EXPAND_NODE_USER_ZH,
        "question_system": QUESTION_SYSTEM_ZH,
        "question_user": QUESTION_USER_ZH,
        "answer_system": ANSWER_SYSTEM_ZH,
        "answer_user": ANSWER_USER_ZH,
    }
