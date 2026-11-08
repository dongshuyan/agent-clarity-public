# Agent Clarity

Agent Clarity 为 Codex 自动维护清晰的会话标题，并用 0–100 的建议分提醒你何时值得整理交接、换一个新的 session 继续工作。

它包含两项核心能力：

1. **三段式会话标题**：`状态｜初始需求｜当前进展`。
2. **会话切换建议分**：在标题前显示 `S1`–`S4` 档位和分数。

评分越高，越值得考虑开一个新 session。这个分数是辅助判断，不是“模型变笨的概率”、回答质量分或经过校准的概率；插件不会自动创建、切换或中断 session。

评分通常在一轮结束后更新；刚发送新消息时，标题可能暂时显示上一轮的分数。S2 达到 60 分是 S3/S4 的提前探测线，不是强制换 session 的阈值。

## 标题怎么看

例如：

```text
S2·41分｜实现中｜修复登录超时｜验证重试逻辑
```

含义如下：

| 部分 | 含义 |
| --- | --- |
| `S2·41分` | 当前使用 S2 规则，建议分为 41；分数越高，越应考虑换 session |
| `实现中` | 当前阶段 |
| `修复登录超时` | 这段对话最初要解决的问题，通常保持稳定 |
| `验证重试逻辑` | 最近完成或正在进行的具体进展 |

不同任务也会使用同一种格式：

```text
S2·18分｜调研中｜比较向量数据库｜筛选官方文档与论文
S3·63分｜方案中｜设计会话交接方案｜整理风险与迁移步骤
未评分｜待确认｜设计会话交接方案｜等待确认风险边界
```

这些是格式示例。`未评分`表示当前缺少可靠数据或语义自检没有提交成功，不等于 0 分。

用户手动修改过的标题段会被保留。评分前缀也是独立的机器字段；如果直接手动修改评分前缀，自动更新评分前缀会暂停，但三段式标题仍可继续维护。

## S1、S2、S3、S4 是什么

四个档位使用同一个 0–100 输出，区别在于读取的数据和是否让当前任务模型做有限的语义自检。

| 档位 | 判断内容 | 模型参与 | 适合场景 |
| --- | --- | --- | --- |
| **S1** | 监控接管后的根回合数、压缩次数；回合最多贡献 75 分，压缩最多贡献 25 分 | 0 次新增模型调用 | 最快的粗略基线 |
| **S2（默认）** | 在 S1 基础上加入最近输入 token 占参考窗口的比例、明确失败事件和输入增长 | 0 次新增模型调用 | 日常使用的默认档位 |
| **S3** | S2 + 连续性风险、重复风险、约束风险；每 3 个根回合探测一次，S2 达到 60 分可提前探测 | 当前任务模型在同一回合提交受限标签；不额外开启模型请求 | 想增加少量语义判断 |
| **S4** | S2 + S3 信号，再读取最近最多 3 个根回合的有限摘录、标题进展和白名单工具状态；每 5 个根回合探测一次，S2 达到 60 分可提前探测 | 当前任务模型在同一回合提交更多受限标签；不额外开启模型请求 | 想让交接风险判断更完整 |

S3/S4 的流程是：当前 Codex 模型正常回答用户，同时在同一回合按提示提交一次结构化 JSON；程序校验标签后计算语义增量。模型不能直接填写数字分数。

- S3 的语义增量最多 9 分。
- S4 的语义增量最多 15 分。
- 模型漏交、超时、返回未知标签或 JSON 无效时，当前探测显示 `未评分`。
- 非探测回合显示最近一次确定性的 S2 分数。
- S3/S4 只读取有上限的材料，不读取完整 transcript；S4 最多保留最近 3 个根回合，每轮用户和助手内容最多 900 个字符。

S1–S4 的回合数从插件开始监控后计算，按根会话提示回合去重；不会声称补齐安装前的历史回合。工具调用和内部子代理不单独增加回合数。

S2 默认使用模型目录中的参考上下文窗口。Codex Hook 当前提供输入 token 数，但不总是提供会话临时使用的实际窗口，因此分数可能是估算值。需要严格模式时，可以改为只接受实际窗口：

```sh
python3 scripts/session_monitor.py configure --window-mode actual_only
python3 scripts/session_monitor.py configure --window-mode reference
```

## 安装

需要 Python 3.11+、Git，以及支持模型请求 Hooks 的 Codex。脚本按 macOS/Linux 设计；当前真实联测在 macOS，Linux 尚未做完整实机联测，Windows 尚未验证。

```sh
git clone https://github.com/dongshuyan/agent-clarity-public.git
cd agent-clarity
```

### 安装到当前 Codex 账户

```sh
python3 scripts/title_plugin.py install --global
```

### 只安装到一个 Git 项目

```sh
python3 scripts/title_plugin.py install --project /absolute/path/to/project
```

`--global` 和 `--project` 只能选一个。当前账户的全局安装覆盖该账户中新建和继续的会话；项目安装只覆盖指定项目范围。

### 供多个 Codex/Harbor 账户共用

如果需要在多个 `CODEX_HOME` 之间保持同一套插件状态，把共享安装放在稳定的本地目录，并使用 `--portable`：

```sh
SHARED_CODEX_HOME="/path/to/stable/agent-clarity-codex-home"
mkdir -p "$SHARED_CODEX_HOME"
CODEX_HOME="$SHARED_CODEX_HOME" \
  python3 scripts/title_plugin.py install --global --portable
```

然后让其他账户加载安装输出的本地插件市场，并在各账户的 Codex CLI 中审查本插件的 Hooks。共享安装不会复制登录信息，也不能代替模型服务。

新账户可以使用安装输出中的 `plugin_id` 加载市场：

```sh
codex plugin marketplace add "$SHARED_CODEX_HOME/agent-clarity/.local/agent-clarity/marketplace"
codex plugin add <plugin_id>
```

安装器可能返回 `needs_hook_review`。这表示文件已部署，但 Codex 尚未允许执行 Hook。请在**同一账户**启动 Codex，输入 `/hooks`，只审查并信任本次安装的 `clarity-session-titles@...` 七项命令，不要信任全部插件。然后检查：

```sh
python3 scripts/title_plugin.py status --global
```

看到 `runtime_ready: true` 且七项 Hook 都是 `trusted` 后，重新加载 Codex。新 session 和旧 session 续聊都会自动运行，不需要每轮手动触发。

## 日常使用

安装完成后，标题和评分会自动维护。查看当前安装和本会话读数：

```sh
python3 scripts/session_monitor.py status
```

切换评分档位：

```sh
python3 scripts/session_monitor.py configure --level S1
python3 scripts/session_monitor.py configure --level S2
python3 scripts/session_monitor.py configure --level S3
python3 scripts/session_monitor.py configure --level S4
```

关闭或重新开启评分：

```sh
python3 scripts/session_monitor.py configure --enabled off
python3 scripts/session_monitor.py configure --enabled on
```

关闭评分会移除插件写入的评分前缀，并保留原来的三段式标题。标题维护和评分是同一个插件中的两个适配器；关闭评分不会关闭标题自动维护。

更新或卸载插件：

```sh
python3 scripts/title_plugin.py update --global
python3 scripts/title_plugin.py uninstall --global
```

项目安装时，把每条命令中的 `--global` 换成 `--project /absolute/path/to/project`。

## 数据范围与限制

- S1/S2 主要读取 Hook 提供的结构化事件和 token 数，不扫描完整历史对话。
- S4 的用户/助手摘录保存在当前 `CODEX_HOME`，账户之间不会共享原文。
- 评分尚未用大量真实任务做校准，适合观察趋势，不应当作严格阈值。
- 桌面侧栏的视觉刷新和“换 session 后是否一定改善质量”尚未作为产品效果完成独立实验。

## 开发与验证

运行单元测试：

```sh
python3 -m unittest discover -s tests -v
```

真实评分联测会消耗当前账户额度，并固定使用 `gpt-6-luna / low`：

```sh
python3 tests/live_session_scores.py --execute
```

实现细节、完整配置、验证记录和已知边界见：[评分使用说明](docs/session-monitor.md)、[验证记录](docs/verification.md)。

仓库还提供独立的 `clear-communication` Skill，用于组织清晰的解释和文档；它不参与标题或评分运行时。

## 许可证与来源

标题解析和分段保护参考了 [agent-session-titles](https://github.com/panda-z519/agent-session-titles)，许可证见 [第三方声明](THIRD_PARTY_NOTICES.md)。
