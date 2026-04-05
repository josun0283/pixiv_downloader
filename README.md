# pixiv_downloader
Download Pixiv artworks by tag/keyword. Supports multi-tag logic, tag filtering, AI filtering, R-18 filtering, and a maximum artwork limit.

## Requirements
- Python 3.8+
- `requests` library
- A valid Pixiv login session cookie (`PHPSESSID`)

To find your `PHPSESSID`, follow: https://sora.ink/archives/520

## Files
- `pixiv_config.py`: Configuration dataclasses
- `pixiv_session.py`: Session and request helpers
- `pixiv_search.py`: Search and URL helpers
- `pixiv_download.py`: Main download logic
- `pixiv_tag_download.py`: Example entry script

## Configure pixiv_config.py
Open `pixiv_config.py` to adjust defaults. The main options are in `DownloadConfig`:
- `store_path`: default download folder
- `timeout`, `retry_times`, `fail_delay`: request behavior
- `with_tag`: save tags to `tags.json`
- `url_only`: print URLs without downloading
- `num_threads`, `thread_delay`: reserved for parallel downloads

Example:
```python
from pixiv_config import DownloadConfig

config = DownloadConfig(
	store_path=r"C:\\Users\\YourName\\Downloads",
	timeout=6,
	retry_times=5,
	with_tag=True,
	url_only=False,
)
```

## Setup
1. Install dependencies:
   - `pip install requests`
2. Log in to https://www.pixiv.net in your browser.
3. Copy your `PHPSESSID` (and optionally `device_token`) cookie value.

## Basic Usage
Edit `pixiv_tag_download.py` and set your cookie values:

```python
from pixiv_download import download_by_tag

if __name__ == "__main__":
	download_by_tag(
		keyword="landscape",
		dest_dir=r"C:\\Users\\YourName\\Downloads",
		phpsessid="PASTE_YOUR_PHPSESSID_HERE",
		pages=1,
	)
```

## Tag Logic
- `include_tags`: AND logic (must include all)
- `any_tags`: OR logic (must include at least one)
- `exclude_tags`: NOT logic (must include none)

Example:
```python
download_by_tag(
	keyword=["tag_1", "tag_2"],
	dest_dir=r"C:\\Users\\YourName\\Downloads",
	phpsessid="PASTE_YOUR_PHPSESSID_HERE",
	include_tags=["tag_1", "tag_2"],
	any_tags=["tag_3", "tag_4"],
	exclude_tags=["tag_5"],
)
```

## AI Filtering
- `filter_ai=True` excludes AI-generated works.

## R-18 Filtering
- `filter_r18=True` excludes R-18 works.

## Limit the Number of Artworks
- `max_artworks=K` limits how many artworks will be processed.

## Notes
- R-18 content requires a logged-in account with R-18 enabled.
- If requests fail, check your cookie validity and network access.
