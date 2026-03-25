from __future__ import annotations

import argparse
import base64
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, build_opener, urlopen


DEFAULT_BASE_URL = "http://172.16.82.11:18081/dcm4chee-arc/aets/DCM4CHEE/rs"
DEFAULT_CATEGORY_PATH = "冷冻消融及随访/北大人民医院"
DEFAULT_PAGE_SIZE = 200
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_WORKERS = 8


@dataclass(frozen=True)
class StudyRef:
    study_instance_uid: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill historical studies in dcm4chee by updating their Access Control ID "
            "to the viewer classification path."
        )
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="Base DICOMweb REST URL, typically /dcm4chee-arc/aets/DCM4CHEE/rs.",
    )
    parser.add_argument(
        "--category-path",
        default=DEFAULT_CATEGORY_PATH,
        help="Category path to write back into every matching study.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        help="Number of studies to fetch per QIDO page.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=DEFAULT_MAX_WORKERS,
        help="Parallel update workers. Use 1 to run sequentially.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="HTTP timeout in seconds for QIDO and update calls.",
    )
    parser.add_argument(
        "--username",
        help="Optional HTTP basic auth username.",
    )
    parser.add_argument(
        "--password",
        help="Optional HTTP basic auth password.",
    )
    parser.add_argument(
        "--header",
        action="append",
        default=[],
        help="Optional extra HTTP header in the form 'Name: value'. Can be repeated.",
    )
    parser.add_argument(
        "--cookie",
        help="Optional Cookie header value. Useful when the PACS session is protected by browser login.",
    )
    parser.add_argument(
        "--study-uid",
        action="append",
        dest="study_uids",
        help="Optional study UID to update. Repeat to backfill only specific studies.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only list the studies that would be updated.",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=Path(__file__).with_name("backfill_category_path.log"),
        help="Write detailed errors to this log file.",
    )
    return parser.parse_args()


def normalize_category_path(value: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    for delimiter in ("→", "｜", ">", "::"):
        text = text.replace(delimiter, "/")
    segments = [segment.strip() for segment in text.split("/") if segment.strip()]
    return "/".join(segments)


def serialize_category_path(value: str) -> str:
    segments = [segment.strip() for segment in normalize_category_path(value).split("/") if segment.strip()]
    return "→".join(segments)


def render_progress_bar(completed: int, total: int, width: int = 24) -> str:
    if total <= 0:
        return f"[{'-' * width}]"

    completed = max(0, min(completed, total))
    filled = int((completed / total) * width)

    if completed >= total:
        return f"[{'=' * width}]"
    if filled <= 0:
        return f"[>{'-' * max(0, width - 1)}]"
    if filled >= width:
        return f"[{'=' * width}]"

    return f"[{'=' * filled}>{'-' * (width - filled - 1)}]"


def setup_logging(log_file: Path) -> logging.Logger:
    logger = logging.getLogger("backfill_category_path")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(console_handler)

    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(file_handler)

    return logger


def parse_extra_headers(values: Iterable[str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for raw_value in values:
        if not raw_value:
            continue
        if ":" not in raw_value:
            raise ValueError(f"Invalid --header value (expected 'Name: value'): {raw_value}")
        name, value = raw_value.split(":", 1)
        headers[name.strip()] = value.strip()
    return headers


def extract_qido_value(item: dict, tag: str) -> str | None:
    raw = item.get(tag) or item.get(tag.lower())

    if isinstance(raw, dict):
        values = raw.get("Value") or []
        if values:
            return str(values[0]).strip() or None
        return None

    if raw is None:
        return None

    text = str(raw).strip()
    return text or None


def build_request(
    url: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    auth_header: str | None = None,
    extra_headers: Optional[dict[str, str]] = None,
) -> Request:
    headers = {
        "Accept": "application/json",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    if auth_header:
        headers["Authorization"] = auth_header
    if extra_headers:
        headers.update(extra_headers)
    return Request(url, data=body, headers=headers, method=method)


def basic_auth_header(username: Optional[str], password: Optional[str]) -> str | None:
    if not username and not password:
        return None

    token = base64.b64encode(f"{username or ''}:{password or ''}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def qido_study_uids(
    base_url: str,
    *,
    page_size: int,
    timeout: float,
    auth_header: str | None,
    extra_headers: Optional[dict[str, str]],
    logger: logging.Logger,
) -> list[StudyRef]:
    studies: list[StudyRef] = []
    offset = 0
    base = base_url.rstrip("/")

    while True:
        url = f"{base}/studies?includefield=0020000D&limit={page_size}&offset={offset}"
        request = build_request(url, auth_header=auth_header, extra_headers=extra_headers)

        try:
            with urlopen(request, timeout=timeout) as response:
                payload = response.read()
        except HTTPError as exc:
            raise RuntimeError(f"QIDO request failed ({exc.code}): {exc.reason}") from exc
        except URLError as exc:
            raise RuntimeError(f"QIDO request failed: {exc.reason}") from exc

        items = json.loads(payload.decode("utf-8")) if payload else []
        if not items:
            break

        for item in items:
            uid_text = extract_qido_value(item, "0020000D") or ""
            if uid_text:
                studies.append(StudyRef(study_instance_uid=uid_text))

        logger.info("[QIDO] offset=%s fetched=%s total=%s", offset, len(items), len(studies))
        if len(items) < page_size:
            break
        offset += len(items)

    return studies


def qido_study_category_path(
    base_url: str,
    study_uid: str,
    *,
    timeout: float,
    auth_header: str | None,
    extra_headers: Optional[dict[str, str]],
) -> str | None:
    base = base_url.rstrip("/")
    encoded_uid = quote(study_uid, safe="")
    url = f"{base}/studies?StudyInstanceUID={encoded_uid}&includefield=77771027&limit=1&offset=0"
    request = build_request(url, auth_header=auth_header, extra_headers=extra_headers)

    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except HTTPError as exc:
        raise RuntimeError(f"QIDO category lookup failed ({exc.code}): {exc.reason}") from exc
    except URLError as exc:
        raise RuntimeError(f"QIDO category lookup failed: {exc.reason}") from exc

    items = json.loads(payload.decode("utf-8")) if payload else []
    if not items:
        return None

    category_value = extract_qido_value(items[0], "77771027")
    if not category_value:
        return None

    return normalize_category_path(category_value)


def qido_study_record(
    base_url: str,
    study_uid: str,
    *,
    timeout: float,
    auth_header: str | None,
    extra_headers: Optional[dict[str, str]],
) -> dict | None:
    base = base_url.rstrip("/")
    encoded_uid = quote(study_uid, safe="")
    url = f"{base}/studies?StudyInstanceUID={encoded_uid}&includefield=all&limit=1&offset=0"
    request = build_request(url, auth_header=auth_header, extra_headers=extra_headers)

    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except HTTPError as exc:
        raise RuntimeError(f"QIDO study record lookup failed ({exc.code}): {exc.reason}") from exc
    except URLError as exc:
        raise RuntimeError(f"QIDO study record lookup failed: {exc.reason}") from exc

    items = json.loads(payload.decode("utf-8")) if payload else []
    if not items:
        return None
    return items[0]


def update_study_category(
    base_url: str,
    study_uid: str,
    category_path: str,
    *,
    timeout: float,
    auth_header: str | None,
    extra_headers: Optional[dict[str, str]],
) -> None:
    base = base_url.rstrip("/")
    encoded_uid = quote(study_uid, safe="")
    encoded_category = quote(category_path, safe="")
    url = f"{base}/studies/{encoded_uid}/access/{encoded_category}"
    request = build_request(
        url,
        method="PUT",
        body=b"{}",
        auth_header=auth_header,
        extra_headers=extra_headers,
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            response.read()
            if response.status not in (200, 202, 204):
                raise RuntimeError(f"Unexpected status {response.status}")
    except HTTPError as exc:
        raise RuntimeError(f"Failed to update {study_uid} ({exc.code}): {exc.reason}") from exc
    except URLError as exc:
        raise RuntimeError(f"Failed to update {study_uid}: {exc.reason}") from exc


def update_study_private_category(
    base_url: str,
    study_uid: str,
    category_path: str,
    *,
    timeout: float,
    auth_header: str | None,
    extra_headers: Optional[dict[str, str]],
) -> None:
    study_record = qido_study_record(
        base_url,
        study_uid,
        timeout=timeout,
        auth_header=auth_header,
        extra_headers=extra_headers,
    )
    if not study_record:
        raise RuntimeError(f"Study record not found for {study_uid}")

    normalized_category = normalize_category_path(category_path)
    stored_category_path = serialize_category_path(normalized_category)
    study_record["77771027"] = {"vr": "UT", "Value": [stored_category_path]}
    if not extract_qido_value(study_record, "00080005"):
        study_record["00080005"] = {"vr": "CS", "Value": ["ISO_IR 192"]}

    base = base_url.rstrip("/")
    encoded_uid = quote(study_uid, safe="")
    url = f"{base}/studies/{encoded_uid}"
    body = json.dumps(study_record, ensure_ascii=False).encode("utf-8")
    request = build_request(
        url,
        method="PUT",
        body=body,
        auth_header=auth_header,
        extra_headers={
            **(extra_headers or {}),
            "Content-Type": "application/dicom+json",
        },
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            response.read()
            if response.status not in (200, 202, 204):
                raise RuntimeError(f"Unexpected status {response.status}")
    except HTTPError as exc:
        raise RuntimeError(f"Failed to update private category for {study_uid} ({exc.code}): {exc.reason}") from exc
    except URLError as exc:
        raise RuntimeError(f"Failed to update private category for {study_uid}: {exc.reason}") from exc

def print_progress(completed: int, total: int, study_uid: str, status: str) -> None:
    percent = int((completed / total) * 100) if total else 100
    bar = render_progress_bar(completed, total)
    print(f"[BACKFILL] {bar} {completed}/{total} ({percent}%) {status} {study_uid}")


def main() -> int:
    args = parse_args()
    logger = setup_logging(args.log_file)

    category_path = normalize_category_path(args.category_path)
    if not category_path:
        raise SystemExit("--category-path cannot be empty")
    auth_header = basic_auth_header(args.username, args.password)
    extra_headers = parse_extra_headers(args.header)
    if args.cookie:
        extra_headers["Cookie"] = args.cookie
    try:
        if args.study_uids:
            studies = [StudyRef(study_instance_uid=str(uid).strip()) for uid in args.study_uids if str(uid).strip()]
        else:
            studies = qido_study_uids(
                args.base_url,
                page_size=max(1, int(args.page_size)),
                timeout=args.timeout,
                auth_header=auth_header,
                extra_headers=extra_headers,
                logger=logger,
            )

        if not studies:
            logger.info("[DONE] No studies found.")
            return 0

        logger.info("[PLAN] %s study/studies will be updated to %s", len(studies), category_path)
        if args.dry_run:
            for index, study in enumerate(studies, start=1):
                print_progress(index, len(studies), study.study_instance_uid, "dry-run")
            return 0

        max_workers = max(1, int(args.max_workers))
        completed = 0
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(
                    update_study_category,
                    args.base_url,
                    study.study_instance_uid,
                    serialize_category_path(category_path),
                    timeout=args.timeout,
                    auth_header=auth_header,
                    extra_headers=extra_headers,
                ): study
                for study in studies
            }

            for future in as_completed(future_map):
                study = future_map[future]
                try:
                    future.result()
                    completed += 1
                    print_progress(completed, len(studies), study.study_instance_uid, "updated")
                except Exception as exc:
                    logger.error("[FAIL] %s: %s", study.study_instance_uid, exc)

        logger.info("[DONE] updated=%s total=%s", completed, len(studies))
        return 0
    except Exception as exc:
        logger.exception("Fatal backfill error: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
