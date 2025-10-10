# intent module

运行时的“意图与槽位抽取”模块，供后续图节点使用；并包含离线维护与评估脚本。

## 文件与用途

- slot_pipeline.py: 运行时入口。输出
  - `slots`: {topic, person, location, date, time, temperature}
  - `analysis.signals`: {has_from_to, has_location, has_datetime, has_topic, has_person}
  - `composed`: 槽位摘要（人类可读）
  - 日志: `logs/np_samples.jsonl`（抽样）、`logs/unresolved.jsonl`（未解）
  - 依赖: hanlp, pyahocorasick, openai
  - 状态: 已使用（将由图入口节点调用）


- geo_dict.csv: 地名词库（std/aliases/level/code）
  - 状态: 已使用（缺失时回退内置词表）

- np_rater.py: 离线一致性评分（默认针对 topic/person）。输入 `logs/np_samples.jsonl`；输出 `logs/np_scores.jsonl`。
  - 用法: `python -m src.intent.np_rater --sample-size 50 --lookback-days 2 --slots topic,person`
  - 状态: 可选工具（离线）

- unresolved_report.py: 聚合 `logs/unresolved.jsonl`，生成：
  - `gazetteer_todo.csv`（待扩充别名）
  - `fewshot_todo.jsonl`（few-shot 标注样本）
  - `summary.txt`（统计摘要）
  - 用法: `python -m src.intent.unresolved_report --use_hanlp`
  - 状态: 可选工具（离线）

- gazetter_updated.py: 将人工修订的 `gazetteer_todo.csv` 合并回 `geo_dict.csv`。
  - 用法: `python -m src.intent.gazetter_updated --main geo_dict.csv --todo gazetteer_todo.csv`
  - 状态: 可选工具（离线）

- config.json: 本模块本地配置（兜底）。在后端 `.env` 已配置的情况下可忽略。
  - 状态: 可选（兜底）

- clues.yaml: 预留线索文件。
  - 状态: 暂未使用

- 后续可以继续考虑few-shot的应用范围，目前只有在gazetter上使用

## 环境与依赖
- 环境变量：`OPENAI_API_KEY`, `OPENAI_BASE_URL`（来自 backend `.env`）
- 依赖（见 `backend/requirements.txt`）：`openai`, `hanlp`, `pyahocorasick`

## 预热与复用
- 进程内单例：由 `src.intent.manager.get_router()` 提供，避免每次请求重新加载模型/AC。
- 启动预热：服务启动时会调用 `manager.warmup()`，首次启动可能较慢（模型下载/加载）。
- 开关与缓存：
  - `INTENT_ENABLED=true|false` 控制是否启用该模块（禁用后图仍可运行）。
  - `HANLP_HOME` 指向持久目录以缓存模型（未设置则默认 `~/.hanlp`）。

## 与图的集成（概览）
- 计划在图入口添加 `intent_slot_detect` 节点，调用 `slot_pipeline.Router.process(text)`。
- `analysis.signals` 用于判断是否调用工具；`slots`/`composed` 注入系统提示，用于引导选择最相关工具及参数。 