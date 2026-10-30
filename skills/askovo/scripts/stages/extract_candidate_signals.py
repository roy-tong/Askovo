#!/usr/bin/env python3
"""Open-vocabulary candidate signal discovery over a labeled dataset.

Provenance (consolidation lineage):

- Text cleaning base: ``projects/灵泷视界/用户研究/scripts/extract_candidate_signals.py``
  — the most evolved cleaner of the family: strips code fences / inline code /
  code-like lines by punctuation density, drops URLs, long hex blobs and log
  lines, and mines CJK 2–4-gram phrases alongside latin n-grams.
- Ranking base: ``projects/泛具身用户研究/scripts/extract_candidate_signals.py`` —
  the methodological upgrade: signals are ranked by unique-thread support,
  platform diversity and month persistence (not raw frequency), and a
  discriminative filter keeps only terms over-represented in the
  evidence-bearing pool relative to the full-corpus background (its
  ``evidence_pool`` was records with ``demand_evidence_level`` beyond E0).
- From ``projects/Tiiny用户研究/scripts/extract_candidate_signals.py`` (identical
  to the AI眼镜 variant except default filenames): the latin n-gram mining with
  stopwords and noise phrases, and the ``top_by_bucket`` / ``top_by_source``
  cross-tabs.
- Project-agnostic changes: pandas dropped (std csv/json only), every path
  explicit, ``.jsonl.gz`` input, domain stopwords / noise phrases extend via
  the taxonomy config (``signal_stopwords`` / ``signal_noise_phrases`` /
  ``signal_cjk_noise``), and which records count as "evidence-bearing" is a
  CLI choice instead of a hardcoded field value.

I/O contract: dataset JSONL(.gz) → ``data/processed/candidate_signals.json``
(+ optional CSV of the ranked signals).

Candidate signals are intentionally open-ended: use them to expand or
challenge the fixed taxonomy before writing conclusions — they are discovery
aids, not prevalence claims.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from common import Taxonomy, ensure_parent, read_jsonl

BASE_STOPWORDS = {
    "the", "and", "for", "that", "this", "with", "you", "are", "was", "but",
    "have", "has", "not", "can", "will", "just", "from", "they", "your",
    "all", "one", "out", "use", "using", "like", "about", "would", "there",
    "their", "what", "when", "which", "into", "than", "then", "them",
    "also", "only", "more", "some", "get", "got", "how", "why", "who",
    "it's", "its", "i'm", "i've", "don't", "doesn't", "didn't", "isn't",
    "llm", "llms", "model", "models", "ai", "level", "info", "debug",
    "warn", "error", "source", "msg", "time", "github.com", "https",
    "http", "download.go", "attempt", "failed", "retrying", "part",
    "don", "know", "think", "want", "need", "right", "now", "make",
    "askovo", "people", "most", "much", "years", "ago", "any", "other",
    "same", "thing", "even", "though", "pretty", "really", "good",
    "better", "well", "lot", "actually", "probably", "maybe",
    "public", "private", "protected", "class", "void", "const", "var", "let",
    "import", "export", "return", "true", "false", "null", "undefined", "vector3",
    "serializefield", "lastmessageat", "pt1m", "pt1h", "pt24h", "success", "failure",
}

BASE_NOISE_PHRASES = [
    "action performed",
    "automatically please",
    "please contact",
    "contact moderators",
    "moderators subreddit",
    "subreddit message",
    "message compose",
    "questions concerns",
    "please reply",
    "conversation please",
    "public discord",
    "pcpartpicker list",
    "list type item",
    "type item price",
    "prices include",
    "shipping taxes",
    "taxes rebates",
    "rebates discounts",
    "generated pcpartpicker",
    "report jul",
    "jul pacific",
    "view discuss",
    "discuss post",
    "pacific summary",
]

BASE_CJK_NOISE = {
    "这个", "那个", "就是", "还是", "可以", "不是", "什么", "一个", "没有", "因为",
    "所以", "然后", "感觉", "视频", "真的", "已经", "但是", "他们", "我们", "自己",
    "一下", "这种", "怎么", "现在",
}

TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_+.#-]{2,}")
LOG_LINE_RE = re.compile(
    r"(^|\s)(level=|time=|msg=|traceback|stack trace|exception|panic:|at [\w.$]+\(.*:\d+\))",
    re.I,
)
URL_RE = re.compile(r"https?://\S+")
HEX_RE = re.compile(r"\b[a-f0-9]{12,}\b", re.I)
CODE_FENCE_RE = re.compile(r"```.*?```", re.S)
INLINE_CODE_RE = re.compile(r"`[^`]{1,240}`")
CODE_LINE_RE = re.compile(
    r"^\s*(?:public|private|protected|class|def|function|const|let|var|import|from"
    r"|#include|using namespace|if\s*\(|for\s*\(|while\s*\(|return\b|[}\]])",
    re.I,
)
CJK_SPAN_RE = re.compile(r"[\u3400-\u9fff]{2,}")


def analysis_text(text: str) -> str:
    text = CODE_FENCE_RE.sub(" ", text)
    text = INLINE_CODE_RE.sub(" ", text)
    lines = []
    for line in text.splitlines():
        if LOG_LINE_RE.search(line) or CODE_LINE_RE.search(line):
            continue
        punctuation = sum(1 for char in line if char in "{}[]();=<>|_\\")
        if len(line) > 30 and punctuation / max(1, len(line)) > 0.12:
            continue
        lines.append(line)
    text = "\n".join(lines)
    text = URL_RE.sub(" ", text)
    text = HEX_RE.sub(" ", text)
    return text


def latin_tokens(text: str, stopwords: set) -> List[str]:
    return [t.lower() for t in TOKEN_RE.findall(analysis_text(text)) if t.lower() not in stopwords]


def latin_ngrams(words: List[str], n: int, stopwords: set, noise_phrases: List[str]) -> Iterable[str]:
    for i in range(len(words) - n + 1):
        gram = words[i : i + n]
        if any(w in stopwords for w in gram):
            continue
        if len(set(gram)) == 1:
            continue
        phrase = " ".join(gram)
        if any(noise in phrase for noise in noise_phrases):
            continue
        yield phrase


def cjk_ngrams(text: str, cjk_noise: set) -> Iterable[str]:
    for span in CJK_SPAN_RE.findall(analysis_text(text)):
        for n in (2, 3, 4):
            for index in range(len(span) - n + 1):
                phrase = span[index : index + n]
                if phrase in cjk_noise:
                    continue
                yield phrase


def has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", text))


def score_terms(
    counter: Counter,
    threads: Dict[str, set],
    platforms: Dict[str, set],
    months: Dict[str, set],
    background: Counter,
    pool_size: int,
    bg_total: int,
    min_records: int,
    min_threads: int,
    top: int,
) -> List[Dict[str, Any]]:
    """泛具身 ranking: thread support × platform diversity × time persistence,
    gated by a discriminative filter against the full-corpus background."""
    out: List[Dict[str, Any]] = []
    for term, count in counter.most_common(800):
        if count < min_records:
            continue
        thr = len(threads.get(term, set()))
        plat = len(platforms.get(term, set()))
        mon = len(months.get(term, set()))
        if thr < min_threads or plat < 1:
            continue
        bg_count = background.get(term, 0)
        bg_share = (bg_count + 1) / bg_total
        ev_share = count / pool_size
        if ev_share < 2.5 * bg_share:
            continue
        out.append(
            {
                "term": term,
                "records": count,
                "unique_threads": thr,
                "platforms": plat,
                "months": mon,
                "score": round((thr * 2 + plat * 3 + mon * 1.5) * (1 + min(count, 200) / 200), 2),
            }
        )
    return sorted(out, key=lambda x: -x["score"])[:top]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mine open-vocabulary candidate signals from a labeled dataset."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument(
        "--taxonomy", type=Path, default=None, help="optional taxonomy JSON for extra stopwords"
    )
    parser.add_argument("--top", type=int, default=200)
    parser.add_argument(
        "--evidence-field",
        default=None,
        help="when set, only records whose value is not empty/E0/unknown form the "
        "evidence-bearing pool (泛具身 pattern); default: all records",
    )
    parser.add_argument("--min-records", type=int, default=3)
    parser.add_argument("--min-threads", type=int, default=2)
    parser.add_argument(
        "--out", type=Path, default=Path("data/processed/candidate_signals.json")
    )
    parser.add_argument("--csv-out", type=Path, default=None, help="optional CSV of ranked signals")
    args = parser.parse_args()

    taxonomy: Optional[Taxonomy] = Taxonomy.load(args.taxonomy) if args.taxonomy else None
    stopwords = set(BASE_STOPWORDS)
    noise_phrases = list(BASE_NOISE_PHRASES)
    cjk_noise = set(BASE_CJK_NOISE)
    if taxonomy:
        stopwords.update(taxonomy.signal_stopwords)
        noise_phrases.extend(taxonomy.signal_noise_phrases)
        cjk_noise.update(taxonomy.signal_cjk_noise)

    records = list(read_jsonl(args.input))
    if args.evidence_field:
        pool = [
            r
            for r in records
            if str(r.get(args.evidence_field) or "") not in {"", "E0", "unknown", "None"}
        ]
    else:
        pool = records
    pool_size = len(pool)

    def thread_id(row: Dict[str, Any]) -> str:
        return str(row.get("parent_id") or row.get("record_id") or "unknown")

    # background term frequencies over the full input (for the discriminative filter)
    bg_latin: Counter = Counter()
    bg_cjk: Counter = Counter()
    for row in records:
        text = str(row.get("text") or "")
        words = latin_tokens(text, stopwords)
        bg_latin.update(set(words))
        bg_latin.update(set(latin_ngrams(words, 2, stopwords, noise_phrases)))
        bg_cjk.update(set(cjk_ngrams(text, cjk_noise)))
    # Background and evidence scores both use document frequency, not occurrences.
    bg_total = len(records) or 1

    unigram: Counter = Counter()
    bigram: Counter = Counter()
    trigram: Counter = Counter()
    cjk_phrase: Counter = Counter()
    by_bucket: Dict[str, Counter] = defaultdict(Counter)
    by_source: Dict[str, Counter] = defaultdict(Counter)
    threads: Dict[str, set] = defaultdict(set)
    platforms: Dict[str, set] = defaultdict(set)
    months: Dict[str, set] = defaultdict(set)

    for row in pool:
        text = str(row.get("text") or "")
        words = latin_tokens(text, stopwords)
        grams = list(latin_ngrams(words, 2, stopwords, noise_phrases)) + list(
            latin_ngrams(words, 3, stopwords, noise_phrases)
        )
        unigram.update(words)
        bigram.update({g for g in grams if g.count(" ") == 1})
        trigram.update(g for g in grams if g.count(" ") == 2)
        cjk_terms = set(cjk_ngrams(text, cjk_noise))
        cjk_phrase.update(cjk_terms)
        tid = thread_id(row)
        plat = str(row.get("source_platform") or "unknown")
        month = str(row.get("month_bucket") or "")[:7]
        bucket = str(row.get("sample_bucket") or "unknown")
        by_bucket[bucket].update(grams)
        by_source[plat].update(grams)
        for term in set(grams):
            threads[term].add(tid)
            platforms[term].add(plat)
            if month:
                months[term].add(month)
        for term in cjk_terms:
            threads[term].add(tid)
            platforms[term].add(plat)
            if month:
                months[term].add(month)

    ranked_latin = score_terms(
        bigram, threads, platforms, months, bg_latin, pool_size, bg_total,
        args.min_records, args.min_threads, args.top,
    )
    ranked_cjk = score_terms(
        cjk_phrase, threads, platforms, months, bg_cjk, pool_size, bg_total,
        args.min_records, args.min_threads, args.top,
    )

    result = {
        "input": str(args.input),
        "record_count": len(records),
        "evidence_pool": pool_size if args.evidence_field else None,
        "evidence_field": args.evidence_field,
        "top_unigrams": unigram.most_common(args.top),
        "top_bigrams": bigram.most_common(args.top),
        "top_trigrams": trigram.most_common(args.top),
        "top_cjk_2_4grams": cjk_phrase.most_common(args.top),
        "ranked_latin_signals": ranked_latin,
        "ranked_cjk_signals": ranked_cjk,
        "top_by_bucket": {k: v.most_common(80) for k, v in by_bucket.items()},
        "top_by_source": {k: v.most_common(80) for k, v in by_source.items()},
        "note": "Candidate signals are intentionally open-ended. Use these to "
        "expand or challenge the fixed taxonomy before writing conclusions.",
    }
    ensure_parent(args.out)
    args.out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"wrote candidate signals -> {args.out}")

    if args.csv_out:
        ensure_parent(args.csv_out)
        with args.csv_out.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["lang", "term", "records", "unique_threads", "platforms", "months", "score"],
            )
            writer.writeheader()
            for row in ranked_latin:
                writer.writerow(dict(row, lang="latin"))
            for row in ranked_cjk:
                writer.writerow(dict(row, lang="cjk"))
        print(f"wrote ranked signals CSV -> {args.csv_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
