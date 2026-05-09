# Sim-Psych and Agentic Context Format Notes

这份文档记录阅读外部后训练设计材料后的新认知，重点讨论：

- 我们正在规划的 QA / Sim-Psych 数据，应如何与 Agentic 上下文协议对齐
- 为什么“数据真相”应优先保存在语义层，而不是 prompt 字符串层
- 第一批最基础的 `remember` 数据，如何尽快投影到可训练的 agentic 样本格式

相关参考材料：

- `/mnt/fast/LLM/study-sft/examples/agentic-ml/01-ask-and-answer.txt`
- `/mnt/fast/LLM/study-sft/docs/agentic-context-format-design.md`


## 1. 一个很重要的新认知

外部文档的价值不只是提出了一套新消息格式，而是把：

- 运行时 Agent loop
- 结构化上下文
- 工具调用
- 训练样本
- 安全序列化

放进了同一个协议层来思考。

这对我们当前项目的启发是：

**我们不应只生成“可以读的文本样本”，而应尽早生成“可以投影到 Agentic 上下文协议中的语义样本”。**

换句话说，未来真正稳定的训练材料，最好不是一堆 prompt 字符串，而是一种更高层的结构化记录。文本只是这些记录的一种投影。


## 2. 对我们当前项目最有启发的设计点

我认为外部文档里有四个点特别值得吸收。

### 2.1 `observation / belief / me` 的角色拆分很有用

这个拆分比传统 `system / user / assistant` 更适合我们未来的目标。

- `observation`：外界刺激、问题、工具返回、环境变化
- `belief`：角色底色、当前状态、可用工具、局部规则、任务上下文
- `me`：主体当前的 deliberation / reasoning / action / response

这与我们之前讨论的“刺激 -> 评价 -> 状态变化 -> 意图 -> 行为”天然相容。

### 2.2 `opaque_payload` 和 `structured_region` 的区分很关键

这意味着我们以后生成数据时，不必把所有东西都当成纯平文本。

例如：

- 用户问题、环境原始文本、网页片段、群聊截图转写，可以视为 `opaque_payload`
- 结构化 recall、工具签名、意图标签、状态变量、动作脚本，可以视为 `structured_region`

这对 Sim-Psych 尤其重要，因为刺激样本里会有大量“原始事件描述”，而理想响应里会有大量“结构化内部路径”。

### 2.3 “语义 AST 优先于文本 prompt” 是非常正确的

外部文档强调：

- JSON AST 是语义真相
- token 序列只是 wire format
- prompt 文本只是可视化投影

这对我们当前的数据工程有直接影响：

如果未来的数据最终都要进入 agentic 训练协议，那么现在就不应该把最终真相只保存在拼接好的字符串里，而应该尽量保留结构化语义层。

### 2.4 loss mask 和 span metadata 值得提前考虑

这说明数据集不只是“内容对不对”，还包括“哪部分参与监督”。

这对我们很重要，因为未来我们会有很多不同性质的字段：

- stimulus
- state
- recall
- reasoning
- intent
- action
- answer

这些不一定都要一起进 loss。提前在数据结构层考虑 target span，是对的。


## 3. 我们的数据与 Agentic 协议的自然映射

### 3.1 QA 数据

最基础的 `remember` 知识召回数据，其实已经能非常自然地投影进 agentic 上下文。

一种直观映射是：

- `observation`：用户问题
- `belief`：可选的角色说明、工具表、任务模式、局部记忆
- `me`：recall / answer / tool action

如果是最简单的无工具版本：

- `observation` 里放问题
- `belief` 里只放最少的运行时身份说明
- `me` 里放短 deliberation + 最终回答

如果是后续增强版本：

- `me` 可以先输出 `knowledge_recall`
- 再输出 `answer`

这说明我们目前构建的 `BloomAugmentTask` 和 `RecallDeriveTask`，不只是数据后处理任务，也是在给未来的 agentic SFT 预制更友好的中间目标。

### 3.2 Sim-Psych 数据

Sim-Psych 的映射其实更漂亮：

- `observation`：刺激事件本身
- `belief`：人格底色、当前状态、关系背景、价值约束
- `me`：评价过程、状态变化、主导意图、外显行为

这几乎就是我们这条路线最理想的协议落点。

也就是说，Sim-Psych 项目不是独立于 Agentic 训练协议的，它天然适合作为这套协议的高阶训练材料。


## 4. 两阶段设计与 Agentic 协议如何对齐

我们已经决定把复杂性拆成两个阶段。

### 第一阶段：先做刺激数据集

在这个阶段，我们应优先生成：

- 刺激本体
- 刺激实例
- 条件化变量
- 可能触发的评价维度
- 可能唤起的意图原语

但此时还不必强行把所有内容写成最终 `me` 目标。

更适合的做法是：

- 先把刺激样本保存成语义 JSON
- 未来再投影到 `observation` 和局部 `belief`

### 第二阶段：生成理想响应

这个阶段就更接近 agentic 训练目标了。

理想响应可直接拆成：

- `me.deliberation`
- `me.structured_reasoning`
- `me.intent`
- `me.action` 或 `me.response`

这意味着第二阶段的输出，应该从一开始就考虑“如何成为 `me` 的目标内容”，而不是只生成散文式分析。


## 5. 对我们现有文档和任务规划的直接启发

### 5.1 Shared Derived-Data Foundation 将来应支持“语义导出”而不仅是文本导出

目前我们规划了：

- per-item artifact
- aggregate JSONL export
- manifest

后面应补充一个观念：

- 导出不只是平面文本记录
- 还应支持语义 AST 风格的中间表示

至少对以下任务有帮助：

- `RecallDeriveTask`
- `ReasoningCompressTask`
- 未来的 Sim-Psych `AppraisalDerive`

### 5.2 `RecallDeriveTask` 很适合作为 agentic `me` 的早期中间目标

如果首批数据只做到 `remember` 知识召回，也完全值得立刻试。

因为可以很快做三种对照：

1. `observation(question) -> me(answer)`
2. `observation(question) -> me(recall + answer)`
3. `observation(question) + belief(task hint) -> me(recall + answer)`

这能非常快地验证这条路在原理上是否通。

### 5.3 `ReasoningCompressTask` 应优先输出结构化片段，而不是长文本

受外部格式设计启发，后续 reasoning 压缩任务最好优先输出：

- step list
- candidate / verification / revision
- short recall block

而不是只输出一段可读 prose。

因为结构化片段更容易落进 `structured_region`。


## 6. 推荐的数据真相层设计

对于我们自己的数据，建议区分三层：

### 6.1 Semantic truth

真正的语义记录，推荐 JSON 化。

例如 QA 项：

```json
{
  "task_family": "qa_recall",
  "question": "...",
  "knowledge_recall": ["..."],
  "answer": "...",
  "bloom_level": "remember"
}
```

例如 Sim-Psych 项：

```json
{
  "task_family": "sim_psych",
  "stimulus": "...",
  "state": {
    "confidence": 0.4,
    "fatigue": 0.7
  },
  "appraisal": ["..."],
  "intent": ["repair_connection"],
  "response": "..."
}
```

### 6.2 Protocol projection

把 semantic truth 投影成：

- `observation`
- `belief`
- `me`

以及内部的 `opaque_payload` / `structured_region`。

### 6.3 Text projection

最后才是给人阅读、给现有训练脚本兼容的 prompt 文本。

这个顺序不要反过来。


## 7. 如果只用很少资源，第一批实验最值得怎么做？

我会建议先做最小闭环，而不是追求格式完美。

### 路线 A：最小 QA 验证

目标：

- 用 `remember` 级 QA 样本验证 `recall -> answer` 这条路是否提升稳定性

最小样本语义层：

- question
- recall
- answer

最小协议映射：

- `observation`: question
- `me`: recall + answer

### 路线 B：最小 Sim-Psych 验证

目标：

- 选一小批刺激样本，验证“刺激 -> 评价 -> 意图 -> 回应”是否能被模型学到

最小样本语义层：

- stimulus
- state hint
- dominant intent
- ideal response

最小协议映射：

- `observation`: stimulus
- `belief`: state hint + core charter
- `me`: short appraisal + dominant intent + response

这两条都不需要等大而全的数据工厂完工。


## 8. 一个很实际的提醒

Agentic 协议设计很强，但它也会反过来诱惑我们过早地把所有数据都格式化得过于复杂。

要小心两个风险：

### 风险 1：过早绑定具体 token 方案

像 `<|box_start|>`、`<|quad_start|>` 这些边界 token 的设计很重要，但对我们当前数据工程来说，暂时不应该让 token 细节绑死语义层设计。

### 风险 2：把“结构化”误解成“复杂化”

结构化的目标不是堆更多字段，而是明确：

- 哪些是 observation
- 哪些是 belief
- 哪些是 me 的训练目标

如果一份样本的结构太复杂，以至于人很难看懂，那它未必是更好的第一阶段样本。


## 9. 当前最值得写进原则的一句话

**先保存语义真相，再决定它如何投影到 agentic 上下文；不要把拼接好的 prompt 字符串当成唯一真相。**

这句话值得成为我们后续所有派生数据任务和心理模拟任务的共同设计原则。


## 10. 下一步可考虑补充到仓库文档的方向

后续如果继续推进，建议把这些内容分别纳入：

- 在 `Shared Derived-Data Foundation` 里加入 semantic export / protocol projection 的规划
- 在 `RecallDeriveTask` 里加入 early agentic target 的说明
- 在 Sim-Psych 相关文档里加入 `observation / belief / me` 的映射章节
- 单独新增一份 `semantic-sample-schema` 规格草案

这样未来无论是 QA 课程学习路线，还是 Sim-Psych 人格训练路线，都能更自然地接入同一套后训练协议。
