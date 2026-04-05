# pixiv_downloader
通过标签/关键词下载 Pixiv 作品。支持多标签逻辑、标签过滤、AI 过滤、R-18 过滤，以及最大下载数量限制。

## 依赖
- Python 3.8+
- `requests` 库
- 有效的 Pixiv 登录会话 Cookie（`PHPSESSID`）

获取 `PHPSESSID` 可参考：https://sora.ink/archives/520

## 文件说明
- `pixiv_config.py`: 配置数据类
- `pixiv_session.py`: 会话与请求工具
- `pixiv_search.py`: 搜索与 URL 工具
- `pixiv_download.py`: 主要下载逻辑
- `pixiv_tag_download.py`: 示例入口脚本

## 配置 pixiv_config.py
打开 `pixiv_config.py` 来修改默认参数，主要在 `DownloadConfig`：
- `store_path`: 默认下载目录
- `timeout`, `retry_times`, `fail_delay`: 请求行为
- `with_tag`: 保存标签到 `tags.json`
- `url_only`: 只输出 URL，不下载
- `num_threads`, `thread_delay`: 预留的并发下载参数

示例：
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

## 安装与准备
1. 安装依赖：
   - `pip install requests`
2. 在浏览器中登录 https://www.pixiv.net
3. 复制你的 `PHPSESSID`（可选 `device_token`）Cookie 值。

## 基本用法
编辑 `pixiv_tag_download.py`，填写 Cookie：

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

## 标签逻辑
- `include_tags`: AND 逻辑（必须同时包含）
- `any_tags`: OR 逻辑（至少包含一个）
- `exclude_tags`: NOT 逻辑（必须不包含）

如果不打算使用这些参数，可以把这一段注释掉。

示例：
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

## AI 过滤
- `filter_ai=True` 可排除 AI 作品。

## R-18 过滤
- `filter_r18=True` 可排除 R-18 作品。

## 限制作品数量
- `max_artworks=K` 可限制处理作品数量。

## 备注
- R-18 内容需要账号已开通 R-18 访问权限。
- 若请求失败，请检查 Cookie 是否有效与网络状况。
