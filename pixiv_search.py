from urllib.parse import quote

from pixiv_session import request_json


def fetch_search_ids(session, keyword, download_config, page=1, mode="all"):
    encoded = quote(keyword, safe="")
    url = f"https://www.pixiv.net/ajax/search/artworks/{encoded}"
    params = {
        "word": keyword,
        "order": "date_d",
        "mode": mode,
        "p": page,
        "s_mode": "s_tag_full",
        "type": "illust_and_ugoira",
        "lang": "en",
    }
    data = request_json(session, url, params, download_config)
    if data.get("error"):
        raise RuntimeError(f"Search error: {data.get('message')}")
    return data.get("body", {}).get("illustManga", {}).get("data", [])


def fetch_original_urls(session, pid, download_config):
    pages_url = f"https://www.pixiv.net/ajax/illust/{pid}/pages"
    data = request_json(session, pages_url, None, download_config)
    page_urls = [p.get("urls", {}).get("original") for p in data.get("body", [])]
    return [u for u in page_urls if u]


def fetch_illust_details(session, pid, download_config):
    details_url = f"https://www.pixiv.net/ajax/illust/{pid}"
    data = request_json(session, details_url, None, download_config)
    if data.get("error"):
        raise RuntimeError(f"Illust details error: {data.get('message')}")
    return data.get("body", {})


def normalize_tags(tags):
    return {t.lower() for t in tags}


def split_keyword(keyword):
    if isinstance(keyword, (list, tuple, set)):
        return [str(k).strip() for k in keyword if str(k).strip()]
    return [str(keyword).strip()] if str(keyword).strip() else []
