# 调研与取舍

核对日期：2026-10-18。公开源码和文档的版本、网址及下载摘要见 [references.json](references.json)。完整下载件和独立 Git checkout 位于被忽略的 `reference/`，运行时不读取它们。

## 标题

[agent-session-titles](https://github.com/panda-z519/agent-session-titles) 的实际实现是 Skill、生命周期钩子和 Python 脚本的组合。Agent 根据任务生成标题，脚本把标题写入 Codex。它没有替换 Codex 自身的标题生成算法。

采用其“模型负责语义、脚本负责写入和状态保护”的分工。本次按用户确认恢复 `状态｜初始需求｜当前进展`，交付为 Codex 插件。复制固定提交 `2d931a54a736a57c23a3e9a7fcfca56031dfd5f3` 的 `parse_three_part_title`、`protected_segments` 和 `merge_protected_title`，改编手动改名协调逻辑及 Skill 指导。MIT 许可随源码和插件包保留。

沿用上游的插件清单、Skill 和脚本组合，但不使用其全局安装流程、全局 Hooks 或数据库写入回退。上游全局配置不符合本次“只在测试项目生效”的要求；因此增加项目安装器、独立插件标识、安装记录、更新摘要检查和卸载流程。插件由 Codex 的项目配置真实加载，标题仍通过官方 `thread/read` / `thread/name/set` 写入和回读。

这不是替换 Codex 原生标题算法。Agent 在项目规则约束下调用插件中的 Skill 和脚本；初始需求固定，进展和状态更新，手动修改过的段保留。0.2.0 仅依靠主动调用，在桌面简短问答中实际漏做。0.3.0 因此采用上游的生命周期提醒方式，使用项目插件内的 `UserPromptSubmit` 和 `Stop`；其中按回合核验、最多补做一次的 Stop 检查为本项目新增。没有照搬上游的全局安装或写库回退。

依据 [官方 Hooks 文档](https://learn.chatgpt.com/docs/hooks)，插件脚本同样需要信任审查；`UserPromptSubmit` 可追加上下文，`Stop` 的 `decision: block` 可要求继续，`stop_hook_active` 用于识别补做流程。本项目通过 `/hooks` 正式审查，不自动写信任记录，也不使用绕过信任检查的选项。插件作用范围仍由项目配置和脚本双重限制。

依据：[官方插件打包与项目配置](https://developers.openai.com/plugins/build/plugins)、[App server](https://learn.chatgpt.com/docs/app-server)、[项目规则](https://learn.chatgpt.com/docs/agent-configuration/agents-md)、[Skills](https://learn.chatgpt.com/docs/build-skills)。本机 CLI 为 `0.163.0-alpha.10.2`，已生成协议 schema，检查实际加载与改名方法。插件列表的远端加载曾导致实际安装超时；依据当前 schema，安装发现现明确限定 `marketplaceKinds: ["local"]`，并以真实安装重测。

实现取舍由项目隔离、真实可安装及可卸载决定。运行和更新不依赖 `reference/`；原仓库后续可独立拉取更新，再审核需要合入的变更。

用户随后要求全局生效，因此 0.4.0 保留项目模式，另加当前 `CODEX_HOME` 的全局安装。按 [官方插件打包文档](https://developers.openai.com/plugins/build/plugins)，用户配置可启用插件，项目层可覆盖用户默认值；本项目复用同一插件包和本地来源，将全局配置写入用户层。目录和状态限制仍由脚本检查，Hooks 审查也保持不变。新增的工作集中于范围切换、双向保护记录交接和全局安装生命周期，无需更换模型或标题算法。

## 表达

| 来源 | 采用内容 | 证据与局限 |
| --- | --- | --- |
| [GPT with Taste](https://github.com/NB-Corp/gpt-with-taste) | 从读者的问题和下一步出发组织信息；先筛选和解释，再写句子；移除重复的过程汇报 | 仓库保存原任务、材料、提示词和两侧输出。属于作者的少量示例，不是独立效果证明；使用完整 Main，不能把改善归因于单条规则或钩子 |
| [plain-english](https://github.com/Tradelord223/plain-english) | 保留事实、适用条件、否定、证据强度、执行状态和精确标识 | 有清晰的语义约束和行为用例；项目规模较小，没有证实中文对话阅读效果 |
| [plain-writing-skill](https://github.com/docwriter-org/plain-writing-skill) | 同任务、同模型的配对对照，以及匿名评审的组织方式 | 作者的 67 项评测衡量对其规则的遵循程度；不能把所报胜率当作理解效率。其禁用类比、偏好长句等个性化规则不直接采用 |
| [International Plain Language Federation](https://www.iplfederation.org/plain-language/) | 评价读者能否找到、理解、使用需要的信息 | 面向读者的通用原则；不是针对当前模型的实测 |
| [Agrawal & Carpuat, TACL 2024](https://aclanthology.org/2024.tacl-1.24/) | 用阅读理解问题辅助检查改写后的意义保留 | 问题只覆盖部分信息，因此另做完整性检查。英文文本简化研究不能直接证明中文 Agent 表达效果 |

不运行 GPT with Taste 的全量安装器：其默认路径会替换模型指令并涉及全局配置，超过本项目测试范围。采用追加的短规则与可移植 Skill；学术文本继续服从术语、论证和期刊格式要求。

不把去 AI 语气、短句数量、字数减少或模型评分作为成功的替代指标。必要的专业术语和边界说明应保留；改写不能把猜测变成事实，也不能把“本地通过”写成“已上线”。

## 搜索范围与停止理由

先检查用户提供的两个仓库，再按 `plain language skill`、`clear technical communication`、`writing clearly concisely agent skill`、`text simplification meaning preservation reading comprehension`、`Codex project hooks thread/name/set` 等拆分方向检查公开仓库、论文和官方文档。额外检查过的 Strunk 风格写作 Skill 有示例强化原文确定性的风险，未采用其示例作为标准答案。

GitHub 的 `agent session title codex` 和 `plain language skill writing` 组合查询没有返回结果，不能据此认定没有其他方案。已找到可复用机制、能核对的案例和符合约束的接入路径；继续追逐更多榜单或论文不太可能改变首版选择，因此转入实现和小规模验证。

## 验证边界

早期表达对照曾因原生 CLI 认证失败而先使用独立 Agent 会话做行为检查。后来经现有桌面认证桥接完成了本机 CLI 对照，详见下节与验证记录；两阶段的证据保持区分。它与桌面端完整提示词是否完全一致不作假设。匿名比较和材料核对用于找出具体得失，不宣称测得真实用户的阅读时间，也不报告没有人类实验支持的效率百分比。

任何标题 API 实测仅操作为这个项目新建的测试会话。界面刷新需要单独观察；不会用单元测试或 API 响应代替。


## 本机接入补充（早期 0.3.0 联测）

PATH 中的原生 CLI 与桌面环境提供的 `CODEX_CLI_PATH` 在本机不是同一个启动入口。最初直接运行 `codex exec` 返回 401；仅在命令行指定读取文件认证也没有解决嵌套进程的认证问题。进一步查看本机 Harbor 启动代码，发现桌面账户通过 stdio app-server 的现有认证桥接管理，子进程的凭据存储有专门隔离。

采用现成的 `CODEX_CLI_PATH app-server --stdio` 后，`account/read` 确认已有账户，实际模型回合成功完成。最终实现沿用这个入口；不修改 Harbor、不读取或复制令牌、不改全局认证配置。普通环境没有该变量时使用 PATH 的 Codex。协议参考：[Codex app-server](https://learn.chatgpt.com/docs/app-server)。

因此，CLI 可以承载本项目的真实表达对照与 Agent 调用链路测试。但桌面还有自己的标题状态和通知处理：本机代码显示它通过 `thread/name/set` 持久化名称，并处理 `thread/name/updated` 通知。独立 app-server 进程的名称写入没有在测试主连接上产生同样的通知，不能把 API 持久化成功推导成桌面侧栏即时刷新成功。该边界保留在交付说明中。
