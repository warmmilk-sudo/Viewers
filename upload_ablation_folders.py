from __future__ import annotations

import argparse
import logging
import os
import threading
import time
import warnings
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Optional

import pydicom
from pydicom.dataset import Dataset
from pydicom.errors import InvalidDicomError
from pynetdicom import AE
from pynetdicom.sop_class import StudyRootQueryRetrieveInformationModelFind
try:
    from tqdm.auto import tqdm
except ImportError:  # pragma: no cover - fallback for minimal runtime environments.
    class _NullTqdm:
        def __init__(self, *args, **kwargs):
            self.total = kwargs.get("total")

        def update(self, *_args, **_kwargs):
            return None

        def set_postfix_str(self, *_args, **_kwargs):
            return None

        def refresh(self):
            return None

        def close(self):
            return None

    def tqdm(*args, **kwargs):
        return _NullTqdm(*args, **kwargs)


DEFAULT_DICOM_HOST = "172.16.82.11"
DEFAULT_DICOM_PORT = 11112
DEFAULT_DICOM_CALLED_AET = "DCM4CHEE"
DEFAULT_DICOM_CALLING_AET = "PYNETDICOM"
DEFAULT_LOG_FILE = Path(__file__).with_name("upload_ablation_folders.log")
DEFAULT_ASSOCIATION_TIMEOUT = 10.0
DEFAULT_DIMSE_TIMEOUT = 120.0
DEFAULT_VERIFY_TIMEOUT = 600.0
DEFAULT_POLL_INTERVAL = 5.0
DEFAULT_RETRY_DELAY = 5.0
DEFAULT_MAX_WORKERS = 4
DEFAULT_MAX_RETRIES = 20
DEFAULT_DICOM_RETRIES = 5
DEFAULT_DICOM_BACKOFF = 2.0
AUTO_FILE_WORKER_MULTIPLIER = 8
AUTO_SERIES_WORKER_MULTIPLIER = 4
AUTO_WORKER_MINIMUM = 4
AUTO_WORKER_CAP = 64

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
class DicomFile:
    path: Path
    sop_class_uid: str
    study_instance_uid: str
    series_instance_uid: str
    sop_instance_uid: str


@dataclass(frozen=True)
class StudyBatch:
    study_instance_uid: str
    files: List[DicomFile]


@dataclass(frozen=True)
class WorkerSummary:
    series_dir: Path
    study_groups: int
    files: int
    existing_files: int
    stored_files: int
    skipped_files: int
    failed_files: int


ProgressCallback = Callable[[Path, str, int, int, str, Optional[str]], None]


def normalize_aet(value: str) -> str:
    aet = value.strip().upper()
    if not aet:
        raise ValueError("AE title cannot be empty")
    return aet[:16]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Upload DICOM series folders under a root directory to a PACS via "
            "native DICOM C-FIND / C-STORE with parallel uploads and retries."
        )
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(r"F:\ablation_data\20260115"),
        help="Root directory that contains the folders to upload.",
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
        "--http-retries",
        dest="dicom_retries",
        type=int,
        default=DEFAULT_DICOM_RETRIES,
        help="Maximum retry rounds for transient DICOM connection or association failures while checking or uploading a file.",
    )
    parser.add_argument(
        "--dicom-backoff",
        "--http-backoff",
        dest="dicom_backoff",
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
    return parser.parse_args()


def iter_study_dirs(root: Path) -> List[Path]:
    if not root.exists():
        raise FileNotFoundError(f"Root directory does not exist: {root}")

    if not root.is_dir():
        raise NotADirectoryError(f"Not a directory: {root}")

    child_dirs = sorted([path for path in root.iterdir() if path.is_dir()], key=lambda p: p.name.lower())
    if not child_dirs:
        return [root]

    has_grandchildren = any(
        any(grandchild.is_dir() for grandchild in child.iterdir())
        for child in child_dirs
    )
    if has_grandchildren:
        return child_dirs

    return [root]


def iter_series_dirs(study_dir: Path) -> List[Path]:
    child_dirs = sorted([path for path in study_dir.iterdir() if path.is_dir()], key=lambda p: p.name.lower())
    if child_dirs:
        return child_dirs
    return [study_dir]


def collect_files(batch_dir: Path, recursive: bool) -> List[Path]:
    if recursive:
        files = [path for path in batch_dir.rglob("*") if path.is_file()]
    else:
        files = [path for path in batch_dir.iterdir() if path.is_file()]

    return sorted(files, key=lambda p: str(p).lower())


def read_dicom_file(file_path: Path) -> Optional[DicomFile]:
    try:
        with warnings.catch_warnings():
            for pattern in _IGNORED_DICOM_WARNING_PATTERNS:
                warnings.filterwarnings("ignore", message=pattern)
            dataset = pydicom.dcmread(str(file_path), stop_before_pixels=True, force=True)
            study_instance_uid = getattr(dataset, "StudyInstanceUID", None)
            series_instance_uid = getattr(dataset, "SeriesInstanceUID", None)
            sop_instance_uid = getattr(dataset, "SOPInstanceUID", None)
            sop_class_uid = getattr(dataset, "SOPClassUID", None)
    except (InvalidDicomError, OSError, ValueError):
        return None

    if not study_instance_uid or not series_instance_uid or not sop_instance_uid or not sop_class_uid:
        return None

    return DicomFile(
        path=file_path,
        sop_class_uid=str(sop_class_uid),
        study_instance_uid=str(study_instance_uid),
        series_instance_uid=str(series_instance_uid),
        sop_instance_uid=str(sop_instance_uid),
    )


def group_files_by_study(files: Iterable[Path]) -> List[StudyBatch]:
    grouped: "OrderedDict[str, List[DicomFile]]" = OrderedDict()

    for file_path in files:
        record = read_dicom_file(file_path)
        if not record:
            continue

        grouped.setdefault(record.study_instance_uid, []).append(record)

    return [StudyBatch(study_instance_uid=uid, files=records) for uid, records in grouped.items()]


def setup_logging(log_file: Path) -> logging.Logger:
    class _ConsoleFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            return record.levelno < logging.WARNING

    logger = logging.getLogger("upload_ablation_folders")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("%(message)s"))
    console_handler.addFilter(_ConsoleFilter())
    logger.addHandler(console_handler)

    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(file_handler)

    return logger


def resolve_worker_count(
    task_count: int,
    manual_max_workers: int,
    *,
    cpu_multiplier: int,
    minimum: int,
    cap: int,
) -> int:
    if task_count <= 0:
        return 0

    if manual_max_workers and manual_max_workers > 0:
        return max(1, min(manual_max_workers, task_count))

    cpu_count = os.cpu_count() or 1
    auto_workers = max(minimum, cpu_count * cpu_multiplier)
    auto_workers = min(auto_workers, cap)
    return max(1, min(auto_workers, task_count))


def sleep_backoff(base_delay: float, attempt: int) -> None:
    delay = min(base_delay * (2 ** max(0, attempt - 1)), 30.0)
    time.sleep(max(0.5, delay))


def is_acceptable_c_store_status(status_code: Optional[int]) -> bool:
    if status_code is None:
        return False
    return status_code == 0x0000 or 0xB000 <= status_code <= 0xBFFF


def build_instance_query(record: DicomFile) -> Dataset:
    with warnings.catch_warnings():
        for pattern in _IGNORED_DICOM_WARNING_PATTERNS:
            warnings.filterwarnings("ignore", message=pattern)
        dataset = Dataset()
        dataset.QueryRetrieveLevel = "IMAGE"
        dataset.StudyInstanceUID = record.study_instance_uid
        dataset.SeriesInstanceUID = record.series_instance_uid
        dataset.SOPInstanceUID = record.sop_instance_uid
    return dataset


class DicomWorkerClient:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        called_aet: str,
        calling_aet: str,
        storage_sop_class_uids: Iterable[str],
        association_timeout: float,
        dimse_timeout: float,
    ) -> None:
        self.host = host
        self.port = port
        self.called_aet = normalize_aet(called_aet)
        self.calling_aet = normalize_aet(calling_aet)
        self.storage_sop_class_uids = tuple(dict.fromkeys(storage_sop_class_uids))
        self.association_timeout = association_timeout
        self.dimse_timeout = dimse_timeout
        self._local = threading.local()
        self._associations: list = []
        self._lock = threading.Lock()

    def _build_ae(self) -> AE:
        ae = AE(ae_title=self.calling_aet)
        ae.acse_timeout = self.association_timeout
        ae.dimse_timeout = self.dimse_timeout
        ae.network_timeout = self.dimse_timeout
        ae.requested_contexts = []
        for sop_class_uid in self.storage_sop_class_uids:
            ae.add_requested_context(sop_class_uid)
        ae.add_requested_context(StudyRootQueryRetrieveInformationModelFind)
        return ae

    def get_association(self):
        assoc = getattr(self._local, "assoc", None)
        if assoc is not None and assoc.is_established:
            return assoc

        if assoc is not None:
            try:
                assoc.release()
            except Exception:
                try:
                    assoc.abort()
                except Exception:
                    pass

        ae = getattr(self._local, "ae", None)
        if ae is None:
            ae = self._build_ae()
            self._local.ae = ae

        assoc = ae.associate(self.host, self.port, ae_title=self.called_aet)
        if not assoc.is_established:
            raise ConnectionError(
                f"Failed to establish DICOM association to {self.host}:{self.port} as "
                f"{self.calling_aet} -> {self.called_aet}"
            )

        self._local.assoc = assoc
        with self._lock:
            self._associations.append(assoc)
        return assoc

    def close_all(self) -> None:
        with self._lock:
            associations = list(self._associations)
            self._associations.clear()

        for assoc in associations:
            try:
                if assoc.is_established:
                    assoc.release()
            except Exception:
                try:
                    assoc.abort()
                except Exception:
                    pass


def probe_instance_exists(client: DicomWorkerClient, record: DicomFile) -> bool:
    assoc = client.get_association()
    query = build_instance_query(record)
    found = False

    for status, identifier in assoc.send_c_find(query, StudyRootQueryRetrieveInformationModelFind):
        code = getattr(status, "Status", None)
        if not status:
            raise RuntimeError("C-FIND returned no status")

        if code in (0xFF00, 0xFF01):
            if identifier is not None:
                found = True
            continue

        if code == 0x0000:
            return found

        if code == 0xFE00:
            raise RuntimeError("C-FIND was cancelled by the peer")

        raise RuntimeError(f"C-FIND failed with status 0x{code:04X}" if code is not None else "C-FIND failed")

    return found


def check_record_exists(
    client: DicomWorkerClient,
    record: DicomFile,
    logger: logging.Logger,
    dicom_retries: int,
    dicom_backoff: float,
) -> bool:
    last_error: Exception | None = None

    for attempt in range(1, max(1, dicom_retries) + 1):
        try:
            return probe_instance_exists(client, record)
        except Exception as exc:
            last_error = exc
            if attempt >= max(1, dicom_retries):
                break
            sleep_backoff(dicom_backoff, attempt)

    if last_error is not None:
        logger.warning("[WARN] existence check failed for %s: %s", record.sop_instance_uid, last_error)
    return False


def partition_existing_records(
    records: List[DicomFile],
    client: DicomWorkerClient,
    args: argparse.Namespace,
    logger: logging.Logger,
) -> tuple[List[DicomFile], List[DicomFile]]:
    if not records:
        return [], []

    max_workers = resolve_worker_count(
        len(records),
        args.max_workers,
        cpu_multiplier=AUTO_FILE_WORKER_MULTIPLIER,
        minimum=AUTO_WORKER_MINIMUM,
        cap=AUTO_WORKER_CAP,
    )

    existing: List[DicomFile] = []
    missing: List[DicomFile] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(
                check_record_exists,
                client,
                record,
                logger,
                args.dicom_retries,
                args.dicom_backoff,
            ): record
            for record in records
        }

        for future in as_completed(future_map):
            record = future_map[future]
            try:
                if future.result():
                    existing.append(record)
                else:
                    missing.append(record)
            except Exception as exc:
                logger.warning(
                    "[WARN] existence check failed for %s: %s",
                    record.sop_instance_uid,
                    exc,
                )
                missing.append(record)

    return existing, missing


def store_single_record(client: DicomWorkerClient, record: DicomFile) -> None:
    assoc = client.get_association()
    status = assoc.send_c_store(record.path)
    code = getattr(status, "Status", None)
    if is_acceptable_c_store_status(code):
        return
    raise RuntimeError(
        f"C-STORE failed with status 0x{code:04X}" if code is not None else "C-STORE failed without status"
    )


def store_single_record_with_retry(
    client: DicomWorkerClient,
    record: DicomFile,
    logger: logging.Logger,
    dicom_retries: int,
    dicom_backoff: float,
) -> None:
    last_error: Exception | None = None

    for attempt in range(1, max(1, dicom_retries) + 1):
        try:
            store_single_record(client, record)
            return
        except Exception as exc:
            last_error = exc
            try:
                if probe_instance_exists(client, record):
                    return
            except Exception as probe_exc:
                last_error = probe_exc

        if attempt >= max(1, dicom_retries):
            break
        sleep_backoff(dicom_backoff, attempt)

    if last_error is not None:
        raise last_error


def wait_for_instances_to_appear(
    client: DicomWorkerClient,
    records: List[DicomFile],
    verify_timeout: float,
    poll_interval: float,
    logger: logging.Logger,
) -> List[DicomFile]:
    pending = list(records)
    deadline = time.monotonic() + verify_timeout

    while pending:
        missing: List[DicomFile] = []
        for record in pending:
            try:
                if not probe_instance_exists(client, record):
                    missing.append(record)
            except Exception as exc:
                logger.warning(
                    "Existence check failed for %s in %s: %s",
                    record.sop_instance_uid,
                    record.path.parent,
                    exc,
                )
                missing.append(record)

        if not missing:
            return []

        if time.monotonic() >= deadline:
            return missing

        pending = missing
        time.sleep(max(0.5, poll_interval))


def process_series_dir(
    series_dir: Path,
    args: argparse.Namespace,
    logger: logging.Logger,
    progress_callback: Optional[ProgressCallback] = None,
    progress_position: Optional[int] = None,
) -> WorkerSummary:
    files = collect_files(series_dir, args.recursive)
    study_batches = group_files_by_study(files)
    storage_sop_class_uids = list(
        dict.fromkeys(
            record.sop_class_uid
            for batch in study_batches
            for record in batch.files
        )
    )
    if len(storage_sop_class_uids) > 127:
        logger.warning(
            "[WARN] %s has %s storage SOP classes; truncating to 127 to stay within the DICOM negotiation limit.",
            series_dir,
            len(storage_sop_class_uids),
        )
        storage_sop_class_uids = storage_sop_class_uids[:127]

    client = DicomWorkerClient(
        host=args.dicom_host,
        port=args.dicom_port,
        called_aet=args.called_aet,
        calling_aet=args.calling_aet,
        storage_sop_class_uids=storage_sop_class_uids,
        association_timeout=args.association_timeout,
        dimse_timeout=args.dimse_timeout,
    )
    progress_bar = None

    try:
        if not study_batches:
            logger.info("[SKIP] %s has no readable DICOM files.", series_dir)
            return WorkerSummary(
                series_dir=series_dir,
                study_groups=0,
                files=0,
                existing_files=0,
                stored_files=0,
                skipped_files=len(files),
                failed_files=0,
            )

        total_files = 0
        existing_files = 0
        stored_files = 0
        failed_files = 0
        skipped_files = len(files) - sum(len(batch.files) for batch in study_batches)
        progress_total = sum(len(batch.files) for batch in study_batches)
        processed_sop_instance_uids: set[str] = set()
        processed_count = 0
        overwrite_existing = not bool(getattr(args, "skip_existing", False))
        progress_bar = tqdm(
            total=progress_total,
            desc=series_dir.name,
            unit='file',
            position=progress_position or 0,
            leave=False,
            dynamic_ncols=True,
            mininterval=0.1,
            smoothing=0,
            bar_format='{n_fmt}/{total_fmt}',
        )

        def report_progress(record: DicomFile, status: str) -> None:
            nonlocal processed_count
            if record.sop_instance_uid in processed_sop_instance_uids:
                return

            processed_sop_instance_uids.add(record.sop_instance_uid)
            processed_count += 1
            progress_bar.update(1)
            if progress_callback is not None:
                progress_callback(
                    series_dir,
                    study_batch.study_instance_uid,
                    processed_count,
                    progress_total,
                    status,
                    record.path.name,
                )

        logger.info(
            "[SERIES] %s -> %s study group(s), %s file(s)",
            series_dir,
            len(study_batches),
            len(files),
        )
        if overwrite_existing:
            logger.info("[OVERWRITE] %s will reupload existing instances instead of skipping them.", series_dir.name)

        for study_batch in study_batches:
            pending = list(study_batch.files)
            total_files += len(pending)
            attempt = 1

            while pending:
                if overwrite_existing:
                    existing = []
                    missing = list(pending)
                else:
                    existing, missing = partition_existing_records(
                        pending,
                        client,
                        args,
                        logger,
                    )
                    if existing:
                        existing_files += len(existing)
                        logger.info(
                            "[SKIP] %s study=%s already exists: %s",
                            series_dir.name,
                            study_batch.study_instance_uid,
                            ", ".join(record.sop_instance_uid for record in existing),
                        )
                        for record in existing:
                            report_progress(record, "skip")

                if not missing:
                    break

                max_workers = resolve_worker_count(
                    len(missing),
                    args.max_workers,
                    cpu_multiplier=AUTO_FILE_WORKER_MULTIPLIER,
                    minimum=AUTO_WORKER_MINIMUM,
                    cap=AUTO_WORKER_CAP,
                )
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    future_map = {
                        executor.submit(
                            store_single_record_with_retry,
                client,
                record,
                logger,
                args.dicom_retries,
                args.dicom_backoff,
            ): record
            for record in missing
        }

                    for future in as_completed(future_map):
                        record = future_map[future]
                        try:
                            future.result()
                            report_progress(record, "uploaded")
                        except Exception as exc:
                            logger.warning(
                                "[WARN] %s study=%s sop=%s upload error: %s",
                                series_dir.name,
                                study_batch.study_instance_uid,
                                record.sop_instance_uid,
                                exc,
                            )

                uploaded_this_round = len(missing)

                missing = wait_for_instances_to_appear(
                    client,
                    missing,
                    args.verify_timeout,
                    args.poll_interval,
                    logger,
                )
                stored_this_round = uploaded_this_round - len(missing)
                if stored_this_round > 0:
                    stored_files += stored_this_round
                    logger.info(
                        "[OK] %s study=%s stored %s file(s) this round",
                        series_dir.name,
                        study_batch.study_instance_uid,
                        stored_this_round,
                    )

                if not missing:
                    break

                pending = missing
                attempt += 1
                if attempt > max(1, args.max_retries):
                    failed_files += len(pending)
                    for record in pending:
                        report_progress(record, "failed")
                    logger.error(
                        "[FAIL] %s study=%s still missing %s file(s) after %s attempts: %s",
                        series_dir.name,
                        study_batch.study_instance_uid,
                        len(pending),
                        args.max_retries,
                        ", ".join(record.path.name for record in pending),
                    )
                    break

                logger.warning(
                    "[RETRY] %s study=%s missing %s file(s); retrying after %.1fs",
                    series_dir.name,
                    study_batch.study_instance_uid,
                    len(pending),
                    args.retry_delay,
                )
                time.sleep(max(0.5, args.retry_delay))

        return WorkerSummary(
            series_dir=series_dir,
            study_groups=len(study_batches),
            files=total_files,
            existing_files=existing_files,
            stored_files=stored_files,
            skipped_files=skipped_files,
            failed_files=failed_files,
        )
    finally:
        if progress_bar is not None:
            progress_bar.close()
        client.close_all()


def process_study_dir(
    study_dir: Path,
    args: argparse.Namespace,
    logger: logging.Logger,
    progress_callback: Optional[ProgressCallback] = None,
) -> WorkerSummary:
    series_dirs = iter_series_dirs(study_dir)
    logger.info("[STUDY] %s -> %s series dir(s)", study_dir, len(series_dirs))

    summaries: List[WorkerSummary] = []
    max_workers = resolve_worker_count(
        len(series_dirs),
        args.max_workers,
        cpu_multiplier=AUTO_SERIES_WORKER_MULTIPLIER,
        minimum=2,
        cap=max(8, AUTO_WORKER_CAP // 2),
    )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(process_series_dir, series_dir, args, logger, progress_callback, position): series_dir
            for position, series_dir in enumerate(series_dirs)
        }
        for future in as_completed(future_map):
            series_dir = future_map[future]
            try:
                summaries.append(future.result())
            except Exception as exc:
                logger.exception("[FATAL] %s series processing failed: %s", series_dir, exc)

    return WorkerSummary(
        series_dir=study_dir,
        study_groups=sum(summary.study_groups for summary in summaries),
        files=sum(summary.files for summary in summaries),
        existing_files=sum(summary.existing_files for summary in summaries),
        stored_files=sum(summary.stored_files for summary in summaries),
        skipped_files=sum(summary.skipped_files for summary in summaries),
        failed_files=sum(summary.failed_files for summary in summaries),
    )


def main() -> int:
    args = parse_args()
    logger = setup_logging(args.log_file)

    try:
        study_dirs = iter_study_dirs(args.root)
        logger.info("[ROOT] %s -> %s study dir(s)", args.root, len(study_dirs))

        total_study_dirs = 0
        total_series_dirs = 0
        total_groups = 0
        total_files = 0
        total_existing_files = 0
        total_stored_files = 0
        total_skipped_files = 0
        total_failed_files = 0

        for study_dir in study_dirs:
            total_study_dirs += 1
            summary = process_study_dir(study_dir, args, logger)
            total_groups += summary.study_groups
            total_files += summary.files
            total_existing_files += summary.existing_files
            total_stored_files += summary.stored_files
            total_skipped_files += summary.skipped_files
            total_failed_files += summary.failed_files

            series_dirs = iter_series_dirs(study_dir)
            total_series_dirs += len(series_dirs)

        logger.info(
            "[DONE] study dirs=%s series dirs=%s study groups=%s files=%s existing=%s stored=%s skipped=%s failed=%s",
            total_study_dirs,
            total_series_dirs,
            total_groups,
            total_files,
            total_existing_files,
            total_stored_files,
            total_skipped_files,
            total_failed_files,
        )
        return 0
    except Exception as exc:
        logger.exception("Fatal error while preparing upload: %s", exc)
        logger.error("[FATAL] %s; see log file: %s", exc, args.log_file)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
