# 首次正式发布验收

2026-10-24，在 Mac ARM64 上完成。应用容器来自 GHCR，模型复用宿主 Ollama 的 `gemma3:1b` 与 `nomic-embed-text`。验收使用仓库专用合成 PDF；既有用户资料、聊天记录和模型未上传。

## 发布证据

- 应用提交：`f2aa2097a52a86b06330837661862223b22822ea`。
- [成功的 main 发布](https://github.com/Odysseus-cyber/Aegis-RAG/actions/runs/40064928889)。
- [含 delivery.json 和部署包的 Release](https://github.com/Odysseus-cyber/Aegis-RAG/releases/tag/sha-f2aa2097a52a86b06330837661862223b22822ea)。
- [PR #1](https://github.com/Odysseus-cyber/Aegis-RAG/pull/1) 与 [PR #2](https://github.com/Odysseus-cyber/Aegis-RAG/pull/2) 的检查和三套双架构构建均通过。
- 三个包均已匿名验证 `linux/amd64`、`linux/arm64` manifest；Mac 实际使用 ARM64 镜像，并核对 OCI 提交标签。

| 镜像 | 发布 digest |
| --- | --- |
| backend | `sha256:9ef2ea834df1ecf82be70c3819debe54e7d5e599a4c8cccddec3aaa8659281c2` |
| frontend | `sha256:9001763578fc09fb4bcc02ef992e8ad54722ee29277f7ad38d5f381359377ffc` |
| drift | `sha256:96431736c7883a801f487dcae0a117e5abbbf71e01a9c0ace253348791849117` |

## 实际功能结果

部署命令对 `aegis-demo.pdf` 连续入库两次，文档和分块数保持不变（1 个文档、1 个分块）。指定该文档完成两轮真实模型问答，检查到 SSE 完成事件、正确来源引用、4 条持久化消息和2条关联到助手消息的反馈。

浏览器另外执行两轮问答和一次反馈，记录到32次消息渲染更新；标题为 Aegis-RAG，输入在回答后恢复。页面版本来自后端 `/version`，可跳转到对应 Actions。

追加下载恢复测试后，本地后端共71项测试通过，前端19项测试、lint和生产构建通过。发布下载曾遇到 TLS EOF，失败返回非零且未写入当前部署记录；部署工具因此增加最多三次的原子下载重试，并复用本地已有 digest 镜像，保留 OCI 校验。

首次 main 的前端任务曾停滞在 amd64 `npm ci`，日志未给出根因，该流水线被后续提交替代。静态前端改用原生 builder 后，双架构镜像任务不足一分钟通过；不能据此断言原停滞由 QEMU 引起。

## 真实质量报告

首次正式部署后，独立漂移容器对2条实际模型回答补算向量并评分。结果来自本机 Gemma rubric，属于模型估计。

| 项目 | 实际结果 |
| --- | --- |
| 忠实度 | 0.875，达到0.7阈值 |
| 回答相关性 | 0.425，低于0.65阈值，告警 |
| 检索、回答向量、长度、反馈漂移 | 历史参考窗口样本不足，明确显示数据不足 |
| 上下文精度 | 无标准答案，明确跳过 |
| 任务整体 | `alert`，退出码1；未触发部署回滚 |

已有 Presidio 策略会把 `quarterly`、`five years` 等时间周期脱敏为 `<DATE_TIME>`，影响答案可读性。该策略本轮保持不变。真实历史基线不足，不能据这次演示判断长期漂移表现。正常、告警、数据不足及执行错误的合成场景只用于监控展示，使用独立 `synthetic_demo` 分组，不写入聊天数据库。

## 复用入口

```sh
make deploy-demo VERSION=f2aa2097a52a86b06330837661862223b22822ea
make verify-demo
make evaluate-demo
make rollback-demo  # 需要已有上一套验证成功的不同版本
```

应用：`http://127.0.0.1:15173`。Grafana：`http://127.0.0.1:13000`，本机演示账号 `admin` / `aegis-local-demo`。原生应用 `5173` 保留。Kubernetes 示例未实际部署。

本机报告与浏览器截图保存在 `.runtime/aegis-release-acceptance/`；运行数据与截图不纳入公开仓库。本文记录首次正式发布的结果，后续升级与回滚记录保存在同一验收目录。
