import concurrent.futures
import json
import os
import threading
import time
from datetime import datetime

from pixiv_config import DownloadConfig
from pixiv_search import (
    fetch_illust_details,
    fetch_original_urls,
    fetch_search_ids,
    normalize_tags,
    split_keyword,
)
from pixiv_session import make_session, request_bytes


_THREAD_LOCAL = threading.local()
_THREAD_START_LOCK = threading.Lock()
_THREAD_START_INDEX = 0


def _debug_print(debug, message):
    if debug:
        print(f"[DEBUG] {message}")


def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def _normalize_post_date(item):
    post_date = (
        item.get("createDate")
        or item.get("create_date")
        or item.get("uploadDate")
        or item.get("upload_date")
    )
    if isinstance(post_date, str) and "T" in post_date:
        post_date = post_date.split("T", 1)[0]
    return post_date


def _normalize_int(value):
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_like_count(item):
    if not isinstance(item, dict):
        return None

    candidates = (
        item.get("bookmarkCount"),
        item.get("bookmark_count"),
        item.get("likeCount"),
        item.get("like_count"),
        item.get("total_bookmarks"),
    )
    for candidate in candidates:
        value = _normalize_int(candidate)
        if value is not None:
            return value
    return None


def _build_save_path(dest_dir, direct_url):
    file_name = direct_url.split("/")[-1]
    if "_p" not in file_name:
        name, ext = file_name.rsplit(".", 1)
        file_name = f"{name}_p0.{ext}"
    return os.path.join(dest_dir, file_name)


def _write_json_atomic(path, payload):
    temp_path = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    last_exc = None
    for attempt in range(8):
        try:
            os.replace(temp_path, path)
            return
        except PermissionError as exc:
            last_exc = exc
            if attempt == 7:
                break
            time.sleep(0.05 * (attempt + 1))
        except OSError as exc:
            last_exc = exc
            break

    try:
        if os.path.exists(temp_path):
            os.remove(temp_path)
    except OSError:
        pass

    raise last_exc


def _write_tags_json(tags_path, tag_map):
    _write_json_atomic(tags_path, tag_map)


def _build_sort_indexes_payload(tag_map):
    pid_list = list(tag_map.keys())

    likes_asc = sorted(
        pid_list,
        key=lambda pid: (
            _normalize_int(tag_map.get(pid, {}).get("likes")) is None,
            _normalize_int(tag_map.get(pid, {}).get("likes"))
            if _normalize_int(tag_map.get(pid, {}).get("likes")) is not None
            else -1,
            str(pid),
        ),
    )
    post_date_asc = sorted(
        pid_list,
        key=lambda pid: (
            str(tag_map.get(pid, {}).get("post_date") or ""),
            str(pid),
        ),
    )
    artwork_id_asc = sorted(
        pid_list,
        key=lambda pid: str(tag_map.get(pid, {}).get("artwork_id") or pid),
    )

    return {
        "version": 1,
        "generated_at": _now_iso(),
        "artwork_count": len(pid_list),
        "sort_indexes": {
            "likes": {
                "asc": likes_asc,
                "desc": list(reversed(likes_asc)),
            },
            "post_date": {
                "asc": post_date_asc,
                "desc": list(reversed(post_date_asc)),
            },
            "artwork_id": {
                "asc": artwork_id_asc,
                "desc": list(reversed(artwork_id_asc)),
            },
        },
    }


def _write_sort_indexes_json(indexes_path, tag_map, debug):
    payload = _build_sort_indexes_payload(tag_map)
    _write_json_atomic(indexes_path, payload)
    _debug_print(
        debug,
        f"sort indexes updated: {indexes_path} ({payload.get('artwork_count', 0)} artworks)",
    )
    return payload


def _normalize_tag_record(record):
    if not isinstance(record, dict):
        return {"local_files": []}

    normalized = dict(record)
    tags = normalized.get("tags", [])
    if not isinstance(tags, list):
        tags = [str(tags)] if tags else []
    normalized["tags"] = [str(t) for t in tags if str(t).strip()]

    local_files = normalized.get("local_files", [])
    if not isinstance(local_files, list):
        local_files = []
    normalized["local_files"] = [str(p) for p in local_files if str(p).strip()]
    return normalized


def _load_tags_json(tags_path, debug):
    if not os.path.exists(tags_path):
        return {}
    try:
        with open(tags_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        _debug_print(debug, f"failed to load existing tags.json -> {exc}")
        return {}

    if not isinstance(loaded, dict):
        return {}

    result = {}
    for pid, record in loaded.items():
        result[str(pid)] = _normalize_tag_record(record)
    return result


def _classify_url_status(urls, error_message):
    if urls:
        return "ok"
    if not error_message:
        return "url_not_found"

    text = error_message.lower()
    if "404" in text:
        return "url_not_found"
    if "403" in text:
        return "forbidden"
    return "request_error"


def _merge_artwork_metadata(existing, artwork):
    merged = _normalize_tag_record(existing)
    merged["author_id"] = artwork.get("author_id")
    merged["author_name"] = artwork.get("author_name")
    merged["post_date"] = artwork.get("post_date")
    merged["tags"] = list(artwork.get("tags", []))
    if artwork.get("likes") is not None:
        merged["likes"] = artwork.get("likes")
    if not merged.get("first_seen_at"):
        merged["first_seen_at"] = _now_iso()
    return merged


def _append_local_file(record, save_path):
    normalized = _normalize_tag_record(record)
    file_name = os.path.basename(save_path)
    local_files = normalized.get("local_files", [])
    if file_name and file_name not in local_files:
        local_files.append(file_name)
    normalized["local_files"] = local_files
    return normalized


def _persist_tag_map(with_tag, tags_path, tag_map, debug, reason, raise_on_error=True):
    if not with_tag:
        return False

    try:
        _write_tags_json(tags_path, tag_map)
    except OSError as exc:
        _debug_print(debug, f"tags.json update failed ({reason}) -> {exc}")
        if raise_on_error:
            raise
        return False

    _debug_print(debug, f"tags.json updated ({reason})")
    return True


def _download_config_as_dict(download_config):
    return {
        "timeout": download_config.timeout,
        "retry_times": download_config.retry_times,
        "fail_delay": download_config.fail_delay,
        "store_path": download_config.store_path,
        "with_tag": download_config.with_tag,
        "url_only": download_config.url_only,
        "num_threads": download_config.num_threads,
        "thread_delay": download_config.thread_delay,
    }


def _write_run_report(dest_dir, report_data):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    report_path = os.path.join(dest_dir, f"download_run_{timestamp}.txt")
    suffix = 1
    while os.path.exists(report_path):
        report_path = os.path.join(dest_dir, f"download_run_{timestamp}_{suffix}.txt")
        suffix += 1
    lines = [
        "Pixiv Downloader Run Report",
        "=" * 40,
        f"started_at: {report_data.get('started_at')}",
        f"finished_at: {report_data.get('finished_at')}",
        f"duration_sec: {report_data.get('duration_sec')}",
        "",
        "Arguments (excluding dest_dir and phpsessid):",
    ]

    args_data = report_data.get("args", {})
    for key in sorted(args_data.keys()):
        lines.append(f"- {key}: {args_data[key]}")

    lines.append("")
    lines.append("Statistics:")
    stats_data = report_data.get("stats", {})
    for key in sorted(stats_data.keys()):
        lines.append(f"- {key}: {stats_data[key]}")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return report_path


def _get_thread_session(phpsessid, device_token, thread_delay):
    session = getattr(_THREAD_LOCAL, "session", None)
    if session is not None:
        return session

    session = make_session(phpsessid, device_token)
    _THREAD_LOCAL.session = session

    if thread_delay and thread_delay > 0:
        global _THREAD_START_INDEX
        with _THREAD_START_LOCK:
            slot = _THREAD_START_INDEX
            _THREAD_START_INDEX += 1
        if slot > 0:
            time.sleep(thread_delay * slot)

    return session


def _reset_thread_start_index():
    global _THREAD_START_INDEX
    _THREAD_START_INDEX = 0


def _get_page_count(item):
    page_count = item.get("pageCount") or item.get("page_count") or 1
    try:
        page_count = int(page_count)
    except (TypeError, ValueError):
        page_count = 1
    return max(1, page_count)


def _build_download_plan(
    session,
    search_keywords,
    search_mode,
    pages,
    download_config,
    include_tags,
    any_tags,
    exclude_tags,
    filter_ai,
    filter_r18,
    only_r18,
    debug,
    max_artworks,
):
    seen = set()
    planned_artworks = []
    total_files = 0

    for search_keyword in search_keywords:
        for page in range(1, pages + 1):
            if max_artworks is not None and len(planned_artworks) >= max_artworks:
                break
            items = fetch_search_ids(
                session,
                search_keyword,
                download_config,
                page=page,
                mode=search_mode,
            )
            if not items:
                _debug_print(
                    debug,
                    f"plan keyword={search_keyword!r} page={page}: no items, stop paging",
                )
                break

            accepted_before = len(planned_artworks)

            for item in items:
                if max_artworks is not None and len(planned_artworks) >= max_artworks:
                    break

                pid = item.get("id")
                if not pid or pid in seen:
                    continue

                item_tags = item.get("tags", [])
                tag_set = normalize_tags(item_tags)
                if include_tags and not include_tags.issubset(tag_set):
                    continue
                if any_tags and tag_set.isdisjoint(any_tags):
                    continue
                if exclude_tags and not exclude_tags.isdisjoint(tag_set):
                    continue

                ai_type = item.get("aiType")
                if filter_ai and ai_type == 2:
                    continue
                x_restrict = item.get("xRestrict")
                if only_r18 and x_restrict not in (1, 2):
                    continue
                if filter_r18 and x_restrict in (1, 2):
                    continue

                seen.add(pid)
                planned_artworks.append(
                    {
                        "pid": str(pid),
                        "tags": item_tags,
                        "author_id": item.get("userId") or item.get("user_id"),
                        "author_name": item.get("userName") or item.get("user_name"),
                        "post_date": _normalize_post_date(item),
                        "likes": _extract_like_count(item),
                    }
                )
                total_files += _get_page_count(item)

            page_new_artworks = len(planned_artworks) - accepted_before
            _debug_print(
                debug,
                (
                    f"plan keyword={search_keyword!r} page={page}: "
                    f"fetched={len(items)} new_artworks={page_new_artworks} "
                    f"total_artworks={len(planned_artworks)}"
                ),
            )

        if max_artworks is not None and len(planned_artworks) >= max_artworks:
            break

    return planned_artworks, total_files


def _download_file_with_session(session, task, download_config):
    direct_url = task["url"]
    save_path = task["save_path"]

    try:
        resp = request_bytes(session, direct_url, download_config)
    except RuntimeError as exc:
        return False, f"Skip {direct_url} -> {exc}", None

    if resp.status_code != 200:
        return False, f"Skip {direct_url} -> {resp.status_code}", None

    with open(save_path, "wb") as f:
        f.write(resp.content)

    return True, save_path, save_path


def _download_file_worker(task, phpsessid, device_token, download_config, sleep_sec):
    session = _get_thread_session(phpsessid, device_token, download_config.thread_delay)
    ok, message, save_path = _download_file_with_session(session, task, download_config)
    if not ok:
        return {"ok": False, "message": message, "pid": task["pid"], "save_path": None}

    if sleep_sec > 0:
        time.sleep(sleep_sec)

    return {
        "ok": True,
        "message": message,
        "pid": task["pid"],
        "save_path": save_path,
    }


def _fetch_urls_worker(artwork, phpsessid, device_token, download_config):
    pid = artwork["pid"]
    session = _get_thread_session(phpsessid, device_token, download_config.thread_delay)
    try:
        urls = fetch_original_urls(session, pid, download_config)
    except RuntimeError as exc:
        return {"pid": pid, "urls": [], "error": str(exc)}
    return {"pid": pid, "urls": urls, "error": None}


def _fetch_like_for_pid_worker(pid, phpsessid, device_token, download_config):
    session = _get_thread_session(phpsessid, device_token, download_config.thread_delay)
    try:
        details = fetch_illust_details(session, pid, download_config)
    except RuntimeError:
        return pid, None
    return pid, _extract_like_count(details)


def download_by_tag(
    keyword,
    dest_dir,
    phpsessid,
    device_token=None,
    pages=1,
    sleep_sec=0,
    download_config=None,
    include_tags=None,
    any_tags=None,
    exclude_tags=None,
    filter_ai=False,
    filter_r18=False,
    only_r18=False,
    debug=False,
    first_download=True,
    max_artworks=None,
):
    """Download Pixiv images by tag/keyword.

    - keyword: tag or search keyword (string or list of tags)
    - dest_dir: output folder
    - phpsessid/device_token: cookies from your logged-in session
    - pages: max number of search result pages to pull
    - sleep_sec: delay between downloads
    - include_tags: require all of these tags
    - any_tags: require at least one of these tags
    - exclude_tags: filter out these tags
    - filter_ai: exclude AI-generated works when True
    - filter_r18: exclude R-18 works when True
    - only_r18: keep only R-18 works when True
    - debug: print additional diagnostics when True
    - first_download: build metadata from scratch when True; use incremental sync when False
    - max_artworks: max number of artworks to process from search
    """
    if only_r18 and filter_r18:
        raise ValueError("only_r18=True and filter_r18=True conflict with each other")

    run_started_at = _now_iso()
    run_start_perf = time.perf_counter()

    if download_config is None:
        download_config = DownloadConfig()
    if not dest_dir:
        dest_dir = download_config.store_path
    os.makedirs(dest_dir, exist_ok=True)
    session = make_session(phpsessid, device_token)

    include_tags = normalize_tags(include_tags or [])
    any_tags = normalize_tags(any_tags or [])
    exclude_tags = normalize_tags(exclude_tags or [])
    search_keywords = split_keyword(keyword)
    if not search_keywords:
        search_keywords = [""]

    num_threads = max(1, int(download_config.num_threads))
    _debug_print(debug, f"num_threads checked: {num_threads}")

    search_mode = "r18" if only_r18 else "all"
    _debug_print(
        debug,
        f"build plan start: keywords={len(search_keywords)} pages_limit={pages} search_mode={search_mode}",
    )
    if num_threads >= 24:
        _debug_print(
            debug,
            "high num_threads may affect normal Pixiv browsing on the same account/session",
        )

    incremental_sync = not first_download
    _debug_print(debug, f"incremental_sync={incremental_sync}")

    _reset_thread_start_index()

    tags_path = os.path.join(dest_dir, "tags.json")
    sort_indexes_path = os.path.join(dest_dir, "tags.index.json")
    tag_map = {}
    tags_write_count = 0
    if download_config.with_tag:
        if incremental_sync:
            tag_map = _load_tags_json(tags_path, debug)
            _debug_print(debug, f"loaded existing metadata entries: {len(tag_map)}")
        else:
            tag_map = {}

    existing_ids_before = set(tag_map.keys()) if incremental_sync else set()
    refreshed_pids = set()
    new_artwork_ids = set()
    old_refreshed_count = 0

    artwork_with_urls = set()
    successful_pids = set()
    expected_files_by_pid = {}
    downloaded_files_by_pid = {}
    newest_date = None
    oldest_date = None
    missing_date_count = 0

    planned_artworks = []
    planned_artworks_count = 0
    download_tasks = []
    all_urls = []
    total_urls_collected = 0
    downloaded_files = 0

    task1_start = time.perf_counter()

    planned_artworks, _ = _build_download_plan(
        session=session,
        search_keywords=search_keywords,
        search_mode=search_mode,
        pages=pages,
        download_config=download_config,
        include_tags=include_tags,
        any_tags=any_tags,
        exclude_tags=exclude_tags,
        filter_ai=filter_ai,
        filter_r18=filter_r18,
        only_r18=only_r18,
        debug=debug,
        max_artworks=max_artworks,
    )
    planned_artworks_count = len(planned_artworks)

    if planned_artworks:
        normalized_dates = [str(art["post_date"])[:10] for art in planned_artworks if art.get("post_date")]
        missing_date_count = len(planned_artworks) - len(normalized_dates)
        if normalized_dates:
            newest_date = max(normalized_dates)
            oldest_date = min(normalized_dates)

    artwork_by_pid = {artwork["pid"]: artwork for artwork in planned_artworks}

    def process_url_result(pid, urls, error_message):
        nonlocal old_refreshed_count, total_urls_collected, tags_write_count

        pid_key = str(pid)
        artwork = artwork_by_pid.get(pid_key)
        if artwork is None:
            return

        refreshed_pids.add(pid_key)
        merged = _merge_artwork_metadata(tag_map.get(pid_key, {}), artwork)
        merged["last_refreshed_at"] = _now_iso()

        url_status = _classify_url_status(urls, error_message)
        merged["url_status"] = url_status
        if error_message:
            merged["url_error"] = error_message
        elif "url_error" in merged:
            merged.pop("url_error")

        if url_status != "ok":
            if merged.get("local_files"):
                merged["download_status"] = "kept_local_missing_remote"
            else:
                merged["download_status"] = "url_not_found"

        tag_map[pid_key] = merged

        is_old = pid_key in existing_ids_before
        if incremental_sync and is_old:
            old_refreshed_count += 1
            if _persist_tag_map(
                download_config.with_tag,
                tags_path,
                tag_map,
                debug,
                f"refresh pid={pid_key}",
                raise_on_error=False,
            ):
                tags_write_count += 1
            return

        if not urls:
            return

        new_artwork_ids.add(pid_key)
        artwork_with_urls.add(pid_key)
        for direct_url in urls:
            total_urls_collected += 1
            all_urls.append(direct_url)
            download_tasks.append(
                {
                    "pid": pid_key,
                    "url": direct_url,
                    "save_path": _build_save_path(dest_dir, direct_url),
                }
            )
            expected_files_by_pid[pid_key] = expected_files_by_pid.get(pid_key, 0) + 1
            _debug_print(debug, f"queue urls collected: {len(download_tasks)}")

    if planned_artworks:
        url_fetch_workers = min(max(1, len(planned_artworks)), min(num_threads, 8))
        _debug_print(debug, f"queue URL fetch workers: {url_fetch_workers}")

        _reset_thread_start_index()
        if url_fetch_workers == 1:
            for artwork in planned_artworks:
                pid = artwork["pid"]
                try:
                    urls = fetch_original_urls(session, pid, download_config)
                    process_url_result(pid, urls, None)
                except RuntimeError as exc:
                    process_url_result(pid, [], str(exc))
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=url_fetch_workers) as executor:
                futures = [
                    executor.submit(
                        _fetch_urls_worker,
                        artwork,
                        phpsessid,
                        device_token,
                        download_config,
                    )
                    for artwork in planned_artworks
                ]
                for future in concurrent.futures.as_completed(futures):
                    try:
                        result = future.result()
                    except Exception as exc:
                        _debug_print(debug, f"URL queue worker failed: {exc}")
                        continue
                    process_url_result(result.get("pid"), result.get("urls", []), result.get("error"))

    task1_elapsed = time.perf_counter() - task1_start
    _debug_print(
        debug,
        f"flat queue built: artworks={len(artwork_with_urls)}, files={len(download_tasks)}",
    )
    if newest_date and oldest_date:
        _debug_print(
            debug,
            f"post_date range (newest -> oldest): {newest_date} -> {oldest_date}",
        )
    else:
        _debug_print(debug, "post_date range: unavailable (no date fields)")
    if missing_date_count > 0:
        _debug_print(debug, f"artworks missing post_date field: {missing_date_count}")
    _debug_print(debug, f"Task 1 (build flat download queue) took {task1_elapsed:.2f}s")

    total_files = len(download_tasks)
    if download_config.url_only:
        print(f"Total files found: {total_files}")
    else:
        print(f"Total files to download: {total_files}")

    task2_start = time.perf_counter()
    report_path = None
    try:
        if download_config.url_only:
            for task in download_tasks:
                print(task["url"])
            successful_pids.update(artwork_with_urls)
            return all_urls

        if num_threads == 1:
            for task in download_tasks:
                ok, message, save_path = _download_file_with_session(session, task, download_config)
                if not ok:
                    print(message)
                    continue

                downloaded_files += 1
                pid = task["pid"]
                successful_pids.add(pid)
                downloaded_files_by_pid[pid] = downloaded_files_by_pid.get(pid, 0) + 1
                tag_map[pid] = _append_local_file(tag_map.get(pid, {}), save_path)

                if total_files > 0:
                    progress_pct = (downloaded_files * 100.0) / total_files
                    print(f"[{downloaded_files}/{total_files}] {progress_pct:.1f}% {message}")
                else:
                    print(f"[{downloaded_files}] {message}")

                if sleep_sec > 0:
                    time.sleep(sleep_sec)
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
                futures = [
                    executor.submit(
                        _download_file_worker,
                        task,
                        phpsessid,
                        device_token,
                        download_config,
                        sleep_sec,
                    )
                    for task in download_tasks
                ]
                for future in concurrent.futures.as_completed(futures):
                    try:
                        result = future.result()
                    except Exception as exc:
                        print(f"Skip task -> {exc}")
                        continue

                    if not result["ok"]:
                        print(result["message"])
                        continue

                    downloaded_files += 1
                    pid = result["pid"]
                    successful_pids.add(pid)
                    downloaded_files_by_pid[pid] = downloaded_files_by_pid.get(pid, 0) + 1
                    tag_map[pid] = _append_local_file(tag_map.get(pid, {}), result["save_path"])

                    if total_files > 0:
                        progress_pct = (downloaded_files * 100.0) / total_files
                        print(
                            f"[{downloaded_files}/{total_files}] {progress_pct:.1f}% {result['message']}"
                        )
                    else:
                        print(f"[{downloaded_files}] {result['message']}")

        for pid in new_artwork_ids:
            record = _normalize_tag_record(tag_map.get(pid, {}))
            expected_count = expected_files_by_pid.get(pid, 0)
            success_count = downloaded_files_by_pid.get(pid, 0)
            if expected_count == 0:
                if record.get("url_status") != "ok":
                    record["download_status"] = "url_not_found"
                else:
                    record["download_status"] = "no_urls"
            elif success_count == 0:
                record["download_status"] = "download_failed"
            elif success_count < expected_count:
                record["download_status"] = "partial"
            else:
                record["download_status"] = "downloaded"

            if success_count > 0:
                record["last_download_at"] = _now_iso()
            tag_map[pid] = record

        print(f"Finished: saved {downloaded_files}/{total_files} files")
        return all_urls
    finally:
        task2_elapsed = time.perf_counter() - task2_start
        _debug_print(debug, f"Task 2 (download all images) took {task2_elapsed:.2f}s")

        if download_config.with_tag:
            refresh_targets = refreshed_pids if incremental_sync else set(tag_map.keys())
            pids_need_likes = [pid for pid in refresh_targets if tag_map.get(pid, {}).get("likes") is None]
            persist_like_checkpoints = incremental_sync

            if pids_need_likes:
                like_workers = min(max(1, num_threads), 4, len(pids_need_likes))
                _debug_print(
                    debug,
                    f"backfill likes start: pending={len(pids_need_likes)} workers={like_workers}",
                )

                _reset_thread_start_index()
                resolved_likes = 0
                if like_workers == 1:
                    for idx, pid in enumerate(pids_need_likes, start=1):
                        _, like_count = _fetch_like_for_pid_worker(
                            pid,
                            phpsessid,
                            device_token,
                            download_config,
                        )
                        if like_count is not None:
                            tag_map[pid]["likes"] = like_count
                            resolved_likes += 1

                        if (
                            persist_like_checkpoints
                            and _persist_tag_map(
                                download_config.with_tag,
                                tags_path,
                                tag_map,
                                debug,
                                f"like refresh pid={pid}",
                                raise_on_error=False,
                            )
                        ):
                            tags_write_count += 1

                        if idx % 100 == 0 or idx == len(pids_need_likes):
                            _debug_print(
                                debug,
                                f"backfill likes progress: {idx}/{len(pids_need_likes)}",
                            )
                else:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=like_workers) as executor:
                        futures = [
                            executor.submit(
                                _fetch_like_for_pid_worker,
                                pid,
                                phpsessid,
                                device_token,
                                download_config,
                            )
                            for pid in pids_need_likes
                        ]

                        completed = 0
                        for future in concurrent.futures.as_completed(futures):
                            completed += 1
                            try:
                                pid, like_count = future.result()
                            except Exception:
                                continue

                            if like_count is not None:
                                tag_map[pid]["likes"] = like_count
                                resolved_likes += 1

                            if (
                                persist_like_checkpoints
                                and _persist_tag_map(
                                    download_config.with_tag,
                                    tags_path,
                                    tag_map,
                                    debug,
                                    f"like refresh pid={pid}",
                                    raise_on_error=False,
                                )
                            ):
                                tags_write_count += 1

                            if completed % 100 == 0 or completed == len(futures):
                                _debug_print(
                                    debug,
                                    f"backfill likes progress: {completed}/{len(futures)}",
                                )

                _debug_print(
                    debug,
                    f"backfill likes done: resolved={resolved_likes}/{len(pids_need_likes)}",
                )

            if _persist_tag_map(download_config.with_tag, tags_path, tag_map, debug, "final save"):
                tags_write_count += 1
            print(f"Saved tags metadata: {tags_path} ({len(tag_map)} artworks)")
            _write_sort_indexes_json(sort_indexes_path, tag_map, debug)
            print(f"Saved sort indexes: {sort_indexes_path}")

        run_finished_at = _now_iso()
        run_duration_sec = round(time.perf_counter() - run_start_perf, 2)
        args_snapshot = {
            "keyword": keyword,
            "device_token": device_token,
            "pages": pages,
            "sleep_sec": sleep_sec,
            "download_config": _download_config_as_dict(download_config),
            "include_tags": sorted(list(include_tags)),
            "any_tags": sorted(list(any_tags)),
            "exclude_tags": sorted(list(exclude_tags)),
            "filter_ai": filter_ai,
            "filter_r18": filter_r18,
            "only_r18": only_r18,
            "debug": debug,
            "first_download": first_download,
            "max_artworks": max_artworks,
        }
        stats_snapshot = {
            "incremental_sync": incremental_sync,
            "planned_artworks": planned_artworks_count,
            "existing_metadata_before": len(existing_ids_before),
            "old_artworks_refreshed": old_refreshed_count,
            "new_artworks_seen": len(new_artwork_ids),
            "urls_collected": total_urls_collected,
            "download_tasks": len(download_tasks),
            "downloaded_files": downloaded_files,
            "skipped_files": max(0, len(download_tasks) - downloaded_files),
            "task1_build_queue_sec": round(task1_elapsed, 2),
            "task2_download_sec": round(task2_elapsed, 2),
            "metadata_entries_after": len(tag_map),
            "tags_json_write_count": tags_write_count,
        }
        report_path = _write_run_report(
            dest_dir,
            {
                "started_at": run_started_at,
                "finished_at": run_finished_at,
                "duration_sec": run_duration_sec,
                "args": args_snapshot,
                "stats": stats_snapshot,
            },
        )
        print(f"Saved run report: {report_path}")
