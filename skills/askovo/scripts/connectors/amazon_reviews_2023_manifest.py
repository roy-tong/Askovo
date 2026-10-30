#!/usr/bin/env python3
"""Write a file manifest of a HuggingFace dataset repository via the tree API.

Collected from the Tiiny user-research project (scripts/amazon_reviews_2023_manifest.py).
Use it to plan downloads (sizes, paths, oids) before running range_download.py
or the streaming collector. Generic value beyond one project: it works for any
HF dataset id and records exact file oids so a later run can prove which file
revision was consumed.

Project-agnostic changes: `--dataset-id` instead of the hardcoded
McAuley-Lab id (kept as default), `--out` resolved relative to the current
directory instead of the project root, and an explicit `--user-agent`.
"""
from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_DATASET = "McAuley-Lab/Amazon-Reviews-2023"


def main() -> None:
    parser = argparse.ArgumentParser(description="List a HuggingFace dataset repository's files with sizes and oids.")
    parser.add_argument("--dataset-id", default=DEFAULT_DATASET)
    parser.add_argument("--prefix", default="raw", help="keep only paths starting with this prefix (use '' for everything)")
    parser.add_argument("--user-agent", default="askovo-connector/1.0")
    parser.add_argument("--out", type=Path, default=Path("hf_dataset_manifest.json"))
    args = parser.parse_args()

    tree_url = (
        "https://huggingface.co/api/datasets/"
        + urllib.parse.quote(args.dataset_id, safe="")
        + "/tree/main?recursive=1"
    )
    request = urllib.request.Request(tree_url, headers={"User-Agent": args.user_agent})
    with urllib.request.urlopen(request, timeout=60) as response:
        tree = json.loads(response.read().decode("utf-8"))

    relevant = []
    for item in tree:
        path = item.get("path", "")
        if args.prefix and not path.startswith(args.prefix):
            continue
        relevant.append(
            {
                "dataset_id": args.dataset_id,
                "path": path,
                "size": item.get("size"),
                "type": item.get("type"),
                "oid": item.get("oid"),
            }
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(relevant, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {len(relevant)} manifest rows for {args.dataset_id} to {args.out}")


if __name__ == "__main__":
    main()
