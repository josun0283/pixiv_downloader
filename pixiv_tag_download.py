from pixiv_download import download_by_tag


if __name__ == "__main__":
    # OR tags: any_tags matches either tag.
    download_by_tag(
        keyword=["あのそよ", "ansy","爱素","素爱","そよあの","syan"],
        dest_dir=r"C:\\Users\\YourName\\Downloads",
        phpsessid="PASTE_YOUR_PHPSESSID_HERE",
        device_token=None,
        pages=9999,
        any_tags=["あのそよ", "ansy","爱素","素爱","そよあの","syan"],
        exclude_tags=["AI生成", "AIイラス", "AIイラスト"],
        filter_ai=True,
        filter_r18=True,
        only_r18=False,
        debug=True,
        first_download=True,
        max_artworks=None,
    )
