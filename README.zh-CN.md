# pixiv_downloader
通过标签/关键词下载 Pixiv 作品。支持多标签逻辑、标签过滤、AI 过滤、R-18 过滤、增量同步，以及离线本地查看器（图库/灯箱预览）。

## 依赖
- Python 3.8+
- `requests` 库
- 有效的 Pixiv 登录会话 Cookie（`PHPSESSID`）
- 可选：`Pillow`（本地查看器高质量预览/缩略图）

获取 `PHPSESSID` 可参考：https://sora.ink/archives/520

## 文件说明
- `pixiv_config.py`: 配置数据类
- `pixiv_session.py`: 会话与请求工具
- `pixiv_search.py`: 搜索与 URL 工具
- `pixiv_download.py`: 主要下载逻辑
- `pixiv_tag_download.py`: 示例入口脚本
- `pixiv_local_viewer.py`: 离线本地图片/元数据查看器

## 配置 pixiv_config.py
打开 `pixiv_config.py` 来修改默认参数，主要在 `DownloadConfig`：
- `store_path`: 默认下载目录
- `timeout`, `retry_times`, `fail_delay`: 请求行为
- `with_tag`: 把作品元数据保存到 `tags.json`
- `url_only`: 只输出 URL，不下载
- `num_threads`: 并发下载线程数
- `thread_delay`: 线程启动槽位延迟（秒）

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
2. （可选，本地查看器）安装 Pillow：
    - `pip install pillow`
3. 在浏览器中登录 https://www.pixiv.net
4. 复制你的 `PHPSESSID`（可选 `device_token`）Cookie 值。

## 基本用法
编辑 `pixiv_tag_download.py`，填写 Cookie：

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

### 增量同步模式
- `first_download=True`：从零开始执行完整下载流程。
    - 元数据先在内存中累计，最终阶段统一保存。
    - 该模式下点赞回填不再对每个 pid 进行 `tags.json` 检查点写入。
- `first_download=False`：启用增量同步。
    - 会读取已有 `tags.json`。
    - 会刷新旧作品状态/点赞，并只下载新作品。
    - 刷新过程中可能进行检查点写入，提升中断恢复能力。

### 运行报告 TXT
- 每次运行会在 `dest_dir` 下生成 `download_run_YYYYMMDD_HHMMSS_mmmmmm.txt`。
- 如果同名文件已存在，会自动追加 `_1`、`_2` 等后缀。
- 报告包含：
    - 下载开始/结束时间
    - `download_by_tag` 参数（不含 `dest_dir` 和 `phpsessid`）
    - URL/文件统计信息

### 输出文件
一次正常运行后通常会生成：
- `dest_dir` 下的图片文件
- `tags.json`：按作品 id 索引的元数据
- `tags.index.json`：排序索引（`likes`、`post_date`、`artwork_id`，每项含 `asc`/`desc`）
- `download_run_*.txt`：运行报告

`tags.json` 常见字段：
- `artwork_id`, `author_id`, `author_name`, `post_date`, `likes`, `tags`
- `local_files`
- `url_status`, `download_status`
- `first_seen_at`, `last_refreshed_at`, `last_download_at`
- 可选 `url_error`

### 离线本地查看器
- 运行：
    - `python pixiv_local_viewer.py --image-root "C:\\Users\\YourName\\Downloads"`
    - `python pixiv_local_viewer.py --metadata "C:\\Users\\YourName\\Downloads\\tags.json"`
- 元数据路径优先级：`--metadata` > `pixiv_local_viewer.py` 中 `CONTROL_TAGS_JSON_PATH` > 默认回退路径。
- 查看器离线工作（仅依赖本地图片和元数据文件）。
- 支持：
    - include/any/exclude 标签筛选
    - 按 `post_date`、`likes`、`artwork_id` 排序
    - 多页作品预览（Prev/Next + 左右方向键）
    - 懒加载滚动图库
    - 双击缩略图进入同窗口灯箱预览
    - 灯箱操作：左右切图、Ctrl+滚轮缩放、双击定点缩放切换、拖拽平移

## 标签逻辑
- `keyword=["a", "b"]`: OR 搜索（分别搜索 `a` 和 `b`，再按作品 id 去重）
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
- `only_r18=True` 只保留 R-18 作品。启用后会使用 Pixiv `mode=r18` 搜索，提高相关性/速度。

## 限制作品数量
- `max_artworks=K` 可限制处理作品数量。

## 备注
- R-18 内容需要账号已开通 R-18 访问权限。
- 若请求失败，请检查 Cookie 是否有效与网络状况。
- 元数据与排序索引使用原子替换写入。
- 在 Windows 下，原子替换会短暂重试以降低临时文件锁导致的 `WinError 5` 失败概率。
- 当 `with_tag=True` 时，最终阶段会保存 `tags.json` 和 `tags.index.json`。

## 作者的一些个人建议
每张图片的名称就是那个作品的pixiv号码\
如果见到喜欢的图可以去pixiv上搜一下点个赞\
`tags.json`里记录了每张作品的作者等其他信息，如果有梯子的话请上p站支持一下作者\
毕竟如果我们把图全都爬下来大家都不去看p站的话画师没流量就不好了\
以往我确实见过作者因为自己的图被爬了并且广传而自己得不到作品反馈而生气的案例\
我很不希望我做的东西最后会造成这种结果，因此只能在此呼吁\
希望大家支持且理解\
感谢！