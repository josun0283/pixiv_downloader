# pixiv_downloader
Download Pixiv artworks by tag/keyword. Supports multi-tag logic, tag filtering, AI filtering, R-18 filtering, incremental sync, and an offline local viewer with gallery/lightbox.

## Requirements
- Python 3.8+
- `requests` library
- A valid Pixiv login session cookie (`PHPSESSID`)
- Optional: `Pillow` for high-quality previews/thumbnails in the local viewer

To find your `PHPSESSID`, follow: https://sora.ink/archives/520

## Files
- `pixiv_config.py`: Configuration dataclasses
- `pixiv_session.py`: Session and request helpers
- `pixiv_search.py`: Search and URL helpers
- `pixiv_download.py`: Main download logic
- `pixiv_tag_download.py`: Example entry script
- `pixiv_local_viewer.py`: Offline metadata/image viewer

## Configure pixiv_config.py
Open `pixiv_config.py` to adjust defaults. The main options are in `DownloadConfig`:
- `store_path`: default download folder
- `timeout`, `retry_times`, `fail_delay`: request behavior
- `with_tag`: save metadata to `tags.json`
- `url_only`: print URLs without downloading
- `num_threads`: number of parallel download workers
- `thread_delay`: startup delay between worker slots

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
2. (Optional, viewer) Install Pillow:
	- `pip install pillow`
3. Log in to https://www.pixiv.net in your browser.
4. Copy your `PHPSESSID` (and optionally `device_token`) cookie value.

## Basic Usage
Edit `pixiv_tag_download.py` and set your cookie values:

```python
from pixiv_download import download_by_tag

if __name__ == "__main__":
	download_by_tag(
		keyword="landscape",
		dest_dir=r"C:\\Users\\YourName\\Downloads",
		phpsessid="PASTE_YOUR_PHPSESSID_HERE",
		first_download=True,
		pages=1,
	)
```

### Incremental Sync Mode
- `first_download=True`: start from scratch and run a full download pass.
	- Metadata is accumulated in memory and written in final save.
	- Likes backfill no longer checkpoints `tags.json` on every pid in this mode.
- `first_download=False`: incremental sync mode.
	- Existing `tags.json` is loaded.
	- Old artworks are refreshed (status/likes), and only new artworks are downloaded.
	- Checkpoint metadata writes may occur during refresh for better interruption recovery.

### Run Report TXT
- Each run writes a report file like `download_run_YYYYMMDD_HHMMSS_mmmmmm.txt` in `dest_dir`.
- If a same-name file already exists, `_1`, `_2`, ... suffix is appended automatically.
- The report includes:
  - download start/end time
  - argument values from `download_by_tag` except `dest_dir` and `phpsessid`
  - URL/file statistics

### Output Files
After a successful run, you will usually get:
- downloaded images in `dest_dir`
- `tags.json`: artwork metadata map keyed by artwork id
- `tags.index.json`: precomputed sort indexes (`likes`, `post_date`, `artwork_id`, each with `asc`/`desc`)
- `download_run_*.txt`: run report

Typical `tags.json` fields include:
- `artwork_id`, `author_id`, `author_name`, `post_date`, `likes`, `tags`
- `local_files`
- `url_status`, `download_status`
- `first_seen_at`, `last_refreshed_at`, `last_download_at`
- optional `url_error`

### Offline Local Viewer
- Run:
  - `python pixiv_local_viewer.py --image-root "C:\\Users\\YourName\\Downloads"`
	- `python pixiv_local_viewer.py --metadata "C:\\Users\\YourName\\Downloads\\tags.json"`
- Path precedence for metadata: `--metadata` > `CONTROL_TAGS_JSON_PATH` in `pixiv_local_viewer.py` > fallback default.
- The viewer works offline using local files + metadata files.
- Supports:
	- include/any/exclude tag filtering
	- sorting by `post_date`, `likes`, `artwork_id`
	- multi-page preview (Prev/Next and Left/Right keys)
	- dataset gallery window with lazy loading
	- lightbox in same window after thumbnail double-click
	- lightbox controls: Left/Right image switch, Ctrl+mouse wheel zoom, double-click point zoom toggle, drag to pan

## Tag Logic
- `keyword=["a", "b"]`: OR search (fetches results for `a` and `b`, then deduplicates by artwork id)
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
- `only_r18=True` keeps only R-18 works. When enabled, search uses Pixiv `mode=r18` for better relevance/speed.

## Limit the Number of Artworks
- `max_artworks=K` limits how many artworks will be processed.

## Notes
- R-18 content requires a logged-in account with R-18 enabled.
- If requests fail, check your cookie validity and network access.
- Metadata and sort-index writes use atomic replace.
- On Windows, atomic replace now retries briefly to reduce transient file-lock (`WinError 5`) failures.
- `tags.json` and `tags.index.json` are always saved in final metadata stage when `with_tag=True`.

## A Personal Note from the Author
Each downloaded image filename is the Pixiv artwork ID.\
If you find an image you really like, please search it on Pixiv and leave a like.\
`tags.json` stores author and artwork metadata. If you can access Pixiv, please consider visiting Pixiv to support the artists.\
If everyone only downloads images and no one visits Pixiv, artists lose traffic and exposure.\
I have personally seen cases where artists were upset because their works were scraped and widely redistributed, while they received little or no feedback on Pixiv.\
I really do not want this project to cause that outcome, so I can only make this appeal here.\
Please support the artists, and thank you for understanding.
