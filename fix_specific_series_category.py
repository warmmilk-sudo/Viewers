from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen

from backfill_category_path import (
    DEFAULT_BASE_URL,
    basic_auth_header,
    build_request,
    extract_qido_value,
    normalize_category_path,
    parse_extra_headers,
    qido_study_category_path,
    qido_study_record,
    serialize_category_path,
    update_study_category,
    update_study_private_category,
)


DEFAULT_CATEGORY_PATH = "冷冻消融及随访/北大人民医院"
DEFAULT_TIMEOUT = 30.0


@dataclass(frozen=True)
class StudyTarget:
    patient_id: str
    study_id: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fix the category path for specific patient/study combinations by updating "
            "both dcm4chee access control and the study-level 77771027 field."
        )
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--category-path", default=DEFAULT_CATEGORY_PATH)
    parser.add_argument("--username", default="hygea")
    parser.add_argument("--password", default="hygea")
    parser.add_argument("--header", action="append", default=[])
    parser.add_argument("--cookie")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        help="Target in the form patientID:studyID. Repeat this option for multiple studies.",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=Path(__file__).with_name("fix_specific_series_category.log"),
    )
    return parser.parse_args()


def qido_studies_by_patient_id(
    base_url: str,
    patient_id: str,
    *,
    timeout: float,
    auth_header: str | None,
    extra_headers: dict[str, str],
) -> list[dict]:
    base = base_url.rstrip("/")
    encoded_patient_id = quote(patient_id, safe="")
    url = (
        f"{base}/studies?00100020={encoded_patient_id}"
        "&includefield=0020000D&includefield=00200010&includefield=00100020"
        "&limit=200&offset=0"
    )
    request = build_request(url, auth_header=auth_header, extra_headers=extra_headers)

    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except HTTPError as exc:
        raise RuntimeError(f"Failed to query studies for patient {patient_id} ({exc.code}): {exc.reason}") from exc
    except URLError as exc:
        raise RuntimeError(f"Failed to query studies for patient {patient_id}: {exc.reason}") from exc

    return json.loads(payload.decode("utf-8")) if payload else []


def find_matching_study_uid(
    base_url: str,
    target: StudyTarget,
    *,
    timeout: float,
    auth_header: str | None,
    extra_headers: dict[str, str],
) -> str:
    studies = qido_studies_by_patient_id(
        base_url,
        target.patient_id,
        timeout=timeout,
        auth_header=auth_header,
        extra_headers=extra_headers,
    )

    for study in studies:
        study_uid = extract_qido_value(study, "0020000D") or ""
        study_id = (extract_qido_value(study, "00200010") or "").strip()
        if not study_uid:
            continue

        if study_id == target.study_id:
            return study_uid

    raise RuntimeError(
        f"No study found for patientID={target.patient_id} with studyID={target.study_id}"
    )


def parse_targets(values: list[str]) -> list[StudyTarget]:
    targets: list[StudyTarget] = []

    for raw_value in values:
        text = str(raw_value or "").strip()
        if not text:
            continue

        if ":" not in text:
            raise ValueError(f"Invalid --target value: {raw_value}. Expected patientID:studyID")

        patient_id, study_id = text.split(":", 1)
        patient_id = patient_id.strip()
        study_id = study_id.strip()

        if not patient_id or not study_id:
            raise ValueError(f"Invalid --target value: {raw_value}. Expected patientID:studyID")

        targets.append(StudyTarget(patient_id=patient_id, study_id=study_id))

    if not targets:
        raise ValueError("At least one --target patientID:studyID is required")

    return targets


def main() -> int:
    args = parse_args()
    category_path = normalize_category_path(args.category_path)
    if not category_path:
        raise SystemExit("--category-path cannot be empty")
    targets = parse_targets(args.target)

    auth_header = basic_auth_header(args.username, args.password)
    extra_headers = parse_extra_headers(args.header)
    if args.cookie:
        extra_headers["Cookie"] = args.cookie

    args.log_file.write_text("", encoding="utf-8")

    for target in targets:
        study_uid = find_matching_study_uid(
            args.base_url,
            target,
            timeout=args.timeout,
            auth_header=auth_header,
            extra_headers=extra_headers,
        )

        current_value = qido_study_category_path(
            args.base_url,
            study_uid,
            timeout=args.timeout,
            auth_header=auth_header,
            extra_headers=extra_headers,
        )
        print(
            f"[MATCH] patientID={target.patient_id} studyID={target.study_id} "
            f"studyUID={study_uid} current={current_value or '(empty)'}"
        )

        if args.dry_run:
            continue

        stored_category = serialize_category_path(category_path)
        update_study_private_category(
            args.base_url,
            study_uid,
            stored_category,
            timeout=args.timeout,
            auth_header=auth_header,
            extra_headers=extra_headers,
        )
        update_study_category(
            args.base_url,
            study_uid,
            stored_category,
            timeout=args.timeout,
            auth_header=auth_header,
            extra_headers=extra_headers,
        )
        verified_value = qido_study_category_path(
            args.base_url,
            study_uid,
            timeout=args.timeout,
            auth_header=auth_header,
            extra_headers=extra_headers,
        )
        study_record = qido_study_record(
            args.base_url,
            study_uid,
            timeout=args.timeout,
            auth_header=auth_header,
            extra_headers=extra_headers,
        )
        private_value = extract_qido_value(study_record or {}, "77771027")

        print(
            f"[UPDATED] patientID={target.patient_id} studyID={target.study_id} "
            f"studyUID={study_uid} qido={verified_value or '(empty)'} "
            f"private={private_value or '(empty)'}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
