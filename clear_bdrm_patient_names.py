from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from backfill_category_path import (
    DEFAULT_BASE_URL,
    basic_auth_header,
    build_request,
    extract_qido_value,
    parse_extra_headers,
    setup_logging,
)


DEFAULT_TIMEOUT = 60.0
DEFAULT_PAGE_SIZE = 200
DEFAULT_MAX_WORKERS = 4
DEFAULT_PREFIX = "bdrm"
DEFAULT_CLEAR_VALUE = " "
DEFAULT_RETRIES = 3
PRIVATE_CREATOR = "DCM4CHEE Archive 5"


@dataclass(frozen=True)
class PatientMatch:
    patient_pk: str
    patient_id: str
    issuer_of_patient_id: str
    patient_name: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Find patients whose PatientName starts with the given prefix and clear "
            "their PACS PatientName through the dcm4chee patient update API."
        )
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--prefix", default=DEFAULT_PREFIX)
    parser.add_argument("--username", default="hygea")
    parser.add_argument("--password", default="hygea")
    parser.add_argument("--header", action="append", default=[])
    parser.add_argument("--cookie")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES)
    parser.add_argument(
        "--clear-value",
        default=DEFAULT_CLEAR_VALUE,
        help=(
            "Value written to PatientName. Defaults to a single space because "
            "dcm4chee normalizes it to an empty PN while rejecting a truly empty string."
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--log-file",
        type=Path,
        default=Path(__file__).with_name("clear_bdrm_patient_names.log"),
    )
    return parser.parse_args()


def extract_patient_name(item: dict) -> str:
    raw = item.get("00100010") or item.get("00100010".lower()) or {}
    values = raw.get("Value") or []
    if not values:
        return ""

    first = values[0]
    if isinstance(first, dict):
        return str(first.get("Alphabetic") or "").strip()

    return str(first).strip()


def qido_patients_by_name_prefix(
    base_url: str,
    prefix: str,
    *,
    page_size: int,
    timeout: float,
    auth_header: str | None,
    extra_headers: dict[str, str],
) -> list[PatientMatch]:
    base = base_url.rstrip("/")
    offset = 0
    matches: list[PatientMatch] = []
    seen_patient_pks: set[str] = set()
    query_value = f"{prefix}*"

    while True:
        url = (
            f"{base}/patients?PatientName={query_value}"
            "&includefield=00100010"
            "&includefield=00100020"
            "&includefield=00100021"
            "&includefield=77771016"
            f"&limit={page_size}&offset={offset}"
        )
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
            patient_pk = extract_qido_value(item, "77771016") or ""
            patient_id = extract_qido_value(item, "00100020") or ""
            issuer = extract_qido_value(item, "00100021") or ""
            patient_name = extract_patient_name(item)

            if not patient_pk or patient_pk in seen_patient_pks:
                continue

            seen_patient_pks.add(patient_pk)
            matches.append(
                PatientMatch(
                    patient_pk=patient_pk,
                    patient_id=patient_id,
                    issuer_of_patient_id=issuer,
                    patient_name=patient_name,
                )
            )

        if len(items) < page_size:
            break

        offset += len(items)

    return matches


def update_patient_name(
    base_url: str,
    patient: PatientMatch,
    *,
    clear_value: str,
    timeout: float,
    auth_header: str | None,
    extra_headers: dict[str, str],
) -> None:
    payload = {
        "00080005": {"vr": "CS", "Value": ["GB18030"]},
        "00100020": {"vr": "LO", "Value": [patient.patient_id]},
        "00100010": {"vr": "PN", "Value": [{"Alphabetic": clear_value}]},
        "77770010": {"vr": "LO", "Value": [PRIVATE_CREATOR]},
        "77771016": {"vr": "LO", "Value": [patient.patient_pk]},
    }
    if patient.issuer_of_patient_id:
        payload["00100021"] = {"vr": "LO", "Value": [patient.issuer_of_patient_id]}

    url = f"{base_url.rstrip('/')}/patients/id/{patient.patient_pk}"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = build_request(
        url,
        method="PUT",
        body=body,
        auth_header=auth_header,
        extra_headers={
            **extra_headers,
            "Content-Type": "application/dicom+json",
        },
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            response.read()
            if response.status not in (200, 202, 204):
                raise RuntimeError(f"Unexpected status {response.status}")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(
            f"Failed to clear PatientName for patientID={patient.patient_id} pk={patient.patient_pk} "
            f"({exc.code}): {exc.reason} {detail}".strip()
        ) from exc
    except URLError as exc:
        raise RuntimeError(
            f"Failed to clear PatientName for patientID={patient.patient_id} pk={patient.patient_pk}: {exc.reason}"
        ) from exc


def verify_patient_name(
    base_url: str,
    patient_id: str,
    *,
    timeout: float,
    auth_header: str | None,
    extra_headers: dict[str, str],
) -> str:
    url = (
        f"{base_url.rstrip('/')}/patients?PatientID={patient_id}"
        "&includefield=00100010&limit=1&offset=0"
    )
    request = build_request(url, auth_header=auth_header, extra_headers=extra_headers)
    with urlopen(request, timeout=timeout) as response:
        payload = response.read()

    items = json.loads(payload.decode("utf-8")) if payload else []
    if not items:
        return ""
    return extract_patient_name(items[0])


def clear_patient_with_retry(
    base_url: str,
    patient: PatientMatch,
    *,
    clear_value: str,
    timeout: float,
    auth_header: str | None,
    extra_headers: dict[str, str],
    retries: int,
) -> str:
    last_error: Exception | None = None
    attempts = max(1, retries)

    for attempt in range(1, attempts + 1):
        try:
            update_patient_name(
                base_url,
                patient,
                clear_value=clear_value,
                timeout=timeout,
                auth_header=auth_header,
                extra_headers=extra_headers,
            )
            verified_name = verify_patient_name(
                base_url,
                patient.patient_id,
                timeout=timeout,
                auth_header=auth_header,
                extra_headers=extra_headers,
            )
            if verified_name:
                raise RuntimeError(
                    f"verification still returned patientName={verified_name!r} after update"
                )
            return ""
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(min(2 * attempt, 5))

    assert last_error is not None
    raise last_error


def main() -> int:
    args = parse_args()
    logger = setup_logging(args.log_file)

    auth_header = basic_auth_header(args.username, args.password)
    extra_headers = parse_extra_headers(args.header)
    if args.cookie:
        extra_headers["Cookie"] = args.cookie

    prefix = str(args.prefix or "").strip()
    if not prefix:
        raise SystemExit("--prefix cannot be empty")

    clear_value = args.clear_value
    if clear_value == "":
        raise SystemExit("--clear-value cannot be truly empty; use the default single space")

    patients = qido_patients_by_name_prefix(
        args.base_url,
        prefix,
        page_size=max(1, int(args.page_size)),
        timeout=args.timeout,
        auth_header=auth_header,
        extra_headers=extra_headers,
    )

    if not patients:
        logger.info("[DONE] no patients matched PatientName prefix=%s", prefix)
        return 0

    logger.info("[PLAN] matchedPatients=%s prefix=%s", len(patients), prefix)
    for patient in patients:
        logger.info(
            "[MATCH] patientName=%s patientID=%s issuer=%s patientPK=%s",
            patient.patient_name or "(empty)",
            patient.patient_id or "(empty)",
            patient.issuer_of_patient_id or "(empty)",
            patient.patient_pk,
        )

    if args.dry_run:
        return 0

    completed = 0
    max_workers = max(1, int(args.max_workers))
    retries = max(1, int(args.retries))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(
                clear_patient_with_retry,
                args.base_url,
                patient,
                clear_value=clear_value,
                timeout=args.timeout,
                auth_header=auth_header,
                extra_headers=extra_headers,
                retries=retries,
            ): patient
            for patient in patients
        }

        for future in as_completed(future_map):
            patient = future_map[future]
            try:
                future.result()
                completed += 1
                logger.info(
                    "[UPDATED] %s/%s patientID=%s patientPK=%s",
                    completed,
                    len(patients),
                    patient.patient_id or "(empty)",
                    patient.patient_pk,
                )
            except Exception as exc:
                logger.error(
                    "[FAIL] patientID=%s patientPK=%s error=%s",
                    patient.patient_id,
                    patient.patient_pk,
                    exc,
                )

    logger.info("[DONE] updated=%s total=%s", completed, len(patients))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
