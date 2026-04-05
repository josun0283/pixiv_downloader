from pixiv_download import download_by_tag


if __name__ == "__main__":
    # Example usage:
    download_by_tag(
        keyword=["ansy"],
        dest_dir=r"paste your save path here",
        phpsessid="paste your PHPSESSID here",
        device_token=None,
        pages=1,
        # include_tags=["tag_1", "tag_2"],
        # any_tags=["tag_3", "tag_4"],
        # exclude_tags=["tag_5"],
        filter_ai=True,
        filter_r18=False,
        max_artworks=3,
    )
