#!/usr/bin/env python3
"""
analyze.py — 伙伴云工作区表结构数据拉取工具

分三阶段执行：
  Phase 1  拉取表格列表
  Phase 2  并发拉取每张表的字段配置
  Phase 3  清洗数据（过滤引用字段、提取字段属性）

进度 → stderr
结果 → stdout（JSON 格式，供 Claude 做 AI 分析）

用法：
  python analyze.py                              # 读凭据文件
  python analyze.py --space-id X --api-key Y    # 临时传入
  python analyze.py > data.json                  # 保存原始数据
"""

import json
import sys
import argparse
import urllib.request
import urllib.error
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# ─── 配置 ──────────────────────────────────────────────────────────────────────

SKILL_DIR        = Path(__file__).parent
CREDENTIALS_FILE = SKILL_DIR / ".credentials.json"
BASE_URL         = "https://api.huoban.com"
CONCURRENCY      = 8
TIMEOUT          = 20

FIELD_TYPE_LABELS = {
    "input":       "文本",
    "numeric":     "数字",
    "date":        "日期",
    "category":    "选项",
    "relation":    "关联",
    "user":        "成员",
    "file":        "附件",
    "image":       "图片",
    "calculation": "计算",
    "auto_number": "自增编号",
    "formula":     "公式",
    "text":        "多行文本",
    "textarea":    "多行文本",
    "money":       "金额",
    "rich":        "富文本",
    "bool":        "开关",
    "phone":       "电话",
    "email":       "邮箱",
    "url":         "链接",
    "location":    "地址",
    "checkbox":    "复选框",
    "rating":      "评分",
}

# ─── 凭据 ──────────────────────────────────────────────────────────────────────

def load_credentials(args):
    if args.space_id and args.api_key:
        return args.space_id, args.api_key

    if not CREDENTIALS_FILE.exists():
        err("未找到凭据文件，请创建：\n"
            f"  {CREDENTIALS_FILE}\n\n"
            "格式：\n"
            '  { "space_id": "...", "api_key": "..." }\n\n'
            "或通过命令行参数传入：\n"
            "  python analyze.py --space-id ... --api-key ...")
        sys.exit(1)

    with open(CREDENTIALS_FILE, encoding="utf-8") as f:
        creds = json.load(f)

    space_id = args.space_id or creds.get("space_id", "")
    api_key  = args.api_key  or creds.get("api_key", "")

    if not space_id or not api_key:
        err("凭据文件中缺少 space_id 或 api_key")
        sys.exit(1)

    return space_id, api_key

# ─── 工具 ──────────────────────────────────────────────────────────────────────

def err(msg):
    print(f"[ERROR] {msg}", file=sys.stderr)

def log(msg):
    print(msg, file=sys.stderr)

def api_post(path, body, api_key):
    url     = f"{BASE_URL}{path}"
    payload = json.dumps(body).encode()
    headers = {
        "Content-Type":       "application/json",
        "Open-Authorization": f"Bearer {api_key}",
    }
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode()
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {body_text}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"网络错误: {e.reason}") from e

    result = json.loads(raw)
    if result.get("code") != 0:
        raise RuntimeError(f"API code={result.get('code')}: {result.get('message', '未知')}")
    return result.get("data", {})

# ─── Phase 1：拉取表格列表 ─────────────────────────────────────────────────────

def phase1_fetch_tables(space_id, api_key):
    log("\n━━━ Phase 1/3  拉取表格列表 ━━━")
    data = api_post("/openapi/v1/table/list", {"space_id": space_id}, api_key)
    tables = data.get("tables", [])
    log(f"  发现 {len(tables)} 张表")
    return tables

# ─── Phase 2：并发拉取字段配置 ────────────────────────────────────────────────

def fetch_one_config(table, api_key):
    data = api_post(f"/openapi/v1/table/{table['table_id']}", {}, api_key)
    return data.get("table", {})

def phase2_fetch_configs(tables, api_key):
    log(f"\n━━━ Phase 2/3  拉取字段配置（{CONCURRENCY} 线程并发） ━━━")
    configs, errors = [], []
    total = len(tables)
    done  = 0

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        futures = {ex.submit(fetch_one_config, t, api_key): t for t in tables}
        for future in as_completed(futures):
            t    = futures[future]
            done += 1
            name = t.get("name", t["table_id"])
            try:
                cfg = future.result()
                configs.append(cfg)
                log(f"  [{done:>3}/{total}] ✓  {name}")
            except Exception as exc:
                errors.append({"table": t, "error": str(exc)})
                log(f"  [{done:>3}/{total}] ✗  {name}  ({exc})")

    log(f"\n  成功 {len(configs)} 张，失败 {len(errors)} 张")
    return configs, errors

# ─── Phase 3：清洗数据 ────────────────────────────────────────────────────────

def has_from_relation(field):
    """过滤从关联表引用过来的镜像字段"""
    fr = field.get("from_relation_field")
    return bool(fr and isinstance(fr, dict) and fr)

def clean_fields(fields):
    result = []
    for f in fields:
        if has_from_relation(f):
            continue
        ft = f.get("field_type", "")
        cleaned = {
            "name":     f.get("name", ""),
            "field_type": ft,
            "label":    FIELD_TYPE_LABELS.get(ft, ft or "未知"),
            "required": f.get("required", False) is True,
        }
        config = f.get("config") or {}
        if ft == "relation" and config.get("table_id"):
            cleaned["target_table_id"] = config["table_id"]
            cleaned["is_multi"]        = config.get("is_multi") == 1
        if ft == "category" and config.get("options"):
            cleaned["options"] = [o.get("name", "") for o in config["options"]]
        result.append(cleaned)
    return result

def phase3_clean(configs):
    log("\n━━━ Phase 3/3  清洗字段数据 ━━━")
    cleaned_tables = []
    for cfg in configs:
        tid  = cfg.get("table_id", "")
        cleaned_tables.append({
            "table_id": tid,
            "name":     cfg.get("name", tid),
            "fields":   clean_fields(cfg.get("fields", [])),
        })
    log(f"  处理完成，共 {len(cleaned_tables)} 张表")
    return cleaned_tables

# ─── 主流程 ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="伙伴云表结构数据拉取")
    parser.add_argument("--space-id", help="工作区 ID")
    parser.add_argument("--api-key",  help="OpenAPI Bearer Token")
    args = parser.parse_args()

    space_id, api_key = load_credentials(args)
    log(f"工作区 ID：{space_id}")

    # Phase 1
    try:
        tables = phase1_fetch_tables(space_id, api_key)
    except RuntimeError as e:
        err(str(e))
        sys.exit(1)

    if not tables:
        err("该工作区没有表格")
        sys.exit(0)

    # Phase 2
    configs, fetch_errors = phase2_fetch_configs(tables, api_key)

    # Phase 3
    cleaned_tables = phase3_clean(configs)

    output = {
        "space_id":    space_id,
        "table_count": len(cleaned_tables),
        "tables":      cleaned_tables,
        "fetch_errors": [
            {"table_id": e["table"]["table_id"], "name": e["table"].get("name", ""), "error": e["error"]}
            for e in fetch_errors
        ],
    }

    log("\n数据准备完成，输出 JSON...\n")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
