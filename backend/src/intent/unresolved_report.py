import os, json, csv, argparse, re
from collections import Counter, defaultdict
from pathlib import Path

# 可选：发现 HanLP 则尝试辅助抽取地名
try:
    import hanlp
    _HANLP = hanlp.load('FINE_ELECTRA_SMALL_ZH')
except Exception:
    _HANLP = None

from .config_utils import get_config

base_dir = os.path.dirname(__file__)
CFG = get_config(
    base_dir,
    defaults={
        "LOG_DIR": os.path.join(base_dir, "logs"),
    },
)

LOG_DIR = CFG["LOG_DIR"]
UNRESOLVED = os.path.join(LOG_DIR, "unresolved.jsonl")
OUT_GAZ = "gazetteer_todo.csv"
OUT_FEWSHOT = "fewshot_todo.jsonl"
OUT_SUMMARY = "summary.txt"

def hanlp_guess_location(text: str):
    if not _HANLP:
        return None
    try:
        out = _HANLP(text)
        for span in out.get("ner", []):
            if isinstance(span, dict):
                word = span.get('text')
                label = span.get('type') or span.get('label')
            else:
                word, label = str(span[0]), str(span[-1])
            if label in ("GPE","LOC","LOCATION","ns"):
                return word
    except Exception:
        pass
    return None

def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line=line.strip()
            if not line: 
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=UNRESOLVED, help="输入日志文件 unresolved.jsonl 路径")
    parser.add_argument("--out_gaz", default=OUT_GAZ, help="输出 gazetteer 待办 CSV")
    parser.add_argument("--out_fewshot", default=OUT_FEWSHOT, help="输出 few-shot 待办 JSONL")
    parser.add_argument("--summary", default=OUT_SUMMARY, help="输出统计摘要")
    parser.add_argument("--max_examples", type=int, default=3, help="每个候选保留多少例句")
    parser.add_argument("--use_hanlp", action="store_true", help="缺 location 时尝试 HanLP 抽取")
    args = parser.parse_args()

    Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
    items = list(read_jsonl(args.input))
    if not items:
        print(f"未读取到数据：{args.input}")
        return

    # 统计
    intent_cnt = Counter()
    miss_cnt = Counter()
    # gazetteer 候选：alias -> 示例、计数
    gaz_candidates = defaultdict(lambda: {"count":0,"examples":[]})
    # fewshot 候选
    fewshot_candidates = []

    for it in items:
        text = it.get("text","").strip()
        slots = it.get("slots", {})
        intent = (slots or {}).get("intent") or it.get("intent") or "general"
        intent_cnt[intent] += 1

        missing = it.get("missing") or []
        for m in missing:
            miss_cnt[m] += 1

        # 需要地名兜底的样例：收集 alias 候选
        if "location" in missing:
            alias = None
            if slots and isinstance(slots.get("location"), str):
                alias = slots["location"]
            # 从文本做一次启发式 or HanLP
            if not alias and args.use_hanlp:
                alias = hanlp_guess_location(text)
            # 简单正则一个中文词片
            if not alias:
                m = re.search(r"[一-龥]{2,6}", text)
                alias = m.group(0) if m else None

            if alias:
                cand = gaz_candidates[alias]
                cand["count"] += 1
                if len(cand["examples"]) < args.max_examples:
                    cand["examples"].append(text)

        # few-shot 待办：LLM/规则仍无法完整识别的样例
        fewshot_candidates.append({
            "text": text,
            "current_intent": intent,
            "missing": missing,
            "slots": slots
        })

    # 输出 gazetteer_todo.csv
    with open(args.out_gaz, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["alias","suggest_std","count","examples"])
        # 默认 suggest_std 先留空
        for alias, info in sorted(gaz_candidates.items(), key=lambda kv: kv[1]["count"], reverse=True):
            w.writerow([alias, "", info["count"], " | ".join(info["examples"])])

    # 输出 fewshot_todo.jsonl
    with open(args.out_fewshot, "w", encoding="utf-8") as f:
        for row in fewshot_candidates:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # 摘要
    with open(args.summary, "w", encoding="utf-8") as f:
        f.write("# Unresolved Summary\n")
        f.write(f"Total items: {len(items)}\n\n")
        f.write("## Intent distribution\n")
        for k,v in intent_cnt.most_common():
            f.write(f"- {k}: {v}\n")
        f.write("\n## Missing slot distribution\n")
        for k,v in miss_cnt.most_common():
            f.write(f"- {k}: {v}\n")
        f.write(f"\nGazetteer candidates: {len(gaz_candidates)} (see {args.out_gaz})\n")
        f.write(f"Few-shot candidates: {len(fewshot_candidates)} (see {args.out_fewshot})\n")

    print(f"已生成：{args.out_gaz}, {args.out_fewshot}, {args.summary}")

if __name__ == "__main__":
    main()
