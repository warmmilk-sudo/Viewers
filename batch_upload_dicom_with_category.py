from __future__ import annotations

import argparse
import fnmatch
import json
import logging
import shutil
import tempfile
import warnings
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

import pydicom
from pydicom.dataset import Dataset
from pydicom.errors import InvalidDicomError
from backfill_category_path import (
    DEFAULT_BASE_URL as DEFAULT_VIEWER_BASE_URL,
    basic_auth_header as build_http_auth_header,
    parse_extra_headers as parse_http_headers,
    qido_study_category_path,
    serialize_category_path,
    update_study_category,
)

from upload_ablation_folders import (
    DEFAULT_ASSOCIATION_TIMEOUT,
    DEFAULT_DICOM_BACKOFF,
    DEFAULT_DICOM_CALLED_AET,
    DEFAULT_DICOM_CALLING_AET,
    DEFAULT_DICOM_HOST,
    DEFAULT_DICOM_PORT,
    DEFAULT_DICOM_RETRIES,
    DEFAULT_DIMSE_TIMEOUT,
    DEFAULT_LOG_FILE,
    DEFAULT_MAX_RETRIES,
    DEFAULT_MAX_WORKERS,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_RETRY_DELAY,
    DEFAULT_VERIFY_TIMEOUT,
    WorkerSummary,
    iter_series_dirs,
    iter_study_dirs,
    read_dicom_file,
    process_study_dir,
    setup_logging,
)


DEFAULT_CATEGORY_PATH = ""
DEFAULT_PRIVATE_CREATOR = "DCM4CHEE Archive 5"
PRIVATE_GROUP = 0x7777
PRIVATE_CATEGORY_ELEMENT = 0x27

_IGNORED_DICOM_WARNING_PATTERNS = (
    r"Value 'GB18030' cannot be used as code extension, ignoring it",
    r"Failed to encode value with encodings: latin_1 - using replacement characters in encoded string",
    r"Invalid value for VR UI: .*",
)

for _warning_pattern in _IGNORED_DICOM_WARNING_PATTERNS:
    warnings.filterwarnings(
        "ignore",
        message=_warning_pattern,
        category=UserWarning,
        module=r"pydicom\.(charset|valuerep)",
    )


@dataclass(frozen=True)
class CategoryRule:
    pattern: str
    category_path: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Batch upload DICOM folders via native DICOM C-STORE and synchronize "
            "a configurable category path to a private 7777 tag and verify it via QIDO."
        )
    )
    parser.add_argument(
        "--root",
        type=Path,
        required=True,
        help="Root directory that contains the folders to upload.",
    )
    parser.add_argument(
        "--category-path",
        default=DEFAULT_CATEGORY_PATH,
        help="Default category path synchronized to dcm4chee and exposed to Viewer as categoryPath, for example 冷冻消融及随访/北大人民医院.",
    )
    parser.add_argument(
        "--category-map",
        type=Path,
        help=(
            "Optional JSON file that maps relative-path glob patterns to category paths. "
            "Supports either {\"pattern\": \"category/path\"} or [{\"match\": \"...\", \"categoryPath\": \"...\"}]."
        ),
    )
    parser.add_argument(
        "--private-creator",
        default=DEFAULT_PRIVATE_CREATOR,
        help="Private creator used in staged copies when writing (7777,1027). Defaults to the dcm4chee archive creator string.",
    )
    parser.add_argument(
        "--staging-root",
        type=Path,
        help=(
            "Optional directory where staged copies are written. If omitted, a temporary directory is used "
            "and removed automatically after upload."
        ),
    )
    parser.add_argument(
        "--dicom-host",
        default=DEFAULT_DICOM_HOST,
        help="IP or hostname of the DICOM SCP.",
    )
    parser.add_argument(
        "--dicom-port",
        type=int,
        default=DEFAULT_DICOM_PORT,
        help="TCP port of the DICOM SCP.",
    )
    parser.add_argument(
        "--called-aet",
        "--aet",
        dest="called_aet",
        default=DEFAULT_DICOM_CALLED_AET,
        help="Called AE title on the PACS side.",
    )
    parser.add_argument(
        "--calling-aet",
        default=DEFAULT_DICOM_CALLING_AET,
        help="Calling AE title used by this script.",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=DEFAULT_LOG_FILE,
        help="Write error details to this log file.",
    )
    parser.add_argument(
        "--association-timeout",
        "--connect-timeout",
        dest="association_timeout",
        type=float,
        default=DEFAULT_ASSOCIATION_TIMEOUT,
        help="Seconds to wait while establishing a DICOM association.",
    )
    parser.add_argument(
        "--dimse-timeout",
        "--read-timeout",
        dest="dimse_timeout",
        type=float,
        default=DEFAULT_DIMSE_TIMEOUT,
        help="Seconds to wait for DICOM DIMSE responses before treating them as slow.",
    )
    parser.add_argument(
        "--verify-timeout",
        type=float,
        default=DEFAULT_VERIFY_TIMEOUT,
        help="Seconds to keep polling after a slow or uncertain upload to see whether the instance appeared anyway.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=DEFAULT_POLL_INTERVAL,
        help="Seconds between existence checks while waiting for a slow server.",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=DEFAULT_RETRY_DELAY,
        help="Seconds to wait between retry attempts.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=DEFAULT_MAX_WORKERS,
        help="Maximum number of parallel workers per level; 0 means auto-scale by CPU and queue size.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help="Maximum retry rounds for files that are still missing after verification.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=False,
        help="Skip files that already exist in PACS instead of reuploading them.",
    )
    parser.add_argument(
        "--dicom-retries",
        type=int,
        default=DEFAULT_DICOM_RETRIES,
        help="Maximum retry rounds for transient DICOM connection or association failures while checking or uploading a file.",
    )
    parser.add_argument(
        "--dicom-backoff",
        type=float,
        default=DEFAULT_DICOM_BACKOFF,
        help="Base seconds used for exponential backoff on transient DICOM failures.",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_false",
        dest="recursive",
        default=True,
        help="Only inspect files directly inside each folder.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        dest="recursive",
        help="Recurse into nested subdirectories when collecting DICOM files.",
    )
    parser.add_argument(
        "--viewer-base-url",
        default=DEFAULT_VIEWER_BASE_URL,
        help="Base dcm4chee REST URL used to sync and verify study category metadata.",
    )
    parser.add_argument(
        "--viewer-username",
        default="hygea",
        help="Optional HTTP basic auth username for the dcm4chee REST endpoint.",
    )
    parser.add_argument(
        "--viewer-password",
        default="hygea",
        help="Optional HTTP basic auth password for the dcm4chee REST endpoint.",
    )
    parser.add_argument(
        "--viewer-header",
        action="append",
        default=[],
        help="Optional extra HTTP header for viewer REST calls in the form 'Name: value'. Can be repeated.",
    )
    parser.add_argument(
        "--viewer-cookie",
        help="Optional Cookie header value for viewer REST calls.",
    )
    parser.add_argument(
        "--viewer-timeout",
        type=float,
        default=30.0,
        help="Seconds to wait for dcm4chee REST updates and QIDO verification calls.",
    )
    return parser.parse_args()


def normalize_category_path(value: str) -> str:
    segments = [
        segment.strip()
        for segment in _split_category_path(value)
        if segment.strip()
    ]
    return "/".join(segments)


def _split_category_path(value: str) -> List[str]:
    if value is None:
        return []

    text = str(value).strip().replace("\\", "/")
    if not text:
        return []

    for delimiter in ("→", "｜", ">", "::"):
        text = text.replace(delimiter, "/")

    parts: List[str] = []
    for fragment in text.split("/"):
        fragment = fragment.strip()
        if fragment:
            parts.append(fragment)
    return parts


def load_category_rules(path: Optional[Path]) -> List[CategoryRule]:
    if path is None:
        return []

    raw = json.loads(path.read_text(encoding="utf-8"))
    rules: List[CategoryRule] = []

    if isinstance(raw, dict):
        for pattern, category in raw.items():
            if pattern == "default":
                continue
            rules.append(
                CategoryRule(
                    pattern=str(pattern),
                    category_path=normalize_category_path(str(category)),
                )
            )
        return rules

    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                raise ValueError("category-map list entries must be objects")
            pattern = item.get("match") or item.get("pattern")
            category = item.get("categoryPath") or item.get("category_path") or item.get("value")
            if not pattern or not category:
                raise ValueError("category-map entries require match/pattern and categoryPath/category_path/value")
            rules.append(
                CategoryRule(
                    pattern=str(pattern),
                    category_path=normalize_category_path(str(category)),
                )
            )
        return rules

    raise ValueError("category-map JSON must be either an object or a list")


def resolve_category_path(
    relative_path: Path,
    rules: Sequence[CategoryRule],
    default_category_path: str,
) -> str:
    rel_text = relative_path.as_posix()

    for rule in rules:
        if fnmatch.fnmatchcase(rel_text, rule.pattern):
            return rule.category_path

    return default_category_path


def collect_study_category_map(
    source_root: Path,
    rules: Sequence[CategoryRule],
    default_category_path: str,
) -> dict[str, str]:
    study_categories: dict[str, str] = {}

    for source_file in sorted(source_root.rglob("*"), key=lambda p: str(p).lower()):
        if not source_file.is_file():
            continue

        record = read_dicom_file(source_file)
        if not record:
            continue

        relative_path = source_file.relative_to(source_root)
        category_path = resolve_category_path(relative_path, rules, default_category_path)
        existing = study_categories.get(record.study_instance_uid)
        if existing and existing != category_path:
            logging.getLogger("batch_upload_dicom_with_category").warning(
                "[WARN] study=%s has mixed category paths (%s vs %s); keeping %s",
                record.study_instance_uid,
                existing,
                category_path,
                existing,
            )
            continue

        study_categories[record.study_instance_uid] = category_path

    return study_categories


def apply_category_metadata(
    dataset: Dataset,
    category_path: str,
    private_creator: str,
) -> None:
    normalized_category = normalize_category_path(category_path)
    stored_category = serialize_category_path(normalized_category)

    block = dataset.private_block(PRIVATE_GROUP, private_creator, create=True)
    block.add_new(PRIVATE_CATEGORY_ELEMENT, "LO", stored_category)


def stage_dicom_file(
    source_file: Path,
    destination_file: Path,
    category_path: str,
    private_creator: str,
    logger: logging.Logger,
) -> bool:
    destination_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        dataset = pydicom.dcmread(source_file, force=True)
    except InvalidDicomError:
        shutil.copy2(source_file, destination_file)
        return False

    if any(ord(character) > 127 for character in serialize_category_path(category_path)):
        dataset.SpecificCharacterSet = "ISO_IR 192"

    apply_category_metadata(
        dataset,
        category_path,
        private_creator,
    )
    pydicom.dcmwrite(destination_file, dataset, write_like_original=True)
    return True


def stage_source_tree(
    source_root: Path,
    staging_root: Path,
    rules: Sequence[CategoryRule],
    default_category_path: str,
    private_creator: str,
    logger: logging.Logger,
) -> tuple[int, int]:
    if staging_root.exists():
        if not staging_root.is_dir():
            raise NotADirectoryError(f"Staging root is not a directory: {staging_root}")
        if any(staging_root.iterdir()):
            raise FileExistsError(f"Staging root is not empty: {staging_root}")
    else:
        staging_root.mkdir(parents=True, exist_ok=True)

    copied_files = 0
    categorized_files = 0

    for source_file in sorted(source_root.rglob("*"), key=lambda p: str(p).lower()):
        if not source_file.is_file():
            continue

        relative_path = source_file.relative_to(source_root)
        destination_file = staging_root / relative_path
        category_path = resolve_category_path(relative_path, rules, default_category_path)
        if stage_dicom_file(
            source_file,
            destination_file,
            category_path,
            private_creator,
            logger=logger,
        ):
            categorized_files += 1
        copied_files += 1

    return copied_files, categorized_files


def upload_staged_root(
    stage_root: Path,
    args: argparse.Namespace,
    logger: logging.Logger,
    *,
    category_rules: Sequence[CategoryRule],
    default_category_path: str,
) -> WorkerSummary:
    study_dirs = iter_study_dirs(stage_root)
    logger.info("[ROOT] %s -> %s study dir(s)", stage_root, len(study_dirs))

    total_study_dirs = 0
    total_series_dirs = 0
    total_groups = 0
    total_files = 0
    total_existing_files = 0
    total_stored_files = 0
    total_skipped_files = 0
    total_failed_files = 0
    total_failed_study_dirs = 0

    for study_dir in study_dirs:
        total_study_dirs += 1
        logger.info("[STUDY] processing %s", study_dir.name)
        try:
            summary = process_study_dir(study_dir, args, logger)
            total_groups += summary.study_groups
            total_files += summary.files
            total_existing_files += summary.existing_files
            total_stored_files += summary.stored_files
            total_skipped_files += summary.skipped_files
            total_failed_files += summary.failed_files
            total_series_dirs += len(iter_series_dirs(study_dir))

            study_categories = collect_study_category_map(study_dir, category_rules, default_category_path)
            if study_categories:
                logger.info(
                    "[SYNC] study dir=%s study(s)=%s syncing study access-control to dcm4chee",
                    study_dir.name,
                    len(study_categories),
                )
                updated = 0
                for study_uid, category_path in study_categories.items():
                    try:
                        update_study_category(
                            args.viewer_base_url,
                            study_uid,
                            serialize_category_path(category_path),
                            timeout=args.viewer_timeout,
                            auth_header=args.viewer_auth_header,
                            extra_headers=args.viewer_extra_headers,
                        )
                        updated += 1
                        reported_category = qido_study_category_path(
                            args.viewer_base_url,
                            study_uid,
                            timeout=args.viewer_timeout,
                            auth_header=args.viewer_auth_header,
                            extra_headers=args.viewer_extra_headers,
                        )
                        if normalize_category_path(reported_category or "") == normalize_category_path(category_path):
                            logger.info(
                                "[VERIFY] study=%s QIDO 77771027=%s",
                                study_uid,
                                reported_category,
                            )
                        elif reported_category:
                            logger.warning(
                                "[WARN] study=%s QIDO 77771027 mismatch expected=%s got=%s",
                                study_uid,
                                category_path,
                                reported_category,
                            )
                        else:
                            logger.warning(
                                "[WARN] study=%s QIDO 77771027 missing after sync; expected=%s",
                                study_uid,
                                category_path,
                            )
                    except Exception as exc:
                        logger.warning(
                            "[WARN] failed to sync viewer category for study=%s path=%s: %s",
                            study_uid,
                            category_path,
                            exc,
                        )
                logger.info(
                    "[SYNC] study dir=%s viewer category updated for %s study/studies",
                    study_dir.name,
                    updated,
                )
        except Exception as exc:
            total_failed_study_dirs += 1
            logger.exception("[WARN] study dir=%s failed and will be skipped: %s", study_dir, exc)
            continue

    logger.info("[ROOT] failed study dir(s) skipped=%s", total_failed_study_dirs)

    return WorkerSummary(
        series_dir=stage_root,
        study_groups=total_groups,
        files=total_files,
        existing_files=total_existing_files,
        stored_files=total_stored_files,
        skipped_files=total_skipped_files,
        failed_files=total_failed_files,
    )


def ensure_root_is_valid(root: Path) -> None:
    if not root.exists():
        raise FileNotFoundError(f"Root directory does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Not a directory: {root}")


def main() -> int:
    args = parse_args()
    logger = setup_logging(args.log_file)

    try:
        ensure_root_is_valid(args.root)

        default_category_path = normalize_category_path(args.category_path)
        if not default_category_path:
            raise ValueError("--category-path cannot be empty")

        viewer_auth_header = build_http_auth_header(args.viewer_username, args.viewer_password)
        viewer_extra_headers = parse_http_headers(args.viewer_header)
        if args.viewer_cookie:
            viewer_extra_headers["Cookie"] = args.viewer_cookie

        logger.info(
            "[META] staged copies will include (7777,1027) under DCM4CHEE Archive 5; study access-control will be verified via QIDO 77771027"
        )
        category_rules = load_category_rules(args.category_map)

        if args.staging_root is None:
            temp_dir = tempfile.TemporaryDirectory(prefix="hygea_dicom_stage_")
            staging_context = temp_dir
            stage_root = Path(temp_dir.name) / args.root.name
        else:
            staging_context = nullcontext()
            stage_root = args.staging_root / args.root.name
            if stage_root.exists() and any(stage_root.iterdir()):
                raise FileExistsError(f"Staging destination already exists and is not empty: {stage_root}")
            stage_root.parent.mkdir(parents=True, exist_ok=True)

        with staging_context:
            logger.info("[STAGE] source=%s staging=%s", args.root, stage_root)
            staged_files, categorized_files = stage_source_tree(
                args.root,
                stage_root,
                category_rules,
                default_category_path,
                args.private_creator,
                logger=logger,
            )
            logger.info(
                "[STAGE] prepared %s file(s), viewer classification will be synced via dcm4chee",
                staged_files,
            )

            upload_args = argparse.Namespace(**vars(args))
            upload_args.root = stage_root
            upload_args.viewer_auth_header = viewer_auth_header
            upload_args.viewer_extra_headers = viewer_extra_headers

            summary = upload_staged_root(
                stage_root,
                upload_args,
                logger,
                category_rules=category_rules,
                default_category_path=default_category_path,
            )
            logger.info(
                "[DONE] study groups=%s files=%s existing=%s stored=%s skipped=%s failed=%s",
                summary.study_groups,
                summary.files,
                summary.existing_files,
                summary.stored_files,
                summary.skipped_files,
                summary.failed_files,
            )

        return 0
    except Exception as exc:
        logger.exception("Fatal error while preparing batch upload: %s", exc)
        logger.error("[FATAL] %s; see log file: %s", exc, args.log_file)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
