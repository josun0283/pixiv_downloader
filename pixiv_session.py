import time

import requests


def make_session(phpsessid, device_token=None):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/97.0.4692.71 Safari/537.36",
        "referer": "https://www.pixiv.net/",
    }
    cookies = {"PHPSESSID": phpsessid}
    if device_token:
        cookies["device_token"] = device_token
    session = requests.Session()
    session.headers.update(headers)
    session.cookies.update(cookies)
    return session


def request_json(session, url, params, download_config):
    last_error = None
    for _ in range(download_config.retry_times):
        try:
            resp = session.get(url, params=params, timeout=download_config.timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(download_config.fail_delay)
    raise RuntimeError(f"Request failed: {url} -> {last_error}")


def request_bytes(session, url, download_config):
    last_error = None
    for _ in range(download_config.retry_times):
        try:
            return session.get(url, timeout=download_config.timeout)
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(download_config.fail_delay)
    raise RuntimeError(f"Request failed: {url} -> {last_error}")
