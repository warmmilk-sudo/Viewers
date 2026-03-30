from __future__ import annotations

import argparse
import base64
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

# 默认设置，参考现有的 backfill_category_path.py
DEFAULT_BASE_URL = "http://172.16.82.11:18081/dcm4chee-arc/aets/DCM4CHEE/rs"
DEFAULT_PAGE_SIZE = 200
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_WORKERS = 8

# 私有标签常量 (7777,1027)
PRIVATE_TAG = "77771027"


@dataclass(frozen=True)
class StudyRef:
    study_instance_uid: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "同步 DICOM 研究分类：遍历 DCM4CHEE 中的所有 Study，提取私有标签 (7777,1027) "
            "的值并将其同步到系统的 Access Control ID 中。"
        )
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"DICOMweb REST URL 基础路径。默认为: {DEFAULT_BASE_URL}",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        help="每页获取的研究数量。",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=DEFAULT_MAX_WORKERS,
        help="并发更新线程数。默认: 8",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="HTTP 请求超时时间（秒）。",
    )
    parser.add_argument(
        "--username",
        default="hygea",
        help="HTTP 基础认证用户名 (Basic Auth)。",
    )
    parser.add_argument(
        "--password",
        default="hygea",
        help="HTTP 基础认证密码 (Basic Auth)。",
    )
    parser.add_argument(
        "--header",
        action="append",
        default=[],
        help="可选的自定义 HTTP Header，格式为 'Name: value'。可多次指定。",
    )
    parser.add_argument(
        "--cookie",
        help="可选的 Cookie Header 值。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="模拟运行：仅列出将要更新的研究及其标签值，不执行实际更新。",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=Path(__file__).with_name("sync_study_category_from_tag.log"),
        help="记录详细错误的日志文件路径。",
    )
    return parser.parse_args()


def setup_logging(log_file: Path) -> logging.Logger:
    logger = logging.getLogger("sync_study_category")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False

    # 控制台输出
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(console_handler)

    # 文件输出
    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(file_handler)

    return logger


def normalize_category_path(value: str) -> str:
    """标准化路径：替换反斜杠、特殊分隔符，并去除首尾空格。"""
    text = str(value or "").strip().replace("\\", "/")
    for delimiter in ("→", "｜", ">", "::"):
        text = text.replace(delimiter, "/")
    segments = [segment.strip() for segment in text.split("/") if segment.strip()]
    return "/".join(segments)


def serialize_category_path(value: str) -> str:
    """序列化路径：将标准化后的路径转换为带有 '→' 分隔符的字符串。"""
    segments = [segment.strip() for segment in normalize_category_path(value).split("/") if segment.strip()]
    return "→".join(segments)


def extract_qido_value(item: dict, tag: str) -> str | None:
    """从 QIDO JSON 中提取标签值。"""
    raw = item.get(tag) or item.get(tag.upper())
    if isinstance(raw, dict):
        values = raw.get("Value") or []
        if values:
            return str(values[0]).strip() or None
        return None
    if raw is None:
        return None
    return str(raw).strip() or None


def build_request(
    url: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    auth_header: str | None = None,
    extra_headers: Optional[dict[str, str]] = None,
) -> Request:
    headers = {"Accept": "application/json"}
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
    """批量获取归档中所有的 Study Instance UID。"""
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
            raise RuntimeError(f"QIDO 请求失败 ({exc.code}): {exc.reason}") from exc
        except URLError as exc:
            raise RuntimeError(f"QIDO 网络错误: {exc.reason}") from exc

        items = json.loads(payload.decode("utf-8")) if payload else []
        if not items:
            break

        for item in items:
            uid_text = extract_qido_value(item, "0020000D") or ""
            if uid_text:
                studies.append(StudyRef(study_instance_uid=uid_text))

        logger.info(f"[QIDO] 获取到 offset={offset} 的数据，当前累计 fetched={len(studies)}")
        if len(items) < page_size:
            break
        offset += len(items)

    return studies


def qido_fetch_tag_value(
    base_url: str,
    study_uid: str,
    *,
    timeout: float,
    auth_header: str | None,
    extra_headers: Optional[dict[str, str]],
) -> str | None:
    """查询指定 Study 的私有分类标签 (7777,1027)。"""
    base = base_url.rstrip("/")
    encoded_uid = quote(study_uid, safe="")
    url = f"{base}/studies?StudyInstanceUID={encoded_uid}&includefield={PRIVATE_TAG}&limit=1"
    request = build_request(url, auth_header=auth_header, extra_headers=extra_headers)

    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except Exception:
        return None

    items = json.loads(payload.decode("utf-8")) if payload else []
    if not items:
        return None

    raw_val = extract_qido_value(items[0], PRIVATE_TAG)
    if not raw_val:
        return None

    return normalize_category_path(raw_val)


def update_study_access_control(
    base_url: str,
    study_uid: str,
    category_path: str,
    *,
    timeout: float,
    auth_header: str | None,
    extra_headers: Optional[dict[str, str]],
) -> bool:
    """调用 REST API 更新 Study 的 Access Control ID。"""
    base = base_url.rstrip("/")
    encoded_uid = quote(study_uid, safe="")
    serialized = serialize_category_path(category_path)
    encoded_category = quote(serialized, safe="")
    
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
            if response.status in (200, 202, 204):
                return True
            return False
    except Exception:
        return False


def process_study(
    study: StudyRef,
    args: argparse.Namespace,
    auth_header: str | None,
    extra_headers: dict[str, str],
    logger: logging.Logger,
) -> tuple[str, str | None, str]:
    """处理单个 Study 的同步逻辑。"""
    tag_value = qido_fetch_tag_value(
        args.base_url,
        study.study_instance_uid,
        timeout=args.timeout,
        auth_header=auth_header,
        extra_headers=extra_headers,
    )

    if not tag_value:
        return study.study_instance_uid, None, "MISSING_TAG"

    if args.dry_run:
        return study.study_instance_uid, tag_value, "DRY_RUN"

    success = update_study_access_control(
        args.base_url,
        study.study_instance_uid,
        tag_value,
        timeout=args.timeout,
        auth_header=auth_header,
        extra_headers=extra_headers,
    )

    return study.study_instance_uid, tag_value, "SUCCESS" if success else "FAILED"


def main() -> int:
    args = parse_args()
    logger = setup_logging(args.log_file)

    auth_header = basic_auth_header(args.username, args.password)
    # 解析自定义 header
    extra_headers = {}
    for h in args.header:
        if ":" in h:
            name, val = h.split(":", 1)
            extra_headers[name.strip()] = val.strip()
    if args.cookie:
        extra_headers["Cookie"] = args.cookie

    logger.info("=" * 60)
    logger.info(f"开始同步归档中的 Study 分类 (目标服务器: {args.base_url})")
    if args.dry_run:
        logger.info("!!! 注意：当前处于 DRY-RUN 模式，不会执行实际更新 !!!")
    logger.info("=" * 60)

    try:
        studies = qido_study_uids(
            args.base_url,
            page_size=args.page_size,
            timeout=args.timeout,
            auth_header=auth_header,
            extra_headers=extra_headers,
            logger=logger,
        )

        if not studies:
            logger.info("未发现任何 Study。")
            return 0

        logger.info(f"计划处理 {len(studies)} 个 Study...")

        completed = 0
        success_count = 0
        fail_count = 0
        skip_count = 0

        with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
            future_to_study = {
                executor.submit(process_study, s, args, auth_header, extra_headers, logger): s
                for s in studies
            }

            for future in as_completed(future_to_study):
                study_uid, tag_val, status = future.result()
                completed += 1
                
                if status == "SUCCESS":
                    success_count += 1
                    logger.info(f"[{completed}/{len(studies)}] [OK] {study_uid} -> {tag_val}")
                elif status == "DRY_RUN":
                    success_count += 1
                    logger.info(f"[{completed}/{len(studies)}] [DRY] {study_uid} 标签值: {tag_val}")
                elif status == "MISSING_TAG":
                    skip_count += 1
                    logger.info(f"[{completed}/{len(studies)}] [SKIP] {study_uid} (未找到标签 {PRIVATE_TAG})")
                else:
                    fail_count += 1
                    logger.error(f"[{completed}/{len(studies)}] [FAIL] {study_uid} 更新失败 (标签值: {tag_val})")

        logger.info("=" * 60)
        logger.info("同步任务结束:")
        logger.info(f"  总计 Study: {len(studies)}")
        if args.dry_run:
            logger.info(f"  检测到有效标签: {success_count}")
        else:
            logger.info(f"  同步成功: {success_count}")
        logger.info(f"  同步失败: {fail_count}")
        logger.info(f"  由于缺少标签跳过: {skip_count}")
        logger.info(f"日志详情详见: {args.log_file}")
        logger.info("=" * 60)

        return 0
    except Exception as exc:
        logger.exception(f"发生致命错误: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
