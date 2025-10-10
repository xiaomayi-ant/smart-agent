"""
NP 组块抽取 + 最小正则 + Gazetteer 标准化 + 受约束 LLM 回补
- 仅使用 config.json + 环境变量，env 覆盖 config
- 产出结构化 slots；必要时调用 LLM 仅补齐缺失槽位
- 将 NP 结果样本落盘（原文、输出、时间戳），用于离线 LLM 评分插件
"""

import os
import re
import csv
import json
import time
import hashlib
import logging
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

from openai import OpenAI
import hanlp
import ahocorasick
from .config_utils import get_config, parse_bool
from ..core.config import settings


# 替换本地 load_config：统一由 config_utils 提供
base_dir = os.path.dirname(__file__)
CFG: Dict[str, Any] = get_config(
	base_dir,
	defaults={
		"LOG_LEVEL": "INFO",
		"LOG_DIR": os.path.join(base_dir, "logs"),
		"ENABLE_NP_SAMPLING": True,
		"DEEPSEEK_MODEL": "deepseek-chat",
		"DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
		"DEEPSEEK_API_KEY": None,
	},
	casters={
		"LOG_LEVEL": lambda v: str(v).upper(),
		"ENABLE_NP_SAMPLING": parse_bool,
	}
)

logging.basicConfig(level=CFG["LOG_LEVEL"], format="%(asctime)s [%(levelname)s] %(message)s")

LOG_DIR = CFG["LOG_DIR"]
UNRESOLVED_PATH = os.path.join(LOG_DIR, "unresolved.jsonl")
NP_SAMPLES_PATH = os.path.join(LOG_DIR, "np_samples.jsonl")
os.makedirs(LOG_DIR, exist_ok=True)


def append_jsonl(path: str, obj: Dict[str, Any]) -> None:
	with open(path, "a", encoding="utf-8") as f:
		f.write(json.dumps(obj, ensure_ascii=False) + "\n")


class Gazetteer:
	def __init__(self, path: str = os.path.join(os.path.dirname(__file__), "geo_dict.csv")):
		self.path = path
		self.alias2std: Dict[str, str] = {}
		self.gaz: Dict[str, Dict[str, Any]] = {}
		self.automaton = None
		self._load()

	def _load(self) -> None:
		if os.path.exists(self.path):
			try:
				with open(self.path, newline='', encoding='utf-8') as f:
					reader = csv.DictReader(f)
					for row in reader:
						std = (row.get("std") or "").strip()
						aliases = (row.get("aliases") or "").strip().split("|") if row.get("aliases") else []
						self.gaz[std] = {
							"std": std,
							"aliases": aliases,
							"level": row.get("level", ""),
							"code": row.get("code", ""),
						}
						for a in [std] + aliases:
							if a:
								self.alias2std[a] = std
				logging.info(f"Loaded gazetteer from {self.path}, {len(self.gaz)} entries.")
			except Exception:
				logging.exception("Failed to load gazetteer CSV")
				self._load_builtin()
		else:
			self._load_builtin()

		try:
			A = ahocorasick.Automaton()
			for alias, std in self.alias2std.items():
				if alias:
					A.add_word(alias, (alias, std))
			A.make_automaton()
			self.automaton = A
			logging.info("Aho-Corasick automaton built.")
		except Exception:
			logging.exception("AC build failed")
			self.automaton = None

	def _load_builtin(self) -> None:
		base = {
			"北京市": {"aliases": ["北京", "帝都", "BJ"], "level": "province", "code": "110000"},
			"上海市": {"aliases": ["上海", "SH"], "level": "province", "code": "310000"},
			"深圳市": {"aliases": ["深圳", "鹏城", "SZ"], "level": "city", "code": "440300"},
			"广州市": {"aliases": ["广州", "GZ"], "level": "city", "code": "440100"},
		}
		for std, meta in base.items():
			self.gaz[std] = {"std": std, **meta}
			for a in [std] + meta["aliases"]:
				self.alias2std[a] = std
		logging.info(f"Loaded built-in gazetteer, {len(self.gaz)} entries.")

	def normalize(self, name: Optional[str]) -> Optional[str]:
		if not name:
			return name
		return self.alias2std.get(name, name)

	def match(self, text: str) -> Optional[str]:
		if self.automaton:
			try:
				hits = []
				for _, val in self.automaton.iter(text):
					alias, std = val
					hits.append((alias, std))
				hits.sort(key=lambda x: len(x[0]), reverse=True)
				return hits[0][1] if hits else None
			except Exception:
				logging.exception("AC match failed")
		try:
			for alias, std in self.alias2std.items():
				if alias and alias in text:
					return std
		except Exception:
			logging.exception("Substring match failed")
		return None


class NPPhraseExtractor:
	def __init__(self) -> None:
		self.tok = hanlp.load(hanlp.pretrained.tok.FINE_ELECTRA_SMALL_ZH)
		self.pos_tagger = hanlp.load(hanlp.pretrained.pos.CTB9_POS_ELECTRA_SMALL)
		self.pos_ok = True

	def analyze(self, text: str) -> Dict[str, Any]:
		res = {"tokens": [], "pos": [], "np_chunks": []}
		try:
			tokens: List[str] = self.tok(text)
			res["tokens"] = tokens
			if self.pos_ok and tokens:
				tags: List[str] = self.pos_tagger(tokens)
				res["pos"] = tags
				res["np_chunks"] = self._chunk_np(tokens, tags)
		except Exception:
			logging.exception("NPPhraseExtractor analyze failed")
		return res

	def _chunk_np(self, tokens: List[str], tags: List[str]) -> List[Dict[str, Any]]:
		n = len(tokens)
		chunks: List[Dict[str, Any]] = []
		i = 0
		while i < n:
			if tags[i] in ("NN", "NR"):
				start = i
				head = i
				j = i - 1
				while j >= 0 and (tags[j] in ("JJ", "NN", "NR") or (j - 1 >= 0 and tags[j - 1] == "CD" and tags[j] == "M")):
					start = j - 1 if (j - 1 >= 0 and tags[j - 1] == "CD" and tags[j] == "M") else j
					j = start - 1
				end = i + 1
				while end < n and tags[end] in ("NN", "NR"):
					end += 1
				chunks.append({
					"start": start,
					"end": end,
					"text": "".join(tokens[start:end]),
					"head": head,
				})
				i = end
				continue
			i += 1

		for k in range(1, n - 1):
			if tokens[k] == "的" and tags[k] in ("DEC", "DEG", "DEV") and tags[k + 1] in ("NN", "NR"):
				left_np = self._find_np_ending_at(chunks, k)
				right_np = self._find_np_starting_at(chunks, k + 1)
				if left_np and right_np:
					fused = {
						"start": left_np["start"],
						"end": right_np["end"],
						"text": "".join(tokens[left_np["start"]: right_np["end"]]),
						"head": right_np["head"],
					}
					chunks.append(fused)

		uniq = {(c["start"], c["end"]): c for c in chunks}
		chunks = list(uniq.values())
		chunks.sort(key=lambda x: (x["start"], x["end"]))
		return chunks

	@staticmethod
	def _find_np_ending_at(chunks: List[Dict[str, Any]], idx: int) -> Optional[Dict[str, Any]]:
		cands = [c for c in chunks if c["end"] == idx]
		if not cands:
			return None
		return max(cands, key=lambda c: c["end"] - c["start"]) 

	@staticmethod
	def _find_np_starting_at(chunks: List[Dict[str, Any]], idx: int) -> Optional[Dict[str, Any]]:
		cands = [c for c in chunks if c["start"] == idx]
		if not cands:
			return None
		return max(cands, key=lambda c: c["end"] - c["start"]) 

	@staticmethod
	def extract_person(tokens: List[str], tags: List[str]) -> Optional[str]:
		n = len(tokens)
		i = 0
		while i < n:
			if tags[i] == "NR":
				j = i + 1
				while j < n and tags[j] == "NR":
					j += 1
				person = "".join(tokens[i:j])
				if person:
					return person
				i = j
				continue
			i += 1
		for t, p in zip(tokens, tags):
			if p == "PN":
				return t
		return None

	@staticmethod
	def choose_topic(tokens: List[str], tags: List[str], np_chunks: List[Dict[str, Any]]) -> Optional[str]:
		for k, t in enumerate(tokens):
			if t == "关于":
				for c in np_chunks:
					if c["start"] >= k + 1:
						if c["end"] - c["start"] >= 1 and len(c["text"]) >= 2:
							return c["text"]
						break
		for k, t in enumerate(tokens):
			if t == "的" and tags[k] in ("DEC", "DEG", "DEV"):
				left = [c for c in np_chunks if c["end"] == k]
				right = [c for c in np_chunks if c["start"] == k + 1]
				if left and right:
					right_np = max(right, key=lambda c: c["end"] - c["start"])
					if len(right_np["text"]) >= 2:
						return right_np["text"]
		for c in np_chunks:
			if len(c["text"]) >= 2 and c["end"] - c["start"] >= 1:
				return c["text"]
		return None


class RegexExtractor:
	DATE = re.compile(r"(今天|明天|后天|\d{1,2}月\d{1,2}日|\d{4}年\d{1,2}月\d{1,2}日)")
	TIME = re.compile(r"(\d{1,2}点半?|\d{1,2}:\d{2})")
	TEMP = re.compile(r"-?\d+\s?(?:°[CF]|摄氏度)")

	def extract(self, text: str) -> Dict[str, Any]:
		res = {"date": None, "time": None, "temperature": None}
		try:
			m = self.DATE.search(text)
			if m:
				res["date"] = m.group(0)
			m = self.TIME.search(text)
			if m:
				res["time"] = m.group(0)
			m = self.TEMP.search(text)
			if m:
				res["temperature"] = m.group(0).replace("摄氏度", "°C")
		except Exception:
			logging.exception("Regex extraction failed")
		return res


class LLMBackfill:
	def __init__(self) -> None:
		self.api_key = os.getenv("OPENAI_API_KEY") or settings.openai_api_key or CFG.get("DEEPSEEK_API_KEY")
		self.model = CFG.get("DEEPSEEK_MODEL", "gpt-4o-mini")
		self.base_url = os.getenv("OPENAI_BASE_URL") or settings.openai_base_url or CFG.get("DEEPSEEK_BASE_URL")
		self.available = bool(self.api_key)
		self.client: Optional[OpenAI] = None
		if self.available:
			self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

		self.system_prompt = (
			"你是信息抽取器。只输出 JSON，不要任何解释。\n"
			"仅补齐用户指定的 slots 字段，其他不要返回。\n"
			"JSON Schema:\n"
			"{\n"
			'  "slots": {\n'
			'    "topic": "string|null",\n'
			'    "person": "string|null",\n'
			'    "location": "string|null",\n'
			'    "date": "string|null",\n'
			'    "time": "string|null"\n'
			"  }\n"
			"}\n"
			"约束：若无法确定请填 null；topic 应为 2-12 字的名词短语，不包含时间/地名/代词/虚词结尾；禁止输出 JSON 以外内容。"
		)

	@staticmethod
	def _strip_code_fences(content: str) -> str:
		if not content:
			return content
		if content.startswith('```'):
			lines = content.split('\n')
			json_lines: List[str] = []
			in_json = False
			for line in lines:
				s = line.strip()
				if s.startswith('```json') or s.startswith('```JSON'):
					in_json = True
					continue
				if s == '```':
					break
				if in_json:
					json_lines.append(line)
			return '\n'.join(json_lines).strip()
		return content

	def extract(self, text: str, needed: List[str]) -> Dict[str, Any]:
		result: Dict[str, Any] = {}
		if not self.available or not needed:
			return result
		try:
			user_prompt = f'文本："{text}"\n需要补齐的槽位: {needed}\n请按 Schema 抽取并返回 JSON。'
			resp = self.client.chat.completions.create(
				model=self.model,
				messages=[
					{"role": "system", "content": self.system_prompt},
					{"role": "user", "content": user_prompt},
				],
				temperature=0.1,
				max_tokens=256,
				timeout=30,
			)
			content = (resp.choices[0].message.content or "").strip()
			content = self._strip_code_fences(content)
			if not content:
				return result
			data = json.loads(content)
			slots = data.get("slots", {})
			for k in needed:
				v = slots.get(k)
				if v is not None:
					result[k] = v
		except Exception:
			logging.exception("LLM backfill failed")
		return result


class Router:
	def __init__(self) -> None:
		self.gaz = Gazetteer()
		self.np = NPPhraseExtractor()
		self.regex = RegexExtractor()
		self.llm = LLMBackfill()
		self.enable_sampling = CFG["ENABLE_NP_SAMPLING"]

	@staticmethod
	def _signals(text: str, slots: Dict[str, Any]) -> Dict[str, bool]:
		t = text or ""
		has_from_to = ("从" in t or "自" in t) and ("到" in t or "至" in t)
		has_location = bool(slots.get("location"))
		has_datetime = bool(slots.get("date") or slots.get("time"))
		has_topic = bool(slots.get("topic"))
		has_person = bool(slots.get("person"))
		return {
			"has_from_to": has_from_to,
			"has_location": has_location,
			"has_datetime": has_datetime,
			"has_topic": has_topic,
			"has_person": has_person,
		}

	@staticmethod
	def _compose(slots: Dict[str, Any]) -> str:
		location = slots.get("location") or ""
		date = slots.get("date") or ""
		time_s = slots.get("time") or ""
		temp = slots.get("temperature") or ""
		topic = slots.get("topic") or ""
		person = slots.get("person") or ""
		parts: List[str] = []
		if person:
			parts.append(f"角色：{person}")
		if topic:
			parts.append(f"主题：{topic}")
		if location:
			parts.append(f"地点：{location}")
		if date or time_s:
			parts.append("时间：" + " ".join([x for x in [date, time_s] if x]))
		if temp:
			parts.append(f"温度：{temp}")
		return "；".join(parts) or "未抽取到有效槽位"

	@staticmethod
	def _gen_sample_id(text: str, ts: str) -> str:
		h = hashlib.sha1()
		h.update((text + "|" + ts).encode("utf-8"))
		return h.hexdigest()

	def _missing(self, slots: Dict[str, Any]) -> List[str]:
		need: List[str] = []
		for k in ("topic", "person", "location", "date", "time"):
			if not slots.get(k):
				need.append(k)
		return need

	def _persist_np_sample(self, text: str, tokens: List[str], tags: List[str], np_chunks: List[Dict[str, Any]], slots: Dict[str, Any]) -> None:
		if not self.enable_sampling:
			return
		try:
			ts = datetime.utcnow().isoformat()
			sample = {
				"id": self._gen_sample_id(text, ts),
				"ts": ts,
				"text": text,
				"tokens": tokens,
				"pos": tags,
				"np_chunks": np_chunks,
				"slots": slots,
				"router": "slot",
				"version": "2025-08-17",
			}
			append_jsonl(NP_SAMPLES_PATH, sample)
		except Exception:
			logging.exception("persist np sample failed")

	def process(self, text: str) -> Dict[str, Any]:
		t0 = time.time()
		trace: Dict[str, Any] = {"stage": [], "errors": []}
		slots: Dict[str, Any] = {}

		try:
			# A. Gazetteer 地点
			loc = self.gaz.match(text)
			if loc:
				slots["location"] = self.gaz.normalize(loc)

			# B. 正则 日期/时间/温度
			rx = self.regex.extract(text)
			for k, v in rx.items():
				if v:
					slots[k] = v

			# C. HanLP NP 组块、人物/主题
			np_res = self.np.analyze(text)
			tokens: List[str] = np_res.get("tokens") or []
			tags: List[str] = np_res.get("pos") or []
			np_chunks: List[Dict[str, Any]] = np_res.get("np_chunks") or []

			if tokens and tags:
				if not slots.get("person"):
					person = NPPhraseExtractor.extract_person(tokens, tags)
					if person:
						slots["person"] = person
				if not slots.get("topic"):
					topic = NPPhraseExtractor.choose_topic(tokens, tags, np_chunks)
					if topic:
						slots["topic"] = topic

			# 样本落盘
			self._persist_np_sample(text, tokens, tags, np_chunks, dict(slots))

			trace["stage"].append("rules_done")

			# D. LLM 兜底（仅补齐缺失，不分类）
			need = self._missing(slots)
			if need:
				back = self.llm.extract(text, need)
				for k, v in back.items():
					if v and not slots.get(k):
						if k == "location":
							v = self.gaz.normalize(v)
						slots[k] = v
				trace["stage"].append({"llm_fallback_for": need})

			# E. 输出 signals / composed
			analysis = {
				"signals": self._signals(text, slots),
				"np_chunks": np_chunks,
			}
			composed = self._compose(slots)

			trace["latency_ms"] = int((time.time() - t0) * 1000)
			result = {
				"slots": slots,
				"analysis": analysis,
				"composed": composed,
				"_trace": trace,
			}

			# F. 若仍缺核心槽位，记未解
			if not any([slots.get("topic"), slots.get("person"), slots.get("location")]):
				append_jsonl(UNRESOLVED_PATH, {
					"ts": datetime.utcnow().isoformat(),
					"text": text,
					"slots": slots,
					"trace": trace,
				})

			return result

		except Exception as e:
			tb = str(e)
			trace["errors"].append(tb)
			append_jsonl(UNRESOLVED_PATH, {
				"ts": datetime.utcnow().isoformat(),
				"text": text,
				"error": tb,
				"trace": trace,
			})
			return {"slots": {}, "analysis": {"signals": {}}, "composed": "", "_trace": trace}


if __name__ == "__main__":
	router = Router()
	samples = [
		"告诉我北京今天的天气",
		"勇敢的宇航员在太空冒险，并且降落在北京。",
		"帮我订后天10:30从北京到上海的高铁",
		"帝都明天热不热？",
		"明早八点从BJ到深圳的机票",
		"写一个关于宇宙探险的故事，主角是小王",
		"上海今天",
	]
	for s in samples:
		print("\nQ:", s)
		out = router.process(s)
		print(json.dumps(out, ensure_ascii=False, indent=2))
	print(f"\n日志（未解）：{UNRESOLVED_PATH}")
	print(f"样本（NP）：{NP_SAMPLES_PATH}") 