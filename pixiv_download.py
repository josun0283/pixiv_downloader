import json
import os
import time

from pixiv_config import DownloadConfig
from pixiv_search import fetch_original_urls, fetch_search_ids, normalize_tags, split_keyword
from pixiv_session import make_session, request_bytes


def download_by_tag(
    keyword,
    dest_dir,
    phpsessid,
    device_token=None,
    pages=1,
    sleep_sec=0.3,
    download_config=None,
    include_tags=None,
    any_tags=None,
    exclude_tags=None,
    filter_ai=False,
    filter_r18=False,
    max_artworks=None,
):
    """Download Pixiv images by tag/keyword.

    - keyword: tag or search keyword (string or list of tags)
    - dest_dir: output folder
    - phpsessid/device_token: cookies from your logged-in session
    - pages: number of search result pages to pull
    - sleep_sec: delay between downloads
    - include_tags: require all of these tags
    - any_tags: require at least one of these tags
    - exclude_tags: filter out these tags
    - filter_ai: exclude AI-generated works when True
    - filter_r18: exclude R-18 works when True
    - max_artworks: max number of artworks to download
    """
    if download_config is None:
        download_config = DownloadConfig()
    if not dest_dir:
        dest_dir = download_config.store_path
    os.makedirs(dest_dir, exist_ok=True)
    session = make_session(phpsessid, device_token)

    include_tags = normalize_tags(include_tags or [])
    any_tags = normalize_tags(any_tags or [])
    exclude_tags = normalize_tags(exclude_tags or [])
    keywords = split_keyword(keyword)
    search_keyword = " ".join(keywords) if keywords else ""

    seen = set()
    tag_map = {}
    all_urls = []
    downloaded_artworks = 0
    for page in range(1, pages + 1):
        items = fetch_search_ids(session, search_keyword, download_config, page=page)
        for item in items:
            if max_artworks is not None and downloaded_artworks >= max_artworks:
                break
            pid = item.get("id")
            if not pid or pid in seen:
                continue
            seen.add(pid)
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
            if filter_r18 and x_restrict in (1, 2):
                continue
            if download_config.with_tag:
                tag_map[pid] = item_tags
            urls = fetch_original_urls(session, pid, download_config)
            for direct_url in urls:
                all_urls.append(direct_url)
                file_name = direct_url.split("/")[-1]
                if "_p" not in file_name:
                    name, ext = file_name.rsplit(".", 1)
                    file_name = f"{name}_p0.{ext}"
                save_path = os.path.join(dest_dir, file_name)
                if download_config.url_only:
                    print(direct_url)
                    continue
                resp = request_bytes(session, direct_url, download_config)
                if resp.status_code != 200:
                    print(f"Skip {direct_url} -> {resp.status_code}")
                    continue
                with open(save_path, "wb") as f:
                    f.write(resp.content)
                print(save_path)
                time.sleep(sleep_sec)
            downloaded_artworks += 1
        if max_artworks is not None and downloaded_artworks >= max_artworks:
            break
    if download_config.with_tag and tag_map:
        tags_path = os.path.join(dest_dir, "tags.json")
        with open(tags_path, "w", encoding="utf-8") as f:
            json.dump(tag_map, f, ensure_ascii=True, indent=2)
    return all_urls
