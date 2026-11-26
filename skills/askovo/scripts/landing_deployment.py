"""Explicit external-deployment adapter for an immutable landing experiment source."""
from __future__ import annotations

import hashlib
import json
import subprocess
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

import landing_experiment

SCHEMA = "askovo.landing-deployment/1"


class _ExperimentMetadata(HTMLParser):
    def __init__(self):
        super().__init__()
        self.source_sha256 = ""

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "meta" and values.get("name") == "askovo-source-sha256":
            self.source_sha256 = str(values.get("content") or "")


def _verify_public_page(url, source_hash, timeout, url_opener):
    try:
        with url_opener(url, timeout=timeout) as response:
            final_url = str(response.geturl()) if hasattr(response, "geturl") else url
            payload = response.read(1048577)
        if not final_url.startswith("https://"):
            return False, "non_https_final_url"
        if len(payload) > 1048576:
            return False, "response_too_large"
        metadata = _ExperimentMetadata()
        metadata.feed(payload.decode("utf-8"))
        if metadata.source_sha256 != source_hash:
            return False, "source_hash_mismatch"
        return True, ""
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return False, type(exc).__name__


def run_process(*, argv, cwd, env, timeout):
    try:
        completed = subprocess.run(argv, cwd=cwd, env=env, shell=False,
                                   capture_output=True, timeout=timeout, check=False)
        return {"exit_code": completed.returncode, "stdout": completed.stdout,
                "stderr": completed.stderr, "error": ""}
    except subprocess.TimeoutExpired as exc:
        return {"exit_code": None, "stdout": exc.stdout or b"",
                "stderr": exc.stderr or b"", "error": "timeout"}


def _validate(spec, root):
    if not isinstance(spec, dict) or spec.get("schema") != SCHEMA:
        raise ValueError("landing deployment schema must be %s" % SCHEMA)
    if not str(spec.get("deployment_id") or "").strip():
        raise ValueError("deployment_id is required")
    authorization = spec.get("authorization") if isinstance(spec.get("authorization"), dict) else {}
    if not str(authorization.get("authorized_by") or "").strip() \
            or not str(authorization.get("authorization_ref") or "").strip():
        raise ValueError("named deployment authorization and authorization_ref are required")
    argv = spec.get("argv")
    if not isinstance(argv, list) or not argv or not all(str(value or "").strip() for value in argv):
        raise ValueError("argv must be a non-empty string array")
    timeout = spec.get("timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 60:
        raise ValueError("timeout_seconds must be between 0 and 60")
    source = Path(root) / landing_experiment.SPEC_NAME
    digest = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    if spec.get("source_sha256") != digest:
        raise ValueError("landing experiment source hash does not match the deployment authorization")
    return digest


def deploy(spec, root, *, process_runner=None, url_opener=None):
    root = Path(root).resolve()
    landing_experiment.load_spec(root)
    source_hash = _validate(spec, root)
    if process_runner is None:
        raise ValueError("an explicit deployment process_runner is required")
    argv = [str(value).replace("{experiment_dir}", str(root)) for value in spec["argv"]]
    outcome = process_runner(argv=argv, cwd=str(root), env={},
                             timeout=float(spec["timeout_seconds"]))
    stdout = outcome.get("stdout") or b""
    if isinstance(stdout, str):
        stdout = stdout.encode("utf-8")
    observed = {}
    try:
        candidate = json.loads(stdout[:65536].decode("utf-8"))
        if isinstance(candidate, dict):
            observed = candidate
    except (ValueError, UnicodeDecodeError):
        observed = {}
    if "sha256:" + hashlib.sha256((root / landing_experiment.SPEC_NAME).read_bytes()).hexdigest() != source_hash:
        raise ValueError("landing experiment source changed during deployment")
    reported = bool(not outcome.get("error") and outcome.get("exit_code") == 0
                    and observed.get("deployment_id") == spec["deployment_id"]
                    and str(observed.get("url") or "").startswith("https://")
                    and str(observed.get("observed_at") or "").strip())
    verified = False
    verification_error = ""
    verification_requested = spec.get("verify_url") is True
    if reported and verification_requested:
        verified, verification_error = _verify_public_page(
            str(observed["url"]), source_hash, float(spec["timeout_seconds"]),
            url_opener or urllib.request.urlopen)
    status = ("DEPLOYMENT_VERIFIED" if verified else
              "DEPLOYMENT_REPORTED" if reported else "ADAPTER_EXECUTED")
    return {
        "schema": "askovo.landing-deployment-result/1",
        "status": status,
        "deployment_id": spec["deployment_id"],
        "url": str(observed.get("url") or ""),
        "observed_at": str(observed.get("observed_at") or ""),
        "source_sha256": source_hash,
        "adapter_executed": True,
        "deployment_reported": reported,
        "deployment_verified": verified,
        "verification_requested": verification_requested,
        "verification_error": verification_error,
        "external_deployment_executed": spec.get("external_deployment") is True,
        "exit_code": outcome.get("exit_code"),
        "error": str(outcome.get("error") or ""),
        "source_mutated": False,
        "boundary": "DEPLOYMENT_REPORTED is only the adapter receipt. DEPLOYMENT_VERIFIED independently reads the HTTPS page and matches its frozen source fingerprint. Neither proves eligible traffic, participation, conversion or demand.",
    }


def write_new(document, path):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return target
