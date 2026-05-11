# Learning Map: Related Work and Reusable Ideas

这份文档用于给当前项目建立一张“站在巨人肩膀上”的学习地图。

目标不是穷尽所有相关论文，而是回答四个更实际的问题：

1. 哪些前人工作和我们现在的方向最接近？
2. 如果时间很少，最值得先读什么？
3. 哪些想法已经有人做过一部分，可以少重复发明轮子？
4. 哪些脑洞有研究价值，但目前更像高风险探索而不是近程主线？


## 1. 先说结论

和我们最接近的，不是一篇“完整对口”的论文，而是几条相邻谱系的交叉：

- 事件常识与社会心理图谱
- 人格 / 情绪 / 同理心数据
- Agent 运行时与工具调用协议
- 合成数据与课程学习
- PEFT / LoRA / 模型合并 / 多任务训练

如果只能记一句话：

**我们真正新颖的地方，不是某一项单点技术，而是把“刺激本体 + 状态条件化的人格 + 派生数据工厂 + agentic 协议训练”串成了一条线。**


## 2. 如果只够读很少

### 2.1 只够读 5 份

优先读这些：

1. `ATOMIC / ATOMIC-2020`
2. `Event2Mind`
3. `Generative Agents`
4. `Constitutional AI`
5. `Curriculum Learning` 与 `Self-Paced Learning`

为什么：

- `ATOMIC / Event2Mind` 给你“事件 -> 意图 / 情绪 / 结果”的结构骨架。
- `Generative Agents` 给你“长期存在、记忆、反思、状态”的视角。
- `Constitutional AI` 给你“单一人格底色 / charter”的方法感。
- `Curriculum Learning` 给你“先学什么、何时加难”的底层思维。

### 2.2 如果能再加 5 份

继续加：

6. `Social Chemistry 101`
7. `SocialIQA`
8. `GLUCOSE`
9. `Self-Instruct`
10. `LoRA / QLoRA / TIES-Merging / Model Soup`


## 3. 第一类资源：事件常识与社会心理骨架

这条线和我们最贴近，因为它们已经在做“给定事件，推断人的动机、反应、后果”。

### 3.1 Event2Mind

它的核心任务很接近：

- 给定事件
- 推断主角意图
- 推断主角反应
- 推断他人反应

最值得借的不是数据本身，而是任务分解方式。

对我们项目的启发：

- `stimulus -> intent` 可以直接借鉴其标签思路
- “自己 / 他人”视角切分很重要
- 同一刺激可以有多个合理心理后果

### 3.2 ATOMIC / ATOMIC-2020

这是非常值得借的结构骨架。

尤其这些关系：

- `xIntent`
- `xNeed`
- `xReact`
- `xEffect`
- `xWant`
- `oReact`
- `oEffect`
- `oWant`

对我们项目的启发：

- 很适合成为刺激语义图谱的第一版参考框架
- 可以帮助我们把“刺激后会怎样”拆成多个局部标签
- 非常适合作为 Sim-Psych 第二阶段的参考输出骨架

### 3.3 SocialIQA

偏社会情境下的常识推理。

对我们项目的启发：

- 可借其任务风格做“社会情境理解”评测
- 适合补“别人为什么这样做”的 commonsense 层

### 3.4 GLUCOSE

偏隐含因果与常识补全。

对我们项目的启发：

- 可以借来思考刺激和背景之间的隐含联系
- 对生成 richer belief 很有帮助

### 3.5 Social Chemistry 101

偏社会规范、边界、行为评价。

对我们项目的启发：

- 非常适合补“什么行为得体 / 失礼 / 有害”
- 对角色在复杂社会情境里的“理想响应”很有用


## 4. 第二类资源：人格、情绪、同理心与角色

这条线能借，但不能全盘照搬。

### 4.1 Persona-Chat

经典 persona 数据。

可借：

- 稳定角色设定的表达方式
- 一致性 persona conditioning 的基本套路

不要照搬：

- 它更偏表层口吻，不足以支撑“人格动力学”

### 4.2 LIGHT

角色、世界观、互动上下文更强。

可借：

- 角色在场景中的 condition 设计
- 世界状态与角色设定的联动

### 4.3 EmpatheticDialogues

偏情绪触发后的回应。

可借：

- 情绪事件到语言回应的映射
- 安慰、共情类回应的风格

不要照搬：

- 它更偏安慰型对话，不等于复杂人格训练

### 4.4 GoEmotions / MELD / IEMOCAP / DailyDialog

主要是情绪识别和情绪对话资源。

可借：

- 情绪标签体系
- 多粒度情绪分类

不要照搬：

- 情绪标签不等于状态轨迹
- “识别情绪”不等于“形成行动意图”


## 5. 第三类资源：心理学与认知科学底座

这条线很重要，因为它更接近“刺激本体”和“评价路径”的理论骨架。

### 5.1 OCC appraisal model

非常适合做事件评价骨架。

可借：

- 事件结果
- 行为规范
- 对对象的喜恶

这有助于把刺激分类从“场景列表”提升为“评价结构”。

### 5.2 Smith & Ellsworth 认知评价维度

非常适合做刺激参数化：

- 新颖性
- 愉悦度
- 确定性
- 可控性
- 归因
- 努力需求

这套维度很适合第一阶段刺激数据集。

### 5.3 Panksepp 七大情感系统

非常适合作为刺激顶级根目录：

- SEEKING
- RAGE
- FEAR
- LUST
- CARE
- PANIC / GRIEF
- PLAY

### 5.4 Russell circumplex model

适合做低维状态空间：

- valence
- arousal

如果后续状态 schema 想先简单起步，这套可用。

### 5.5 Self-Determination Theory

非常适合长期 agent：

- autonomy
- competence
- relatedness

它很适合解释“为什么这个角色会继续成长、会受挫、会恢复”。

### 5.6 Attachment theory

对“被爱、被忽视、被抛弃、修复关系”特别有用。

这对 Sim-Psych 很关键。


## 6. 第四类资源：Agent、长期状态与协议

### 6.1 ReAct

把推理与行动串起来的经典起点。

可借：

- thought / action / observation loop
- 如何把中间推理和行动衔接

### 6.2 Toolformer

工具使用训练的代表性工作。

可借：

- 工具调用作为训练目标
- 何时插入工具行为

### 6.3 Gorilla / OpenFunctions / xLAM 一类

偏函数调用和工具协议。

可借：

- 工具 schema
- 结构化 action target

### 6.4 Generative Agents

这篇对我们不是“直接照做”，但视角很重要。

可借：

- 记忆
- 反思
- 计划
- 长期连续存在的主体视角

### 6.5 Constitutional AI

这条线对我们“单一人格底色”特别有帮助。

可借：

- core charter / 行为原则
- 通过原则塑造模型的整体倾向

这和我们要做的“真诚、勇敢、向善、自省”的人格基底高度相关。


## 7. 第五类资源：合成数据与课程学习

### 7.1 Self-Instruct

经典起点。

可借：

- 如何把现有少量高质量样本扩展成更大训练集

### 7.2 Evol-Instruct / WizardLM

非常适合借“任务难度演化”的方法感。

可借：

- 从简单任务逐渐演化到复杂任务
- 如何系统提高任务复杂度

### 7.3 Orca / Orca 2

可借：

- 中间解释和步骤蒸馏
- 什么时候 short explanation 比 raw CoT 更实用

### 7.4 Curriculum Learning

建议至少看经典思路。

核心观念：

- 样本不必平铺同权
- 学习顺序本身就是训练设计的一部分

### 7.5 Self-Paced Learning / Competence-Based Curriculum

这条线特别适合你问的：

- 什么时候加入更高层任务？
- 难度怎么随训练推进？

可借的关键思路：

- 不要求低层任务完全学到极致再上更高层
- 用“当前能力覆盖范围”逐步解锁更难样本
- 保持 replay，避免忘掉简单任务


## 8. 第六类资源：PEFT、LoRA、多任务与模型合并

这条线和你问的“多个正交 LoRA / 合并 / 低带宽并行”最相关。

### 8.1 LoRA / QLoRA / DoRA

这是基础。

可借：

- 低成本实验
- 多轮快速验证
- 针对不同数据子集单独训练 adapter

### 8.2 AdapterFusion / MAD-X

这些更早的 adapter 工作很值得看。

可借：

- 不同任务保留独立 adapter
- 后期再做融合，而不是一开始强行合并

### 8.3 Task Arithmetic

核心想法：

- 把 finetune 后的权重差当向量操作

可借：

- 任务差分并不一定只能“选一个”
- 可以探索增减、插值、组合

### 8.4 Model Soup

更偏“把若干相近模型做权重平均 / 融合”。

可借：

- 多个局部最优可以有一定集成效应

限制：

- 通常更适合相近任务、相近训练路径

### 8.5 TIES-Merging / DARE

这是目前很值得借的合并路线。

可借：

- 在 delta merge 时减少冲突
- 不是简单平均，而是有冲突裁剪和稀疏处理

### 8.6 LoRAHub 与 Mixture-of-LoRA / X-LoRA 一类

这条线更接近你问的“多个功能模块共存”。

可借：

- 保留多个 adapter
- 通过路由或组合决定当前调用哪部分

对我们项目的启发：

- 很多时候“保留多个 LoRA + 运行时路由”比“提前硬合并回一个权重”更靠谱


## 9. 针对你当前脑洞的直接回答

### 9.1 简单任务应该训练到什么程度，再加入更高层任务？

前人经验更支持：

- 不要等简单任务完全收敛后才开始加难
- 也不要一开始就全量混训

更稳妥的经验法则：

1. 先用简单任务打底，让模型学到格式和最核心行为。
2. 当简单任务验证集进入“边际收益下降”阶段时，引入少量更难任务。
3. 后续保持简单任务 replay，而不是完全切走。
4. 用按难度分桶的评测，而不是只看总平均分。

如果资源很少，我更建议：

- easy-only warmup
- easy+medium mixture
- easy+medium+hard staged mixture

而不是：

- easy 训满
- 再完全切到 medium
- 再完全切到 hard

### 9.2 两个不太相关的简单任务，应该混合训练还是逐个训练？

大多数情况下：

- **混合训练 + 合理采样** 比纯顺序训练更稳

原因：

- 顺序训练更容易遗忘前面的任务
- 混合训练更接近未来真实分布

但有两个例外：

1. 两个任务格式强冲突。
2. 你本来就打算保留独立 adapter，而不是训单一权重。

实际建议：

- 如果目标是一个统一模型，优先混合
- 如果目标是模块化能力库，独立 adapter 也合理

### 9.3 能否创建多个“正交 LoRA”分别训练不同任务，再合并回完整权重？

可以探索，但不能假设“只要维度分区就天然互不干扰”。

原因：

- 即使 LoRA 参数子空间分开，底层 base model 激活还是共享的
- 不同任务通过同一主干传播，仍会在输出分布上耦合

更现实的判断是：

- **这是一个可研究方向**
- **但不是已有成熟结论**

更靠谱的近似前人经验是：

1. 分别训练多个 adapter
2. 先做独立评测
3. 再尝试 merge
4. merge 不理想时，转为 routing / mixture-of-adapters

### 9.4 通过较低频率合并多个 LoRA，能否当成低带宽消费级 GPU 上的数据并行手段？

这很像这些方向的混合体：

- federated averaging
- decentralized training
- adapter merging
- model soup

它在原理上不是异想天开，但现实里有几个难点：

- 不同 worker 的梯度方向可能冲突很大
- 低频 merge 可能导致参数漂移
- 非 IID 数据会放大不稳定性
- merge 频率、学习率、任务分布会强烈影响结果

我的判断是：

- 作为研究型玩具很值得试
- 作为近期主力生产方案风险较高

如果真要试，更建议：

- 先在 adapter delta 上做 merge，而不是全量权重
- 先做相近任务，不要一上来混特别远的任务
- 每轮 merge 后保留统一验证
- 优先对比 `simple average`、`TIES`、`DARE`

### 9.5 会不会出现某种“嵌合模型”或类似彩票假设的效果？

可能会有局部正迁移，但不要过早期待神奇彩票。

更常见的现实情况是：

- 相近任务有时能互补
- 远任务容易互相污染
- 真正稳定的收益往往来自：
  - 好的数据混合
  - 好的路由
  - 好的评测
  - 好的合并策略

所以这条线的实用结论通常不是“神奇涌现”，而是：

- 什么时候该 merge
- 什么时候该保留模块化
- 什么时候该用 router 而不是硬融合


## 10. 对我们项目最值得借的具体东西

### 10.1 直接可借

- 用 `ATOMIC / Event2Mind` 补刺激到意图的结构标签
- 用 `Constitutional AI` 的思路写人格底色 charter
- 用 `Curriculum Learning` / `Self-Paced` 指导 Bloom 渐进训练
- 用 `LoRA + merge` 做低成本原理验证

### 10.2 值得谨慎借

- Persona 类数据
- 纯长 CoT 蒸馏
- 一上来就做复杂多人格

### 10.3 暂时不建议投入过重

- 过早押注复杂正交 LoRA 合并方案
- 过早绑定某个极复杂的训练协议
- 在首批数据没出来前就设计太花的并行训练系统


## 11. 一个实用阅读顺序

### 第一轮：建立大图景

先看这些名字和摘要，知道它们各自解决什么：

- Event2Mind
- ATOMIC-2020
- Social Chemistry 101
- Generative Agents
- Constitutional AI
- Curriculum Learning
- Self-Paced Learning
- LoRA / QLoRA
- Model Soup
- TIES-Merging

### 第二轮：只精读和我们最近工作最相关的

优先精读：

- Event2Mind
- ATOMIC-2020
- Curriculum Learning / Self-Paced Learning
- Constitutional AI
- LoRA / TIES-Merging

### 第三轮：按近期实验需要补

如果近期要做：

- Sim-Psych：补 appraisal theory、attachment、Social Chemistry
- agentic SFT：补 ReAct、Toolformer、xLAM / OpenFunctions
- adapter merge：补 Model Soup、Task Arithmetic、TIES、DARE、LoRAHub 一类


## 12. 最后给项目的现实建议

如果资源非常有限，不要试图同时吃透所有方向。

更稳的路径是：

1. 用最基础的 `remember` QA + recall 数据验证链路
2. 用少量结构化 agentic 样本验证 `observation / belief / me`
3. 再用小规模 Sim-Psych 刺激样本验证“刺激 -> 评价 -> 意图 -> 回应”
4. 最后才去碰复杂课程学习、LoRA 合并和低带宽并行

先证明主线通，再去探索那些漂亮但高风险的扩展。


## 13. 可进一步补充的方向

后续如果继续整理学习地图，可以继续扩展：

- 每项资源的核心论文 / 博客 / 开源实现链接
- “最值得读的章节”而不是整篇通读
- 与当前仓库任务的逐项映射表
- 针对 LoRA merge 的最小实验设计草案

