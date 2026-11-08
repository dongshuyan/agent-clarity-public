# Third-party notices

本项目的表达规则参考并改编了 GPT with Taste 和 plain-english 的部分原则。evals/cases-v2.json 的 public-onboarding 原材料复制自 GPT with Taste 的 MIT 公开案例，保留固定版本来源。下列许可保留原文。标题插件复制了 agent-session-titles 的三段解析、保护段选择和合并函数，并改编其手动改名协调逻辑与 Skill 指导；通信代码使用本机 Codex CLI 的官方协议。plain-writing-skill 仅作为评测方法的参考。具体版本见 docs/references.json。

本文件不为本项目的原创部分另行指定开源许可；仓库保持私有。

## gpt-with-taste

MIT License

Copyright (c) 2026 GPT with Taste contributors
Copyright (c) 2026 X-T-E-R (adapted TOML helper)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

Attribution: src/toml-overlay.mjs adapts the lexical scanner and targeted
line-patching approach from nb-codex-main/src/toml-overlay.mjs, distributed
under the MIT License, Copyright (c) 2026 X-T-E-R. No model catalog or other
separately licensed nb-codex assets are included by that adaptation.

## plain-english

MIT License

Copyright (c) 2026 Raqz

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## agent-session-titles

来源：https://github.com/panda-z519/agent-session-titles，固定提交 `2d931a54a736a57c23a3e9a7fcfca56031dfd5f3`。复制内容位于 `plugins/clarity-session-titles/scripts/title_segments.py`；改编逻辑位于同目录 `title_runtime.py`，Skill 位于插件的 `skills/manage-title/`。插件包内也附有独立许可文件。

MIT License

Copyright (c) 2026 panda-z519

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
