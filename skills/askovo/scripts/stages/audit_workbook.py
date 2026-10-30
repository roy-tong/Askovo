#!/usr/bin/env python3
"""Human-audit workbook tool: stratified spot-check sample → gold-standard
review columns → agreement statistics → xlsx.

This is the consolidated "A-5" audit tool. Provenance (consolidation lineage):

- Sampling base: ``projects/泛具身用户研究/scripts/spot_check_labels.py`` — the
  stratified spot-check pattern (per stratum, sample across a fixed mix of
  evidence levels, up to a per-stratum cap, with reviewer-fill columns
  ``desk_review_judgment`` / ``corrected_level`` / ``notes``). Generalized
  here: stratum field, cross field, per-cross counts and level list are CLI
  arguments instead of a hardcoded product-form/`demand_evidence_level` pair.
- Workbook base: ``projects/泛具身用户研究/scripts/build_audit_workbook.py`` — the
  openpyxl sheet writer (styled header row, wrapped cells, adaptive column
  widths ``min(max(len*1.6, 10), 70)``, frozen header pane) and the
  Chinese-named 总览 sheet. pandas dropped; std csv suffices.
- From ``projects/脑机接口调研/04-场景语料验证``: the manual-review discipline in
  ``scripts/sample_manual_review.py`` + ``05-audit/manual-review-40.csv`` —
  deterministic seeded sampling with an input snapshot hash recorded on every
  row, and the verdict column vocabulary (OK / BORDERLINE / FAIL style
  judgments with failure_type), which ``score`` reads back for distribution
  counts.
- From ``projects/AI眼镜用户研究/scripts/audit_dataset_quality.py``: the
  concentration warnings (top platform share cap, single-month share cap,
  missing months inside the observed range) surfaced on the 总览 sheet.
- From ``projects/大人糖/用户研究/scripts/audit_codebook_coverage.py``: the
  codebook-coverage pattern (term-family regex hits vs a per-family
  sufficiency threshold) as the optional ``coverage`` subcommand.

Dependencies: openpyxl is the ONLY third-party dependency (xlsx in/out);
``sample --csv-out`` / ``score`` on a CSV path work with the standard library
alone.

Discipline: agreement rates measure THIS rule labeler against THIS reviewer on
THIS sample — they are calibration evidence for the labeling pipeline, never
a claim about the population.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from common import ensure_parent, read_jsonl

try:
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
except ModuleNotFoundError:  # pragma: no cover - exercised only without openpyxl
    Workbook = None  # type: ignore[assignment]

HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
HEADER_FONT = Font(color="FFFFFF", bold=True)
WRAP = Alignment(wrap_text=True, vertical="top")
SAMPLE_SHEET = "抽检样本"

GOLD_REVIEWER_COLUMNS = ["reviewer", "review_date", "notes"]


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------

def snapshot_hash(record_ids: Sequence[str]) -> str:
    """BCI pattern: stable 16-hex fingerprint of the sampled input snapshot."""
    joined = "\n".join(sorted(str(r) for r in record_ids))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def join_labels(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "|".join(str(v) for v in value)
    return str(value)


def write_table_sheet(wb: Any, name: str, header: List[str], rows: List[List[Any]]) -> Any:
    """泛具身-style sheet writer: styled header, wrapped cells, adaptive widths."""
    ws = wb.create_sheet(name)
    if not rows and not header:
        ws.cell(row=1, column=1, value="(empty)")
        return ws
    for j, col in enumerate(header, start=1):
        cell = ws.cell(row=1, column=j, value=str(col))
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
    for i, row in enumerate(rows, start=2):
        for j, value in enumerate(row, start=1):
            cell = ws.cell(row=i, column=j, value=value)
            cell.alignment = WRAP
    for j, col in enumerate(header, start=1):
        lens = [len(str(col))] + [len(str(row[j - 1])) for row in rows]
        ws.column_dimensions[get_column_letter(j)].width = min(max(max(lens) * 1.6, 10), 70)
    ws.freeze_panes = "A2"
    return ws


def missing_months(month_counts: Counter) -> List[str]:
    months = sorted(m for m in month_counts if m and m != "unknown")
    if len(months) < 2:
        return []
    start_y, start_m = [int(x) for x in months[0].split("-")]
    end_y, end_m = [int(x) for x in months[-1].split("-")]
    out = []
    y, m = start_y, start_m
    while (y, m) <= (end_y, end_m):
        key = f"{y:04d}-{m:02d}"
        if key not in month_counts:
            out.append(key)
        if m == 12:
            y += 1
            m = 1
        else:
            m += 1
    return out


def concentration_warnings(
    records: List[Dict[str, Any]], platform_cap: float, month_cap: float
) -> List[str]:
    """AI眼镜 audit_dataset_quality pattern: concentration + month-gap warnings."""
    warnings: List[str] = []
    total = len(records)
    if not total:
        return ["empty input"]
    platform_counts = Counter(str(r.get("source_platform") or "unknown") for r in records)
    top_platform, top_count = platform_counts.most_common(1)[0]
    share = top_count / total
    if share > platform_cap:
        warnings.append(
            f"single platform `{top_platform}` is {share:.1%}, above cap {platform_cap:.0%}"
        )
    month_counts = Counter(str(r.get("month_bucket") or "unknown") for r in records)
    if month_counts:
        top_month, top_mcount = month_counts.most_common(1)[0]
        mshare = top_mcount / total
        if top_month != "unknown" and mshare > month_cap:
            warnings.append(
                f"single month `{top_month}` is {mshare:.1%}, above cap {month_cap:.0%}; "
                "annotate event spikes or use the month-balanced view"
            )
    gaps = missing_months(month_counts)
    if gaps:
        warnings.append(
            "missing months in observed range: " + ", ".join(gaps[:18]) + ("..." if len(gaps) > 18 else "")
        )
    return warnings


# ---------------------------------------------------------------------------
# sample: dataset → stratified spot-check workbook
# ---------------------------------------------------------------------------

def cmd_sample(args: argparse.Namespace) -> int:
    if Workbook is None:
        print("openpyxl is required for the xlsx workbook: pip install openpyxl")
        return 2
    records = list(read_jsonl(args.input))
    if not records:
        print(f"no records in {args.input}")
        return 2
    rng = random.Random(args.seed)
    label_fields = [f.strip() for f in args.label_fields.split(",") if f.strip()]
    snap = snapshot_hash(str(r.get("record_id")) for r in records)

    stratum_field = None if args.no_stratify else args.stratum_field
    cross_field = args.cross_field
    cross_values: Optional[List[str]] = (
        [v.strip() for v in args.cross_values.split(",") if v.strip()] if args.cross_values else None
    )

    # group by stratum (single "all" stratum when no field given)
    strata: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for record in records:
        key = join_labels(record.get(stratum_field)) if stratum_field else "all"
        strata[key or "unknown"].append(record)

    picked: List[Dict[str, Any]] = []
    for stratum in sorted(strata):
        pool = strata[stratum]
        chosen: List[Dict[str, Any]] = []
        if cross_field:
            observed = cross_values or sorted(
                {join_labels(r.get(cross_field)) or "unknown" for r in pool}
            )
            for value in observed:
                sub = [
                    r
                    for r in pool
                    if (join_labels(r.get(cross_field)) or "unknown") == value
                ]
                if sub:
                    chosen.extend(rng.sample(sub, min(args.per_cross, len(sub))))
        elif args.per_stratum > 0 and len(pool) > args.per_stratum:
            chosen = rng.sample(pool, args.per_stratum)
        if args.per_stratum > 0 and len(chosen) > args.per_stratum:
            chosen = chosen[: args.per_stratum]
        for record in chosen:
            row = dict(record)
            row["_stratum"] = stratum
            picked.append(row)

    if not picked:
        print("sampling produced no rows; check --stratum-field/--cross-field values")
        return 2

    header = ["idx", "record_id", "stratum"]
    if cross_field:
        header.append(f"{cross_field}_auto")
    for field in label_fields:
        header.append(f"{field}_auto")
    header.extend(
        ["source_platform", "text_excerpt", "source_url", "created_at", "source_query"]
    )
    header.extend([f"gold_{field}" for field in label_fields])
    header.extend(GOLD_REVIEWER_COLUMNS)
    header.append("input_snapshot_sha16")

    rows: List[List[Any]] = []
    for idx, record in enumerate(picked, start=1):
        row: List[Any] = [idx, record.get("record_id"), record["_stratum"]]
        if cross_field:
            row.append(join_labels(record.get(cross_field)))
        for field in label_fields:
            row.append(join_labels(record.get(field)))
        text = str(record.get("text") or "")
        row.extend(
            [
                record.get("source_platform"),
                (record.get("text_excerpt") or text[: args.excerpt]).replace("\n", " "),
                record.get("source_url"),
                record.get("created_at"),
                record.get("source_query"),
            ]
        )
        row.extend(["" for _ in label_fields])  # gold_<field> fill-ins
        row.extend(["", "", ""])  # reviewer / review_date / notes
        row.append(snap)
        rows.append(row)

    wb = Workbook()
    wb.remove(wb.active)

    overview: List[Tuple[str, Any]] = [
        ("输入", str(args.input)),
        ("记录总数", len(records)),
        ("抽检样本数", len(picked)),
        ("抽样种子", args.seed),
        ("分层字段", stratum_field or "(整体抽样)"),
        ("交叉字段", cross_field or "-"),
        ("每交叉取数", args.per_cross),
        ("每层上限", args.per_stratum),
        ("金标字段", ", ".join(f"gold_{f}" for f in label_fields)),
        ("输入快照指纹", snap),
        ("复核说明", "请人工填写 gold_* 列（多标签用 | 分隔）、reviewer、review_date、notes；填完后用 score 子命令计算一致率"),
    ]
    for warning in concentration_warnings(records, args.platform_cap, args.month_cap):
        overview.append(("警告", warning))
    write_table_sheet(wb, "总览", ["项", "值"], [[k, v] for k, v in overview])
    write_table_sheet(wb, SAMPLE_SHEET, header, rows)

    # distribution sheets
    if stratum_field:
        stratum_counts = Counter(
            join_labels(r.get(stratum_field)) or "unknown" for r in records
        )
        write_table_sheet(
            wb,
            "分层分布",
            [stratum_field, "records"],
            [[k, v] for k, v in stratum_counts.most_common()],
        )
    for field in label_fields:
        counts = Counter(
            label
            for r in records
            for label in (join_labels(r.get(field)).split("|") if join_labels(r.get(field)) else ["unlabeled"])
        )
        write_table_sheet(
            wb, f"分布_{field[:24]}"[:31], [field, "records"], [[k, v] for k, v in counts.most_common(100)]
        )

    if args.coverage_config:
        coverage_rows = coverage(records, args.coverage_config)
        write_table_sheet(
            wb,
            "词族覆盖",
            ["family", "level", "hits", "threshold", "sufficient"],
            coverage_rows,
        )

    ensure_parent(args.out)
    wb.save(args.out)
    print(f"wrote workbook ({len(picked)} sample rows) -> {args.out}")
    print(f"snapshot {snap}; reviewer fills gold_* columns, then run: audit_workbook.py score")

    if args.csv_out:
        ensure_parent(args.csv_out)
        with args.csv_out.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerows(rows)
        print(f"wrote CSV sample -> {args.csv_out}")
    return 0


def coverage(records: List[Dict[str, Any]], config_path: Path) -> List[List[Any]]:
    """大人糖 audit_codebook_coverage pattern: per-family regex hits vs threshold."""
    cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
    families = cfg.get("families") or {}
    default_threshold = int(cfg.get("default_threshold", 100))
    seen_hash = set()
    fam_counts: Counter = Counter()
    fam_by_src: Dict[str, Counter] = defaultdict(Counter)
    total = 0
    for record in records:
        text_hash = record.get("normalized_text_hash") or record.get("text_hash")
        if text_hash:
            if text_hash in seen_hash:
                continue
            seen_hash.add(text_hash)
        total += 1
        hay = f"{record.get('thread_title') or ''} {record.get('text') or ''}"
        for family, spec in families.items():
            pattern = spec.get("pattern") if isinstance(spec, dict) else spec
            if pattern and re.search(str(pattern), hay, re.I):
                context = str(spec.get("context_pattern", "") or "") if isinstance(spec, dict) else ""
                if context and not re.search(context, hay, re.I):
                    continue
                fam_counts[family] += 1
                fam_by_src[family][str(record.get("source_platform") or "unknown")] += 1
    out: List[List[Any]] = []
    for family, spec in families.items():
        threshold = (
            int(spec.get("threshold", default_threshold)) if isinstance(spec, dict) else default_threshold
        )
        hits = fam_counts[family]
        out.append([family, "family", hits, threshold, "sufficient" if hits >= threshold else "deficit"])
    return out


# ---------------------------------------------------------------------------
# score: filled workbook/CSV → agreement statistics
# ---------------------------------------------------------------------------

def read_review_rows(path: Path, sheet: Optional[str]) -> List[Dict[str, str]]:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        if Workbook is None:
            raise SystemExit("openpyxl is required to read xlsx: pip install openpyxl")
        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb[sheet or SAMPLE_SHEET] if (sheet or SAMPLE_SHEET) in wb.sheetnames else wb[wb.sheetnames[0]]
        iterator = ws.iter_rows(values_only=True)
        header = [str(c or "") for c in next(iterator, [])]
        rows = [
            {header[i]: ("" if c is None else str(c)) for i, c in enumerate(row) if i < len(header)}
            for row in iterator
        ]
        wb.close()
        return rows
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_label_set(value: str) -> List[str]:
    return sorted({part.strip() for part in str(value or "").split("|") if part.strip()})


def cmd_score(args: argparse.Namespace) -> int:
    rows = read_review_rows(args.reviewed, args.sheet)
    auto_fields = sorted(
        {
            str(key)[: -len("_auto")]
            for key in (rows[0].keys() if rows else [])
            if str(key).endswith("_auto") and not str(key).startswith("gold_")
        }
    )
    if not auto_fields:
        print("no <field>_auto columns found in the reviewed file")
        return 2

    report: Dict[str, Any] = {"reviewed_file": str(args.reviewed), "fields": {}}
    overall_matches = 0
    overall_reviewed = 0
    for field in auto_fields:
        auto_key = f"{field}_auto"
        gold_key = f"gold_{field}"
        n_reviewed = 0
        exact = 0
        per_label: Dict[str, Dict[str, int]] = defaultdict(lambda: {"both": 0, "auto_only": 0, "gold_only": 0})
        confusion: Counter = Counter()
        for row in rows:
            gold_raw = (row.get(gold_key) or "").strip()
            if not gold_raw:
                continue
            n_reviewed += 1
            auto_set = parse_label_set(row.get(auto_key))
            gold_set = parse_label_set(gold_raw)
            if auto_set == gold_set:
                exact += 1
                confusion[("MATCH", "MATCH")] += 1
            else:
                confusion[("|".join(auto_set) or "(none)", "|".join(gold_set) or "(none)")] += 1
            for label in set(auto_set) | set(gold_set):
                stats = per_label[label]
                if label in auto_set and label in gold_set:
                    stats["both"] += 1
                elif label in auto_set:
                    stats["auto_only"] += 1
                else:
                    stats["gold_only"] += 1
        agreement = round(exact / n_reviewed, 4) if n_reviewed else None
        label_stats = {
            label: {
                "both": stats["both"],
                "auto_only": stats["auto_only"],
                "gold_only": stats["gold_only"],
                "precision": round(stats["both"] / (stats["both"] + stats["auto_only"]), 4)
                if (stats["both"] + stats["auto_only"])
                else None,
                "recall": round(stats["both"] / (stats["both"] + stats["gold_only"]), 4)
                if (stats["both"] + stats["gold_only"])
                else None,
            }
            for label, stats in sorted(per_label.items())
        }
        report["fields"][field] = {
            "n_reviewed": n_reviewed,
            "exact_agreement": agreement,
            "per_label": label_stats,
            "top_confusions": [
                {"auto": k[0], "gold": k[1], "count": v}
                for k, v in confusion.most_common(15)
                if k != ("MATCH", "MATCH")
            ][:10],
        }
        if n_reviewed:
            overall_reviewed += n_reviewed
            overall_matches += exact

    verdict_columns = [c for c in (rows[0].keys() if rows else [])
                       if c in {"verdict", "desk_review_judgment", "failure_type"}]
    for column in verdict_columns:
        report[f"{column}_distribution"] = dict(
            Counter((row.get(column) or "").strip() for row in rows if (row.get(column) or "").strip())
        )

    report["overall_exact_agreement"] = (
        round(overall_matches / overall_reviewed, 4) if overall_reviewed else None
    )
    report["note"] = (
        "Agreement calibrates the rule labeler against this reviewer on this sample; "
        "it says nothing about population prevalence."
    )

    if args.out:
        ensure_parent(args.out)
        args.out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"wrote agreement JSON -> {args.out}")

    print(f"overall exact agreement: {report['overall_exact_agreement']}")
    for field, stats in report["fields"].items():
        print(f"  {field}: n={stats['n_reviewed']} exact={stats['exact_agreement']}")
    if args.report_out:
        lines = [
            "# 标签人工抽检一致率报告",
            "",
            f"- 复核文件: `{args.reviewed}`",
            f"- 总体整行一致率: {report['overall_exact_agreement']}",
            "",
            "| 字段 | 复核数 | 整行一致率 |",
            "| --- | ---: | ---: |",
        ]
        for field, stats in report["fields"].items():
            lines.append(f"| {field} | {stats['n_reviewed']} | {stats['exact_agreement']} |")
        lines.append("")
        lines.append("说明：一致率只校准本规则打标器与本复核人在本样本上的表现，不支持任何总体推断。")
        ensure_parent(args.report_out)
        args.report_out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote agreement report -> {args.report_out}")

    if args.min_agreement is not None and overall_reviewed:
        if (report["overall_exact_agreement"] or 0) < args.min_agreement:
            print(
                f"agreement {report['overall_exact_agreement']} below gate {args.min_agreement} — "
                "fix labels or taxonomy before drawing conclusions"
            )
            return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Spot-check sampling, gold-standard review workbook, and agreement scoring."
    )
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    sample_parser = subparsers.add_parser("sample", help="build the audit workbook")
    sample_parser.add_argument("--input", type=Path, required=True, help="dataset JSONL(.gz)")
    sample_parser.add_argument("--out", type=Path, default=Path("05-audit/spot_check_workbook.xlsx"))
    sample_parser.add_argument("--csv-out", type=Path, default=None, help="optional CSV sample")
    sample_parser.add_argument(
        "--stratum-field", default=None, help="field to stratify by (e.g. product_hint)"
    )
    sample_parser.add_argument(
        "--cross-field",
        default=None,
        help="second field: within each stratum, spread the sample across this field's values "
        "(e.g. demand_evidence_level)",
    )
    sample_parser.add_argument(
        "--cross-values", default=None, help="comma list fixing the cross values and their order"
    )
    sample_parser.add_argument("--per-cross", type=int, default=4)
    sample_parser.add_argument("--per-stratum", type=int, default=20)
    sample_parser.add_argument("--no-stratify", action="store_true", help="ignore --stratum-field")
    sample_parser.add_argument(
        "--label-fields",
        default="demand_evidence_level,scenario_labels",
        help="fields surfaced as <field>_auto plus a gold_<field> review column",
    )
    sample_parser.add_argument("--excerpt", type=int, default=300)
    sample_parser.add_argument("--seed", type=int, default=7)
    sample_parser.add_argument("--platform-cap", type=float, default=0.35)
    sample_parser.add_argument("--month-cap", type=float, default=0.12)
    sample_parser.add_argument(
        "--coverage-config",
        type=Path,
        default=None,
        help="optional codebook-coverage JSON (大人糖 pattern): families → regex/threshold",
    )
    sample_parser.set_defaults(func=cmd_sample)

    score_parser = subparsers.add_parser("score", help="score a filled workbook/CSV")
    score_parser.add_argument("--reviewed", type=Path, required=True, help="filled xlsx or CSV")
    score_parser.add_argument("--sheet", default=None, help="sheet name (default 抽检样本)")
    score_parser.add_argument("--out", type=Path, default=None, help="agreement JSON path")
    score_parser.add_argument("--report-out", type=Path, default=None, help="agreement MD path")
    score_parser.add_argument(
        "--min-agreement",
        type=float,
        default=None,
        help="gate: exit 1 when overall exact agreement is below this",
    )
    score_parser.set_defaults(func=cmd_score)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
