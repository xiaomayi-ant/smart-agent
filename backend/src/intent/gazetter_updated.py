import os, csv, argparse, shutil
from collections import defaultdict

MAIN = "geo_dict.csv"
TODO = "gazetteer_todo.csv"
BACKUP = "geo_dict.backup.csv"

def load_main(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows

def write_main(path, rows):
    headers = ["std","aliases","level","code"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        for r in rows:
            w.writerow({
                "std": r.get("std",""),
                "aliases": r.get("aliases",""),
                "level": r.get("level",""),
                "code": r.get("code",""),
            })

def load_todo(path):
    # 列: alias,suggest_std,count,examples
    items = []
    if not os.path.exists(path):
        return items
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            items.append(row)
    return items

def merge_aliases(origin: str, new_alias: str):
    # 去重合并别名字符串（用 | 分隔）
    def split(s):
        return [x.strip() for x in s.split("|") if x.strip()]
    s = set(split(origin) if origin else [])
    for a in split(new_alias):
        s.add(a)
    return "|".join(sorted(s, key=lambda x: (len(x), x)))  # 先短后长便于 AC

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--main", default=MAIN, help="主 gazetteer CSV 路径")
    parser.add_argument("--todo", default=TODO, help="人工审核后的待合并 CSV（已填写 suggest_std）")
    parser.add_argument("--default_level", default="city", help="新标准名默认 level")
    parser.add_argument("--default_code", default="", help="新标准名默认 code")
    args = parser.parse_args()

    main_rows = load_main(args.main)
    todo_rows = load_todo(args.todo)

    # 建索引：std -> row，alias -> std
    by_std = {}
    alias2std = {}
    for r in main_rows:
        std = r.get("std","").strip()
        by_std[std] = r
        aliases = r.get("aliases","")
        for a in [std] + [x.strip() for x in aliases.split("|") if x.strip()]:
            alias2std[a] = std

    updates = 0
    inserts = 0

    for row in todo_rows:
        alias = (row.get("alias") or "").strip()
        std_suggest = (row.get("suggest_std") or "").strip()
        if not alias or not std_suggest:
            continue

        # 建议标准名已存在：把 alias 合并进该 std 的 aliases
        if std_suggest in by_std:
            r = by_std[std_suggest]
            r["aliases"] = merge_aliases(r.get("aliases",""), alias)
            updates += 1
        else:
            # 新增一条标准名记录，并把 alias 放入别名列表
            new_row = {
                "std": std_suggest,
                "aliases": alias,
                "level": args.default_level,
                "code": args.default_code
            }
            main_rows.append(new_row)
            by_std[std_suggest] = new_row
            updates += 1; inserts += 1

    # 备份
    if os.path.exists(args.main):
        shutil.copyfile(args.main, BACKUP)
        print(f"已备份主词库到 {BACKUP}")

    write_main(args.main, main_rows)
    print(f"合并完成：更新/新增 {updates} 条，其中新增标准名 {inserts} 条。")

if __name__ == "__main__":
    main()
