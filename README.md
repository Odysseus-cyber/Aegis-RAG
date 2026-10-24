# Aegis-RAG

[![CI and Delivery](https://github.com/Odysseus-cyber/Aegis-RAG/actions/workflows/delivery.yml/badge.svg)](https://github.com/Odysseus-cyber/Aegis-RAG/actions/workflows/delivery.yml)

Aegis-RAG 是一个本地 PDF 问答应用：选择文档、多轮流式回答、引用、脱敏、反馈以及可观察的模型评估。使用 React、FastAPI、Ollama 和 ChromaDB，默认模型是 `gemma3:1b` 与 `nomic-embed-text`。

基于 [ComplianceCheckRAG](https://github.com/jingyiyanlol/ComplianceCheckRAG) 改造，保留原项目来源与贡献者署名。原源码未附许可证，本次改名不新增许可声明。完整说明见 [架构与功能](README_1.md)。

## 本机开发

需要 Python 3.11、Node 24、Docker Desktop（仅容器演示需要）和 Ollama。这台 Mac 已在 `.runtime/` 准备独立 Python/Node，Makefile 自动使用；新机器可使用系统安装的对应版本。

```sh
make setup
ollama pull gemma3:1b
ollama pull nomic-embed-text
make doctor
make ingest        # data/ 中的有文本层 PDF；不包含 OCR
```

在两个终端分别运行 `make backend` 和 `make frontend`，访问 **http://127.0.0.1:5173**。后端接口文档：**http://127.0.0.1:8000/docs**。页面底部显示部署版本，本机开发显示 `local`；`GET /version` 返回应用名、提交、构建时间与 Actions 链接。

`.env.example` 为配置模板。`make setup` 不清空已有环境，未处于 Git 仓库时跳过 hooks。已有 PDF、`.chroma/`、`telemetry.db` 和浏览器历史均保留；正常启动不要执行清理命令。已有索引要求 ChromaDB 1.5.9，不应降级到 1.0.7。

## CI、发布与本机容器演示

[GitHub Actions](https://github.com/Odysseus-cyber/Aegis-RAG/actions) 在 PR、main 推送与手动触发时运行 Python/前端测试、lint、构建、工作流与配置检查。前后端及漂移任务均构建 `linux/amd64` 和 `linux/arm64` 镜像。仅 main 全部通过后发布三套 GHCR 镜像，并创建 `sha-<完整提交SHA>` GitHub Release，附精确 digest 的 `delivery.json` 与部署包。

```sh
make deploy-demo VERSION=<成功发布的40位提交SHA>
make verify-demo
make evaluate-demo
make rollback-demo
```

发布脚本使用同一清单中的三个镜像，不在本机重建源码；部署前检查 OCI 提交信息与容器到 Ollama 的连接。部署前会验证 GHCR 下载权限；本仓库已发布的镜像支持匿名拉取。如果在其他仓库首次发布时包默认为私有，需将三个包设为公开，或使用用户自行配置的 Docker 登录。

- 应用：**http://127.0.0.1:15173**
- Grafana：**http://127.0.0.1:13000**，本机演示账号 `admin`，密码 `aegis-local-demo`
- Prometheus：**http://127.0.0.1:19090**
- 后端：`127.0.0.1:18000`；ChromaDB：`127.0.0.1:18001`；Pushgateway：`127.0.0.1:19091`

全部端口仅监听本机。前后端与 ChromaDB 使用容器；模型复用宿主 Ollama。资料、数据库和报告位于 `.runtime/aegis-demo/`，独立于开发环境；验收使用仓库附带的合成 PDF，不上传已有用户 PDF 或聊天记录。

功能验收包括重复入库数量不变、两轮指定文档 SSE、引用、消息保存与即时反馈关联。成功后才记录当前版本，保留上一不同版本用于回滚；首次失败明确退出，已有版本失败则尝试恢复。模型质量告警只报告，不触发自动回滚。详见 [交付流程](docs/workflow-summary.md) 与 [部署说明](docs/deployment.md)。

## 监控与质量评估

模型评估由独立漂移任务执行，结果包含 `passed`、`alert`、`insufficient_data` 或 `error`，退出码依次为 `0`、`1`、`0`、`2`。基线冻结为当前 24 小时之前的 7 天样本；不足 10 条有效统计样本不会被当作正常。

统计检测使用 SciPy/NumPy；质量评分使用本机 Gemma 的 JSON schema 约束 rubric，属于模型估计，不声称是 DeepEval 指标。任务使用保存的脱敏检索原文，补算脱敏回答的向量；无可恢复原文时跳过。上下文精度仅用于带参考答案的评估数据。

```sh
# 已部署演示环境的真实评估
make evaluate-demo

# 原生环境手动评估；报告和基线默认不纳入 Git
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python -m monitoring.drift_job.run_drift --trigger adhoc --report reports/drift.json
.venv/bin/python -m monitoring.drift_job.snapshot --pipeline-version <SHA>

# 独立的合成告警展示；不读取或修改真实聊天数据库
PUSHGATEWAY_URL=http://127.0.0.1:19091 .venv/bin/python -m monitoring.drift_job.demo --scenario alert --output reports/demo-alert.json
```

Grafana 的 **Aegis-RAG · Model Quality** 面板按 `real` 和 `synthetic_demo` 区分来源。`passed`、`alert`、`insufficient_data`、`error` 四个合成场景仅验证展示和告警链路，不是模型实验结果。正常、失败及数据不足使用独立状态，旧指标被替换，不会把缺失值显示为零分。详见 [监控说明](docs/monitoring.md)。

## 检查与兼容性

```sh
make test-local
make lint
PATH="$PWD/.runtime/node/bin:$PATH" npm --prefix frontend test
PATH="$PWD/.runtime/node/bin:$PATH" npm --prefix frontend run lint
PATH="$PWD/.runtime/node/bin:$PATH" npm --prefix frontend run build
docker compose -f docker-compose.release.yml config --quiet
```

测试使用临时数据库，常规 CI 不需要真实模型。真实模型演示、容器构建、远程 Actions 与 GHCR 拉取是不同验收阶段，必须分别验证。Kubernetes 示例仅同步名称与配置，本轮不作为已验收部署方式。

改名保留 `ccrag_*` 指标、既有 localStorage 键、`compliance_docs` 集合及数据库表结构。前端 parser 6.1.5 已包含官方安全回补；此前 `npm audit` 的版本范围仍报告三项中等告警，未通过忽略规则隐藏。

本机运行环境、原项目修复前源码及索引备份均保存在被 Git 排除的 `.runtime/`。所有构建日志、截图、运行报告保存在 `.runtime/aegis-acceptance/`，不随公开源码上传。
