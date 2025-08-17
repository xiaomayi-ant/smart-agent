"""
离线评分插件：
- 从 logs/np_samples.jsonl 随机抽样过去N天的样本
- 对指定槽位（默认 topic,person）执行 LLM 一致性评分
- 结果写入 logs/np_scores.jsonl
- 配置来自 config.json + 环境变量（env 覆盖 config）
"""

import os
import sys
import json
import random
import argparse
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from openai import OpenAI
from .config_utils import get_config
from ..core.config import settings


ROOT = os.path.dirname(__file__)
CFG: Dict[str, Any] = get_config(
	ROOT,
	defaults={
		"LOG_LEVEL": "INFO",
		"LOG_DIR": os.path.join(ROOT, "logs"),
		"SAMPLE_SIZE": 50,
		"LOOKBACK_DAYS": 2,
		"DEEPSEEK_MODEL": "deepseek-chat",
		"DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
		"DEEPSEEK_API_KEY": None,
	},
	casters={
		"LOG_LEVEL": lambda v: str(v).upper(),
		"SAMPLE_SIZE": lambda v: int(v),
		"LOOKBACK_DAYS": lambda v: int(v),
	}
)

logging.basicConfig(level=CFG["LOG_LEVEL"], format="%(asctime)s [%(levelname)s] %(message)s")

LOG_DIR = CFG["LOG_DIR"]
SAMPLES_PATH = os.path.join(LOG_DIR, "np_samples.jsonl")
SCORES_PATH = os.path.join(LOG_DIR, "np_scores.jsonl")
os.makedirs(LOG_DIR, exist_ok=True)


def iter_jsonl(path: str) -> Iterable[Dict[str, Any]]:
	if not os.path.exists(path):
		return
	with open(path, "r", encoding="utf-8") as f:
		for line in f:
			line = line.strip()
			if not line:
				continue
			try:
				yield json.loads(line)
			except Exception:
				continue


def read_existing_scores_keyset(path: str) -> Set[Tuple[str, str]]:
	keys: Set[Tuple[str, str]] = set()
	for rec in iter_jsonl(path):
		rid = rec.get("id")
		slot = rec.get("slot")
		if rid and slot:
			keys.add((rid, slot))
	return keys


def within_lookback(ts_str: str, days: int) -> bool:
	try:
		ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
		return ts >= datetime.utcnow() - timedelta(days=days)
	except Exception:
		return False


def rand_sample(items: List[Any], k: int) -> List[Any]:
	if k >= len(items):
		return items
	return random.sample(items, k)


class LLMScorer:
	def __init__(self) -> None:
		self.api_key = os.getenv("OPENAI_API_KEY") or settings.openai_api_key or CFG.get("DEEPSEEK_API_KEY")
		self.model = CFG.get("DEEPSEEK_MODEL", "gpt-4o-mini")
		self.base_url = os.getenv("OPENAI_BASE_URL") or settings.openai_base_url or CFG.get("DEEPSEEK_BASE_URL")
		self.available = bool(self.api_key)
		self.client: Optional[OpenAI] = None
		if self.available:
			self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

		self.system_prompt = (
			"你是一致性评估器。只输出 JSON，不要任何解释。\n"
			"任务：判断候选槽位值与原文语义是否一致或高度相关。\n"
			"输出字段：{\n"
			"  'slot': 'string',\n"
			"  'candidate': 'string',\n"
			"  'score_0_1': 'float in [0,1]',\n"
			"  'label': 'consistent|uncertain|inconsistent'\n"
			"}\n"
		)

	@staticmethod
	def _strip_code_fences(content: str) -> str:
		if not content:
			return content
		if content.startswith("```"):
			lines = content.split("\n")
			json_lines: List[str] = []
			in_json = False
			for line in lines:
				s = line.strip()
				if s.startswith("```json") or s.startswith("```JSON"):
					in_json = True
					continue
				if s == "```":
					break
				if in_json:
					json_lines.append(line)
			return "\n".join(json_lines).strip()
		return content

	def score(self, text: str, slot: str, candidate: str) -> Optional[Dict[str, Any]]:
		if not self.available:
			return None
		try:
			user_prompt = (
				f"原文：\n\"{text}\"\n\n"
				f"候选槽位：\n- slot: \"{slot}\"\n- candidate: \"{candidate}\"\n\n"
				"请按 JSON 返回：{'slot':'...','candidate':'...','score_0_1':0.00-1.00,'label':'consistent|uncertain|inconsistent'}"
			)
			resp = self.client.chat.completions.create(
				model=self.model,
				messages=[
					{"role": "system", "content": self.system_prompt},
					{"role": "user", "content": user_prompt},
				],
				temperature=0.1,
				max_tokens=128,
				timeout=25,
			)
			content = (resp.choices[0].message.content or "").strip()
			content = self._strip_code_fences(content)
			if not content:
				return None
			data = json.loads(content)
			sc = data.get("score_0_1")
			lab = data.get("label")
			if not isinstance(sc, (int, float)) or not (0.0 <= float(sc) <= 1.0):
				return None
			if lab not in ("consistent", "uncertain", "inconsistent"):
				return None
			return data
		except Exception:
			logging.warning("score one failed", exc_info=False)
			return None


def main() -> int:
	parser = argparse.ArgumentParser()
	parser.add_argument("--sample-size", type=int, default=CFG["SAMPLE_SIZE"])
	parser.add_argument("--lookback-days", type=int, default=CFG["LOOKBACK_DAYS"])
	parser.add_argument("--slots", type=str, default="topic,person", help="逗号分隔，例如 topic,person")
	args = parser.parse_args()

	if not os.path.exists(SAMPLES_PATH):
		logging.info("no samples file found, exit")
		return 0

	slots_to_score = [s.strip() for s in args.slots.split(",") if s.strip()]
	exist_keys = read_existing_scores_keyset(SCORES_PATH)

	pool: List[Tuple[Dict[str, Any], str, str]] = []
	for rec in iter_jsonl(SAMPLES_PATH):
		rid = rec.get("id")
		ts = rec.get("ts")
		if not rid or not ts or not within_lookback(ts, args.lookback_days):
			continue
		slots = (rec.get("slots") or {})
		for slot in slots_to_score:
			cand = slots.get(slot)
			if not cand:
				continue
			if (rid, slot) in exist_keys:
				continue
			pool.append((rec, slot, cand))

	if not pool:
		logging.info("no items to score in lookback window, exit")
		return 0

	sample = rand_sample(pool, args.sample_size)

	scorer = LLMScorer()
	if not scorer.available:
		logging.warning("LLM scorer not available (missing API key). nothing to do.")
		return 0

	out_f = open(SCORES_PATH, "a", encoding="utf-8")
	wrote = 0
	try:
		for rec, slot, cand in sample:
			text = rec.get("text") or ""
			rid = rec.get("id") or ""
			ts_src = rec.get("ts") or ""
			data = scorer.score(text, slot, cand)
			if not data:
				continue
			row = {
				"id": rid,
				"source_ts": ts_src,
				"ts_scored": datetime.utcnow().isoformat(),
				"slot": slot,
				"candidate": cand,
				"score_0_1": float(data.get("score_0_1")),
				"label": data.get("label"),
				"model": CFG["DEEPSEEK_MODEL"],
				"prompt_version": "v1",
			}
			out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
			wrote += 1
			if wrote % 10 == 0:
				out_f.flush()
				os.fsync(out_f.fileno())
	finally:
		out_f.close()

	logging.info(f"scored {wrote} items → {SCORES_PATH}")
	return 0


if __name__ == "__main__":
	sys.exit(main()) 