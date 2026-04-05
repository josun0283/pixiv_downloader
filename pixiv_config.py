import dataclasses
import datetime
from typing import Tuple


@dataclasses.dataclass
class RankingConfig:
    # Start date
    start_date: datetime.date = datetime.date(2026, 4, 4)
    # Date range: [start, start + range - 1]
    range: int = 1
    # Which ranking list
    ranking_modes: Tuple = (
        "daily",
        "weekly",
        "monthly",
        "male",
        "female",
        "daily_ai",
        "daily_r18",
        "weekly_r18",
        "male_r18",
        "female_r18",
        "daily_r18_ai",
    )
    mode: str = "daily"  # Choose from the above
    # Illustration, manga, ugoira, all
    content_modes: Tuple = ("all", "illust", "manga", "ugoira")
    content_mode: str = "all"  # Choose from the above
    # Download top k in each ranking
    num_artwork: int = 3

    def __post_init__(self):
        assert self.mode in self.ranking_modes, f"Mode {self.mode} not supported"
        assert (
            self.content_mode in self.content_modes
        ), f"Content mode {self.content_mode} not supported"


@dataclasses.dataclass
class DownloadConfig:
    timeout: float = 4  # Timeout for requests
    retry_times: int = 10  # Retry times for requests
    fail_delay: float = 1  # Waiting time (s) after failure
    store_path: str = "images"  # Image save path
    with_tag: bool = True  # Whether to download tags to a separate json file
    url_only: bool = False  # Only download artwork urls
    num_threads: int = 16  # Number of parallel threads
    thread_delay: float = 1  # Waiting time (s) after thread start
