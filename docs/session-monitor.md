# 会话切换建议分：安装与使用

`clarity-session-titles` 0.7.0 在原来的三段标题前增加建议分：

```text
S2·73分｜实现中｜修复登录超时｜验证重试逻辑
```

分数范围为 0–100，越高越值得考虑整理交接、换一个新会话继续。它是尚未校准的建议分，不是“模型变笨的概率”，也不保证换会话后效果更好。插件不会替你创建会话或中断任务。

每轮结束时程序更新评分，原来的标题维护继续工作。刚发出新消息时，标题可能仍显示上一轮的结果。关键数据不足时显示 `未评分｜…`，而非 0 分。手动改过的语义段仍会保留；手动改评分前缀会暂停前缀自动更新。

## 安装

需要 Python 3.11+ 和支持模型请求 Hooks 的 Codex。本次目标为 macOS 上的 Codex `0.167.0-alpha.3.2`。插件名称为 `clarity-session-titles`，显示名称为“清晰会话标题”；不需要另装评分插件。

解压本次交付的 0.7.0 安装包，进入包含 `scripts/` 和 `plugins/` 的目录。为尚未安装插件的单个 Codex 账户安装：

```sh
python3 scripts/title_plugin.py install --global
```

已有安装使用 `update --global`。只管理一个 Git 项目时，把 `--global` 换成 `--project /项目绝对路径`。

文件部署后，安装器可能返回 `needs_hook_review`。在同一账户的 Codex CLI 输入 `/hooks`，只审查本插件的七项命令，分布在六类事件中：UserPromptSubmit 一项、Stop 两项，以及 PostModelRequest、PreCompact、PostCompact、PostToolUse 各一项。标题提醒和评分探测提示由同一个 UserPromptSubmit 入口合并输出。不要用信任全部来替代逐项检查。

```sh
python3 scripts/title_plugin.py status --global
```

确认 `runtime_ready: true` 后重新加载客户端。新会话和旧会话续聊都会自动运行，不需要每轮手动触发。插件文件已经安装、Hooks 已受信任和一次真实评分成功，是三项不同的检查。

## 本机已有的跨账户共享安装

本机共享安装更新到 0.7.0 后，需重新核对缓存摘要和新版 Hooks 信任。重新加载 Codex 后即可使用，新会话和旧会话续聊都适用。

如果已有 0.5.0 共享安装，继续更新它的原位置：

```sh
CODEX_HOME="$HOME/Library/Application Support/Agent Clarity/codex" \
  python3 scripts/title_plugin.py update --global --portable
```

各账户继续使用同一个本地市场和共享状态；更新后的 Hooks 需要重新审查。不要在另一个账户目录重新创建一套同名全局安装。

首次创建共享安装时，先建立上述 `codex` 目录，再把命令中的 `update` 换成 `install`。共享安装的 `status` 和 `uninstall` 也使用同样的 `CODEX_HOME` 前缀，指向原安装 home；评分设置可直接用下方 `session_monitor.py` 入口。

新接入的账户可在它自己的终端运行以下命令，再审查本插件的 Hooks。`插件ID` 使用上一步安装输出的 `plugin_id`，本机现有 ID 为 `clarity-session-titles@agent-clarity-global-39e78bde7a2a`。

```sh
codex plugin marketplace add "$HOME/Library/Application Support/Agent Clarity/codex/agent-clarity/.local/agent-clarity/marketplace"
codex plugin add 插件ID
```

包内固定了共享状态位置。共享安装读取、保存的是本插件的计数、数字读数和标题保护记录，不复制登录信息。切换账户后，账户仍需加载该插件；插件不能代替不可用的模型服务。

## 档位、开关与详情

在源码仓库中，通过入口查找已安装的脚本，无须记住缓存路径：

```sh
python3 scripts/session_monitor.py status
python3 scripts/session_monitor.py configure --level S1
python3 scripts/session_monitor.py configure --level S2
python3 scripts/session_monitor.py configure --enabled off
python3 scripts/session_monitor.py configure --enabled on
```

项目安装加上 `--project /项目绝对路径`。关闭评分后，在下一次结束检查时移除程序写入的评分前缀，保留原三段标题。用户手改过的前缀仍受保护。

| 档位 | 当前能力 | 监控新增模型调用 |
| --- | --- | --- |
| S1 | 已观测回合与压缩事件的粗略基线；不能识别单轮内容巨大 | 0 |
| S2（默认） | 输入量占窗口比例为主，辅以回合、压缩、近期明确失败和输入增长 | 0 |
| S3 | 每 3 个根回合探测一次；S2 分数达到 60 且尚未消费阈值时提前探测。当前模型在同一回合提交受限标签，程序把标签转成最多 9 分的正向增量 | 0（不增加模型请求；会增加当前回合少量工作） |
| S4 | 每 5 个根回合探测一次；S2 分数达到 60 且尚未消费阈值时提前探测。除 S3 材料外读取最近最多 3 个根回合的有限摘录和结构化工具结果，增量最多 15 分 | 0（不增加模型请求；会增加当前回合少量工作） |

计数从监控接管后开始，按已观测的根会话提示回合去重，不声称补齐安装前的历史。工具调用和内部子代理不增加这个计数。它是辅助信号，尤其不应把 S1 当成精确的质量判断。

S3/S4 的探测只在满足条件的回合注入一次简短指令；模型必须通过本地 `semantic-submit` 命令提交一个闭集 JSON。程序校验回合、nonce、档位和配置版本，再根据标签、证据强度和不确定性计算分数。模型返回未知、JSON 无效、超时、重复提交或未提交时显示 `未评分`，不会把失败伪装成 S2 分数；非探测回合显示当前确定性的 S2 分数。它是同回合自检，不是独立的事后质量审计。

S4 的原文材料按当前 `CODEX_HOME` 保存，最多三个根回合；共享全局安装的账户之间不共享这些用户/助手摘录。每轮最多保留 900 个字符的用户和助手最终内容、20 条工具状态，以及标题状态和当前进展。工具只保留白名单状态、退出码和错误标记，不保留工具原始输入输出。标题状态只读取本地标题记录；记录过大或经过 `.local` 符号链接时忽略。已确认决定不会被插件凭空生成，只有最终内容中明确写出的决定才会成为模型可见材料。

关闭评分或切换到非 S4 档位会停止新的 S4 采集，并在当前账户的历史锁内清理当前账户的摘录。共享安装不会跨 `CODEX_HOME` 删除其他账户已经保存的旧摘录；如需立即清除所有账户的历史，应分别在各账户执行清理。

详情会给出信号贡献、已知与未知项、窗口来源和最后观测时点。运行在 Codex 会话内时，`status` 使用当前 `CODEX_THREAD_ID` 查看本会话；普通终端没有该变量时只显示安装设置。

如果改名请求超时，程序无法确认它是否还会延迟生效，会保留待确认记录，避免连续写入互相覆盖。这时标题可能暂留旧分数，详情中的 `pending`、`prefix_result` 可用于核对；评分提示与标题写入状态是两件事。

## 实际窗口与参考窗口

本机原生 `PostModelRequest` 提供本次请求的输入 token 数，未提供当前会话的实际窗口上限。按已确认的选择，S2 默认使用模型目录的参考窗口，提示和详情保留来源说明。若希望只接受实际窗口，可改为严格模式；没有可靠上限时显示 `未评分`：

```sh
python3 scripts/session_monitor.py configure --window-mode actual_only
```

切回默认的参考窗口模式：

```sh
python3 scripts/session_monitor.py configure --window-mode reference
```

该模式只匹配本机 `models_cache.json` 中的确切模型 ID，使用 `context_window × effective_context_window_percent / 100`。未知模型、无效元数据或输入量超过参考上限时仍未评分。它不读取 `transcript_path`，不扫描历史聊天。

参考窗口与本机默认设置的实测上限吻合，仍可能不同于某个会话临时覆盖的实际窗口。提示会称为“参考窗口”，详情保留来源和目录版本。自行调整过窗口时，可为具体模型设置参考值：

```sh
python3 scripts/session_monitor.py configure --window-mode reference \
  --context-window gpt-6-luna=258400
```

这里的数字是本机验证值，不能直接当成所有模型或所有配置的上限。目录参考值和手动配置值都不应被解释为精确的实时占用率。

## 分数怎样计算

规则随插件发布在 `session-score-config.json`，当前版本为 `s1s2-v1-uncalibrated`。每项按各自上限截断，再相加取整。

| S2 信号 | 最大贡献 |
| --- | ---: |
| 最近一次有效根请求的输入 token 数 / 有效或选定的参考窗口 | 80 分 |
| 监控接管后的提示回合数，40 轮封顶 | 6 分 |
| 已观测的压缩事件，3 次封顶 | 4 分 |
| 最近 20 个提示回合中明确出现请求或工具失败的不同回合，3 轮封顶 | 5 分 |
| 最近最多 5 个同模型、同窗口的有效输入占比的正增长 | 5 分 |

因此，假设其他项均为 0，7 轮、输入占比 90% 得到 73 分；35 轮、占比 10% 得到 13 分。这是规则演算例子，支持“内容量不能被轮数掩盖”，不证明 73 分就是正确的切换时机。

S1 使用 `75 × min(轮数/40, 1) + 25 × min(压缩次数/3, 1)`，作为简单对照档位。S2 的缺失可选信号不重新分配权重，详情标为未知；输入比例等关键项缺失时整项未评分。取消请求不当作质量失败；明确失败也可能源于网络或环境，因此贡献受限。

压缩开始后旧输入样本失效，压缩过程中请求的输入不计为压缩后压力。收到新的有效根请求后才恢复 S2。模型或窗口改变时清空增长比较样本。跨过当前 60 分候选线或缺失项改变时，Hook 返回简短提示；标题数字仍逐轮维护。60 分是产品规则，尚未校准。标题持久化已经过 CLI/API 核对；桌面警告与侧栏的渲染仍需用户检查。

## 怎样验证

```sh
python3 -m unittest discover -s tests -v
python3 tests/live_plugin_lifecycle.py --execute
python3 tests/live_session_scores.py --execute
```

第一项验证算术、计数、缺失、压缩、并发与标题保护；第二项在无凭据的隔离 home 验证安装生命周期；第三项会消耗当前账户配额，固定使用 `gpt-6-luna` / `low`，只操作脚本新建的测试会话。

这些检查证明采集、规则、受限探测和显示按设计执行。它们不提供质量退化标签，也不证明开启新会话优于继续或压缩。真实执行结果和未通过项见 [验证记录](verification.md)。
