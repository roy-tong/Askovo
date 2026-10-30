#!/usr/bin/env python3
"""Resumable concurrent HTTP range downloader for a published research file.

Collected verbatim from the BCI demand-discovery study
(scripts/range_download.py) - it was already project-agnostic. Use it when a
dataset publishes plain files behind a server that honours Range headers
(e.g. HuggingFace resolve URLs) and a single-stream download would take hours.

Each part is fetched into `<output>.parts/NNN.part`; completed parts of the
right size are skipped on re-run, so an interrupted download resumes. Parts
are concatenated into `<output>.partial` and atomically renamed once the
combined size matches `--size`.

The only change during collection: an optional `--user-agent` so the requester
identifies itself per platform etiquette instead of the urllib default.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import os
import shutil
import urllib.request
from pathlib import Path


def fetch(url: str, start: int, end: int, target: Path, user_agent: str | None) -> int:
    expected = end - start + 1
    if target.exists() and target.stat().st_size == expected:
        return expected
    headers = {"Range": f"bytes={start}-{end}"}
    if user_agent:
        headers["User-Agent"] = user_agent
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=180) as response, target.open("wb") as handle:
        shutil.copyfileobj(response, handle, length=1024 * 1024)
    actual = target.stat().st_size
    if actual != expected:
        raise RuntimeError(f"{target.name}: got {actual}, expected {expected}")
    return actual


def main() -> None:
    parser = argparse.ArgumentParser(description="Concurrent, resumable Range download of one published file.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--size", type=int, required=True, help="total file size in bytes (e.g. from the dataset manifest)")
    parser.add_argument("--parts", type=int, default=12)
    parser.add_argument("--user-agent", default=None)
    args = parser.parse_args()
    work = args.output.with_name(args.output.name + ".parts")
    work.mkdir(parents=True, exist_ok=True)
    chunk = (args.size + args.parts - 1) // args.parts
    ranges = []
    for index in range(args.parts):
        start = index * chunk
        if start >= args.size:
            break
        end = min(args.size - 1, start + chunk - 1)
        ranges.append((index, start, end, work / f"{index:03d}.part"))
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(ranges)) as pool:
        futures = [pool.submit(fetch, args.url, start, end, target, args.user_agent) for _, start, end, target in ranges]
        for future in concurrent.futures.as_completed(futures):
            future.result()
    temporary = args.output.with_suffix(args.output.suffix + ".partial")
    with temporary.open("wb") as combined:
        for _, _, _, part in ranges:
            with part.open("rb") as handle:
                shutil.copyfileobj(handle, combined, length=1024 * 1024)
    if temporary.stat().st_size != args.size:
        raise RuntimeError("combined file size mismatch")
    os.replace(temporary, args.output)
    print(f"downloaded {args.output} ({args.size} bytes, {len(ranges)} ranges)")


if __name__ == "__main__":
    main()
