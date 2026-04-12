import argparse
import json
import os
import re
import tkinter as tk
from tkinter import messagebox, ttk

try:
    from PIL import Image, ImageOps, ImageTk

    _PIL_AVAILABLE = True
except ImportError:
    Image = None
    ImageOps = None
    ImageTk = None
    _PIL_AVAILABLE = False


# Control variable: set this to your tags.json path.
# Example: r"C:\\Users\\YourName\\Pictures\\pixiv_down\\tags.json"
# Keep empty string to use command-line args or default behavior.
CONTROL_TAGS_JSON_PATH = r"C:\\Users\\YourName\\Pictures\\pixiv_down\\tags.json"


def _split_tags(text):
    if not text:
        return []
    parts = re.split(r"[\s,]+", text.strip())
    return [p.lower() for p in parts if p]


def _to_int(value, default=-1):
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_tags(record):
    tags = record.get("tags", [])
    if not isinstance(tags, list):
        return []
    return [str(t) for t in tags if str(t).strip()]


class LocalViewerApp:
    def __init__(self, root, metadata_path, image_root):
        self.root = root
        self.metadata_path = metadata_path
        self.image_root = image_root

        self.preview_photo = None
        self.current_preview_pid = None
        self.current_preview_files = []
        self.current_preview_index = 0
        self.current_ordered_ids = None
        self.pid_files_cache = {}

        self.by_id = self._load_metadata()
        self.tag_to_ids = self._build_tag_index(self.by_id)
        self.sort_index_path = self._get_sort_index_path()
        self.sorted_indexes = self._load_or_build_sorted_indexes()

        self.root.title("Pixiv Local Viewer (Offline)")
        self.root.geometry("1360x780")

        self._build_controls()
        self._build_table()
        self.apply_filters()

    def _load_metadata(self):
        if not os.path.exists(self.metadata_path):
            raise FileNotFoundError(f"Metadata not found: {self.metadata_path}")

        with open(self.metadata_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError("tags.json must be a JSON object keyed by artwork id")

        normalized = {}
        for pid, record in data.items():
            if not isinstance(record, dict):
                continue
            rec = dict(record)
            rec["artwork_id"] = str(pid)
            rec["tags"] = _safe_tags(rec)
            local_files = rec.get("local_files", [])
            if not isinstance(local_files, list):
                local_files = []
            rec["local_files"] = [str(x) for x in local_files if str(x).strip()]
            normalized[str(pid)] = rec
        return normalized

    def _build_tag_index(self, by_id):
        index = {}
        for pid, record in by_id.items():
            for tag in record.get("tags", []):
                key = tag.lower()
                if key not in index:
                    index[key] = set()
                index[key].add(pid)
        return index

    def _get_sort_index_path(self):
        metadata_base, _ = os.path.splitext(self.metadata_path)
        return metadata_base + ".index.json"

    @staticmethod
    def _normalize_index_list(values):
        if not isinstance(values, list):
            return []
        return [str(v) for v in values]

    def _validate_sort_indexes(self, sort_indexes):
        if not isinstance(sort_indexes, dict):
            return False

        expected_ids = set(self.by_id.keys())
        required_keys = ("likes", "post_date", "artwork_id")
        for key in required_keys:
            order_map = sort_indexes.get(key)
            if not isinstance(order_map, dict):
                return False

            asc = self._normalize_index_list(order_map.get("asc"))
            desc = self._normalize_index_list(order_map.get("desc"))
            if len(asc) != len(expected_ids) or len(desc) != len(expected_ids):
                return False
            if set(asc) != expected_ids or set(desc) != expected_ids:
                return False

        return True

    def _persist_sort_indexes(self, sort_indexes):
        payload = {
            "version": 1,
            "generated_at": "ui_fallback",
            "artwork_count": len(self.by_id),
            "sort_indexes": sort_indexes,
        }
        try:
            temp_path = self.sort_index_path + ".tmp"
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(temp_path, self.sort_index_path)
        except OSError:
            pass

    def _load_or_build_sorted_indexes(self):
        try:
            with open(self.sort_index_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            loaded = payload.get("sort_indexes")
            if self._validate_sort_indexes(loaded):
                return {
                    "likes": {
                        "asc": self._normalize_index_list(loaded["likes"]["asc"]),
                        "desc": self._normalize_index_list(loaded["likes"]["desc"]),
                    },
                    "post_date": {
                        "asc": self._normalize_index_list(loaded["post_date"]["asc"]),
                        "desc": self._normalize_index_list(loaded["post_date"]["desc"]),
                    },
                    "artwork_id": {
                        "asc": self._normalize_index_list(loaded["artwork_id"]["asc"]),
                        "desc": self._normalize_index_list(loaded["artwork_id"]["desc"]),
                    },
                }
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            pass

        built = self._build_sorted_indexes(self.by_id)
        self._persist_sort_indexes(built)
        return built

    def _build_sorted_indexes(self, by_id):
        all_ids = list(by_id.keys())
        likes_asc = sorted(all_ids, key=lambda pid: _to_int(by_id[pid].get("likes"), -1))
        dates_asc = sorted(all_ids, key=lambda pid: str(by_id[pid].get("post_date") or ""))
        artwork_asc = sorted(all_ids, key=lambda pid: str(by_id[pid].get("artwork_id") or pid))

        return {
            "likes": {"asc": likes_asc, "desc": list(reversed(likes_asc))},
            "post_date": {"asc": dates_asc, "desc": list(reversed(dates_asc))},
            "artwork_id": {"asc": artwork_asc, "desc": list(reversed(artwork_asc))},
        }

    def _order_filtered_ids(self, filtered_ids, sort_by, order):
        sort_key = sort_by if sort_by in self.sorted_indexes else "post_date"
        sort_order = "desc" if order == "desc" else "asc"
        ordered_all = self.sorted_indexes[sort_key][sort_order]
        return [pid for pid in ordered_all if pid in filtered_ids]

    def _build_controls(self):
        frame = ttk.Frame(self.root, padding=8)
        frame.pack(fill=tk.X)

        ttk.Label(frame, text="Include tags (AND)").grid(row=0, column=0, sticky=tk.W, padx=4, pady=4)
        self.include_entry = ttk.Entry(frame, width=30)
        self.include_entry.grid(row=0, column=1, sticky=tk.W, padx=4, pady=4)

        ttk.Label(frame, text="Any tags (OR)").grid(row=0, column=2, sticky=tk.W, padx=4, pady=4)
        self.any_entry = ttk.Entry(frame, width=30)
        self.any_entry.grid(row=0, column=3, sticky=tk.W, padx=4, pady=4)

        ttk.Label(frame, text="Exclude tags").grid(row=1, column=0, sticky=tk.W, padx=4, pady=4)
        self.exclude_entry = ttk.Entry(frame, width=30)
        self.exclude_entry.grid(row=1, column=1, sticky=tk.W, padx=4, pady=4)

        ttk.Label(frame, text="Sort by").grid(row=1, column=2, sticky=tk.W, padx=4, pady=4)
        self.sort_by = ttk.Combobox(frame, width=18, state="readonly", values=["post_date", "likes", "artwork_id"])
        self.sort_by.set("post_date")
        self.sort_by.grid(row=1, column=3, sticky=tk.W, padx=4, pady=4)

        ttk.Label(frame, text="Order").grid(row=1, column=4, sticky=tk.W, padx=4, pady=4)
        self.sort_order = ttk.Combobox(frame, width=10, state="readonly", values=["desc", "asc"])
        self.sort_order.set("desc")
        self.sort_order.grid(row=1, column=5, sticky=tk.W, padx=4, pady=4)

        ttk.Button(frame, text="Search", command=self.apply_filters).grid(row=0, column=4, sticky=tk.W, padx=4, pady=4)
        ttk.Button(frame, text="Reset", command=self.reset_filters).grid(row=0, column=5, sticky=tk.W, padx=4, pady=4)
        ttk.Button(frame, text="Open Gallery", command=self._open_dataset_gallery).grid(
            row=0,
            column=6,
            sticky=tk.W,
            padx=4,
            pady=4,
        )

        self.status_label = ttk.Label(frame, text="")
        self.status_label.grid(row=2, column=0, columnspan=7, sticky=tk.W, padx=4, pady=6)

    @staticmethod
    def _gallery_sort_key(path):
        name = os.path.basename(path)
        match = re.match(r"^(\d+)_p(\d+)", name)
        if match:
            return (int(match.group(1)), int(match.group(2)), name)
        return (10**12, 10**12, name)

    def _collect_dataset_image_paths(self, ordered_ids):
        dataset_paths = []
        for pid in ordered_ids:
            record = self.by_id.get(pid, {})
            dataset_paths.extend(self._resolve_all_file_paths(record))
        return dataset_paths

    @staticmethod
    def _open_viewer_or_message(path):
        ok, exc = LocalViewerApp._open_path_in_viewer(path)
        if not ok:
            messagebox.showerror("Open Image", f"Failed to open file:\n{path}\n\n{exc}")

    def _open_gallery_lightbox(self, paths, start_index):
        if not paths:
            return

        index = max(0, min(int(start_index), len(paths) - 1))

        viewer = tk.Toplevel(self.root)
        viewer.title("Gallery Image Viewer")
        viewer.geometry("1200x900")
        viewer.minsize(640, 480)

        outer = ttk.Frame(viewer, padding=8)
        outer.pack(fill=tk.BOTH, expand=True)

        control = ttk.Frame(outer)
        control.pack(fill=tk.X, pady=(0, 8))

        prev_btn = ttk.Button(control, text="Prev")
        prev_btn.pack(side=tk.LEFT)

        next_btn = ttk.Button(control, text="Next")
        next_btn.pack(side=tk.LEFT, padx=(6, 0))

        counter_label = ttk.Label(control, text="")
        counter_label.pack(side=tk.LEFT, padx=(12, 0))

        ttk.Label(
            control,
            text="Left/Right: next image  |  Ctrl+Wheel: zoom  |  Double-click: toggle zoom  |  Drag: pan",
        ).pack(side=tk.RIGHT)

        canvas = tk.Canvas(outer, highlightthickness=0, bg="#101010")
        canvas.pack(fill=tk.BOTH, expand=True)

        path_label = ttk.Label(outer, text="", wraplength=1100)
        path_label.pack(fill=tk.X, pady=(8, 0))

        state = {
            "index": index,
            "photo": None,
            "resize_job": None,
            "pil_image": None,
            "fit_scale": 1.0,
            "zoom_factor": 1.0,
            "offset_x": 0.0,
            "offset_y": 0.0,
            "drag_last": None,
        }

        def _canvas_size():
            return max(220, canvas.winfo_width()), max(220, canvas.winfo_height())

        def _clamp_offsets():
            if state["pil_image"] is None:
                state["offset_x"] = 0.0
                state["offset_y"] = 0.0
                return

            cw, ch = _canvas_size()
            img_w, img_h = state["pil_image"].size
            scale = state["fit_scale"] * state["zoom_factor"]
            scaled_w = img_w * scale
            scaled_h = img_h * scale

            if scaled_w <= cw:
                state["offset_x"] = 0.0
            else:
                max_x = (scaled_w - cw) / 2.0
                state["offset_x"] = max(-max_x, min(max_x, state["offset_x"]))

            if scaled_h <= ch:
                state["offset_y"] = 0.0
            else:
                max_y = (scaled_h - ch) / 2.0
                state["offset_y"] = max(-max_y, min(max_y, state["offset_y"]))

        def _recompute_fit_scale(keep_effective_scale):
            if state["pil_image"] is None:
                state["fit_scale"] = 1.0
                state["zoom_factor"] = 1.0
                state["offset_x"] = 0.0
                state["offset_y"] = 0.0
                return

            cw, ch = _canvas_size()
            img_w, img_h = state["pil_image"].size
            safe_w = max(1, img_w)
            safe_h = max(1, img_h)
            new_fit = min(cw / safe_w, ch / safe_h, 1.0)
            if new_fit <= 0:
                new_fit = 1.0

            if keep_effective_scale:
                old_effective = state["fit_scale"] * state["zoom_factor"]
                state["fit_scale"] = new_fit
                state["zoom_factor"] = old_effective / new_fit if new_fit > 0 else 1.0
            else:
                state["fit_scale"] = new_fit
                state["zoom_factor"] = 1.0
                state["offset_x"] = 0.0
                state["offset_y"] = 0.0

            state["zoom_factor"] = max(0.2, min(16.0, state["zoom_factor"]))
            _clamp_offsets()

        def _draw_current_image():
            canvas.delete("all")

            if state["pil_image"] is None:
                canvas.create_text(
                    24,
                    24,
                    anchor="nw",
                    text="Cannot preview this image",
                    fill="#f0f0f0",
                )
                state["photo"] = None
                return

            _clamp_offsets()

            img_w, img_h = state["pil_image"].size
            scale = state["fit_scale"] * state["zoom_factor"]
            target_w = max(1, int(round(img_w * scale)))
            target_h = max(1, int(round(img_h * scale)))

            resampling = getattr(Image, "Resampling", Image)
            rendered = state["pil_image"].resize((target_w, target_h), resample=resampling.LANCZOS)
            state["photo"] = ImageTk.PhotoImage(rendered)

            cw, ch = _canvas_size()
            center_x = (cw / 2.0) + state["offset_x"]
            center_y = (ch / 2.0) + state["offset_y"]
            canvas.create_image(center_x, center_y, anchor="center", image=state["photo"])

        def _set_zoom_at_point(target_zoom, point_x, point_y):
            if state["pil_image"] is None:
                return

            bounded = max(0.2, min(16.0, float(target_zoom)))
            current_zoom = state["zoom_factor"]
            if abs(bounded - current_zoom) < 1e-6:
                return

            old_scale = state["fit_scale"] * current_zoom
            new_scale = state["fit_scale"] * bounded

            cw, ch = _canvas_size()
            center_x = (cw / 2.0) + state["offset_x"]
            center_y = (ch / 2.0) + state["offset_y"]

            rel_x = (point_x - center_x) / old_scale
            rel_y = (point_y - center_y) / old_scale

            new_center_x = point_x - (rel_x * new_scale)
            new_center_y = point_y - (rel_y * new_scale)

            state["zoom_factor"] = bounded
            state["offset_x"] = new_center_x - (cw / 2.0)
            state["offset_y"] = new_center_y - (ch / 2.0)
            _clamp_offsets()

        def _load_current_image(reset_view):
            idx = state["index"]
            path = paths[idx]

            try:
                with Image.open(path) as img:
                    img = ImageOps.exif_transpose(img)
                    mode = "RGBA" if "A" in img.getbands() else "RGB"
                    state["pil_image"] = img.convert(mode).copy()
            except OSError as exc:
                state["pil_image"] = None
                canvas.delete("all")
                canvas.create_text(
                    24,
                    24,
                    anchor="nw",
                    text=f"Cannot preview image:\n{exc}",
                    fill="#f0f0f0",
                )
            else:
                _recompute_fit_scale(keep_effective_scale=not reset_view)
                _draw_current_image()

            zoom_pct = int(round(state["fit_scale"] * state["zoom_factor"] * 100))
            counter_label.configure(text=f"{idx + 1}/{len(paths)}  |  {zoom_pct}%")
            path_label.configure(text=path)

            prev_btn.configure(state=(tk.NORMAL if idx > 0 else tk.DISABLED))
            next_btn.configure(state=(tk.NORMAL if idx < len(paths) - 1 else tk.DISABLED))

        def go_prev():
            if state["index"] <= 0:
                return
            state["index"] -= 1
            _load_current_image(reset_view=True)

        def go_next():
            if state["index"] >= len(paths) - 1:
                return
            state["index"] += 1
            _load_current_image(reset_view=True)

        def open_external_current(_event=None):
            self._open_viewer_or_message(paths[state["index"]])

        def schedule_rerender(_event=None):
            if state["resize_job"] is not None:
                viewer.after_cancel(state["resize_job"])
            state["resize_job"] = viewer.after(120, rerender_after_resize)

        def rerender_after_resize():
            if state["pil_image"] is None:
                return
            _recompute_fit_scale(keep_effective_scale=True)
            _draw_current_image()
            idx = state["index"]
            zoom_pct = int(round(state["fit_scale"] * state["zoom_factor"] * 100))
            counter_label.configure(text=f"{idx + 1}/{len(paths)}  |  {zoom_pct}%")

        def on_zoom_wheel(event):
            direction = 1 if event.delta > 0 else -1
            step = 1.15 if direction > 0 else (1.0 / 1.15)
            _set_zoom_at_point(state["zoom_factor"] * step, event.x, event.y)
            _draw_current_image()
            idx = state["index"]
            zoom_pct = int(round(state["fit_scale"] * state["zoom_factor"] * 100))
            counter_label.configure(text=f"{idx + 1}/{len(paths)}  |  {zoom_pct}%")
            return "break"

        def on_zoom_button(step, event):
            _set_zoom_at_point(state["zoom_factor"] * step, event.x, event.y)
            _draw_current_image()
            idx = state["index"]
            zoom_pct = int(round(state["fit_scale"] * state["zoom_factor"] * 100))
            counter_label.configure(text=f"{idx + 1}/{len(paths)}  |  {zoom_pct}%")
            return "break"

        def on_double_click_zoom(event):
            target = 2.5 if state["zoom_factor"] <= 1.05 else 1.0
            _set_zoom_at_point(target, event.x, event.y)
            _draw_current_image()
            idx = state["index"]
            zoom_pct = int(round(state["fit_scale"] * state["zoom_factor"] * 100))
            counter_label.configure(text=f"{idx + 1}/{len(paths)}  |  {zoom_pct}%")
            return "break"

        def on_pan_start(event):
            state["drag_last"] = (event.x, event.y)
            return "break"

        def on_pan_drag(event):
            if state["drag_last"] is None:
                return "break"
            last_x, last_y = state["drag_last"]
            dx = event.x - last_x
            dy = event.y - last_y
            state["drag_last"] = (event.x, event.y)
            state["offset_x"] += dx
            state["offset_y"] += dy
            _draw_current_image()
            return "break"

        def on_pan_end(_event):
            state["drag_last"] = None
            return "break"

        prev_btn.configure(command=go_prev)
        next_btn.configure(command=go_next)

        viewer.bind("<Left>", lambda _e: go_prev())
        viewer.bind("<Right>", lambda _e: go_next())
        viewer.bind("<Escape>", lambda _e: viewer.destroy())
        viewer.bind("<Configure>", schedule_rerender)

        path_label.bind("<Double-Button-1>", open_external_current)

        canvas.bind("<Control-MouseWheel>", on_zoom_wheel)
        canvas.bind("<Control-Button-4>", lambda e: on_zoom_button(1.15, e))
        canvas.bind("<Control-Button-5>", lambda e: on_zoom_button(1.0 / 1.15, e))
        canvas.bind("<Double-Button-1>", on_double_click_zoom)
        canvas.bind("<ButtonPress-1>", on_pan_start)
        canvas.bind("<B1-Motion>", on_pan_drag)
        canvas.bind("<ButtonRelease-1>", on_pan_end)

        viewer.focus_force()
        _load_current_image(reset_view=True)

    @staticmethod
    def _create_gallery_thumb(path, thumb_size):
        if not _PIL_AVAILABLE:
            return None
        try:
            with Image.open(path) as img:
                img = ImageOps.exif_transpose(img)
                mode = "RGBA" if "A" in img.getbands() else "RGB"
                img = img.convert(mode)
                resampling = getattr(Image, "Resampling", Image)
                img.thumbnail(thumb_size, resample=resampling.LANCZOS)

                bg_mode = "RGBA" if mode == "RGBA" else "RGB"
                bg_color = (20, 20, 20, 255) if bg_mode == "RGBA" else (20, 20, 20)
                canvas = Image.new(bg_mode, thumb_size, bg_color)
                x = (thumb_size[0] - img.width) // 2
                y = (thumb_size[1] - img.height) // 2
                if bg_mode == "RGBA":
                    canvas.alpha_composite(img, (x, y))
                    canvas = canvas.convert("RGB")
                else:
                    canvas.paste(img, (x, y))
                return ImageTk.PhotoImage(canvas)
        except OSError:
            return None

    def _open_dataset_gallery(self):
        if self.current_ordered_ids is None:
            ordered_ids = self.sorted_indexes["artwork_id"]["asc"]
        else:
            ordered_ids = self.current_ordered_ids
        paths = self._collect_dataset_image_paths(ordered_ids)
        if not paths:
            messagebox.showinfo("Gallery", "No local images found for current search/sort results.")
            return

        if not _PIL_AVAILABLE:
            messagebox.showinfo(
                "Gallery",
                "Gallery thumbnails require Pillow. Install with:\npython -m pip install pillow",
            )
            return

        gallery = tk.Toplevel(self.root)
        gallery.title("Dataset Gallery")
        gallery.geometry("1320x860")

        outer = ttk.Frame(gallery, padding=8)
        outer.pack(fill=tk.BOTH, expand=True)

        info = ttk.Label(
            outer,
            text=(
                f"Artworks in current result: {len(ordered_ids)}  |  "
                f"Total images: {len(paths)}  |  "
                "Double-click thumbnail to open"
            ),
        )
        info.pack(fill=tk.X, pady=(0, 8))

        canvas_holder = ttk.Frame(outer)
        canvas_holder.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(canvas_holder, highlightthickness=0)
        vbar = ttk.Scrollbar(canvas_holder, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=vbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vbar.pack(side=tk.RIGHT, fill=tk.Y)

        inner = ttk.Frame(canvas)
        inner_window = canvas.create_window((0, 0), window=inner, anchor="nw")

        state = {
            "paths": paths,
            "loaded": 0,
            "batch_size": 120,
            "cols": 6,
            "thumb_size": (170, 170),
            "thumb_refs": [],
            "cells": [],
            "inner": inner,
            "canvas": canvas,
        }

        def load_next_batch():
            start = state["loaded"]
            end = min(start + state["batch_size"], len(state["paths"]))
            for idx in range(start, end):
                path = state["paths"][idx]
                row = idx // state["cols"]
                col = idx % state["cols"]

                cell = ttk.Frame(state["inner"], padding=5)
                cell.grid(row=row, column=col, sticky="n")

                photo = self._create_gallery_thumb(path, state["thumb_size"])
                if photo is None:
                    thumb_label = tk.Label(
                        cell,
                        text="Preview unavailable",
                        width=24,
                        height=10,
                        bg="#202020",
                        fg="#f0f0f0",
                    )
                else:
                    thumb_label = tk.Label(cell, image=photo, bg="#202020")
                    state["thumb_refs"].append(photo)

                thumb_label.pack(fill=tk.BOTH, expand=True)

                file_label = ttk.Label(cell, text=os.path.basename(path), wraplength=170)
                file_label.pack(fill=tk.X, pady=(4, 0))

                for widget in (cell, thumb_label, file_label):
                    widget.bind(
                        "<Double-Button-1>",
                        lambda _e, i=idx, p_list=state["paths"]: self._open_gallery_lightbox(p_list, i),
                    )

                state["cells"].append(cell)

            state["loaded"] = end
            info.configure(text=f"Total images: {len(paths)}  |  Loaded: {state['loaded']}")

        def maybe_load_more():
            if state["loaded"] >= len(state["paths"]):
                return
            y1, y2 = state["canvas"].yview()
            if y2 >= 0.92:
                load_next_batch()

        def on_inner_configure(_event=None):
            bbox = canvas.bbox("all")
            if bbox:
                canvas.configure(scrollregion=bbox)
            maybe_load_more()

        def on_canvas_configure(event):
            canvas.itemconfigure(inner_window, width=event.width)
            maybe_load_more()

        def on_mousewheel(event):
            delta = int(-1 * (event.delta / 120)) if event.delta else 0
            if delta != 0:
                canvas.yview_scroll(delta, "units")
                maybe_load_more()
            return "break"

        inner.bind("<Configure>", on_inner_configure)
        canvas.bind("<Configure>", on_canvas_configure)
        canvas.bind("<MouseWheel>", on_mousewheel)
        inner.bind("<MouseWheel>", on_mousewheel)

        load_next_batch()

    def _build_table(self):
        content_frame = ttk.Frame(self.root, padding=(8, 0, 8, 8))
        content_frame.pack(fill=tk.BOTH, expand=True)

        table_frame = ttk.Frame(content_frame)
        table_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        columns = ("artwork_id", "post_date", "likes", "author_name", "url_status", "download_status", "tags")
        self.table = ttk.Treeview(table_frame, columns=columns, show="headings")

        self.table.heading("artwork_id", text="Artwork ID")
        self.table.heading("post_date", text="Post Date")
        self.table.heading("likes", text="Likes")
        self.table.heading("author_name", text="Author")
        self.table.heading("url_status", text="URL Status")
        self.table.heading("download_status", text="Download Status")
        self.table.heading("tags", text="Tags")

        self.table.column("artwork_id", width=110, anchor=tk.W)
        self.table.column("post_date", width=100, anchor=tk.W)
        self.table.column("likes", width=80, anchor=tk.E)
        self.table.column("author_name", width=160, anchor=tk.W)
        self.table.column("url_status", width=120, anchor=tk.W)
        self.table.column("download_status", width=160, anchor=tk.W)
        self.table.column("tags", width=320, anchor=tk.W)

        ybar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.table.yview)
        self.table.configure(yscrollcommand=ybar.set)

        self.table.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ybar.pack(side=tk.RIGHT, fill=tk.Y)

        self.table.bind("<<TreeviewSelect>>", self._on_table_select)
        self.table.bind("<Double-1>", self.open_selected_image)

        preview_frame = ttk.LabelFrame(content_frame, text="Preview", padding=8)
        preview_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))
        preview_frame.pack_propagate(False)
        preview_frame.configure(width=460)

        nav_frame = ttk.Frame(preview_frame)
        nav_frame.pack(fill=tk.X, pady=(0, 8))

        self.preview_prev_btn = ttk.Button(nav_frame, text="Prev", command=self._show_prev_image)
        self.preview_prev_btn.pack(side=tk.LEFT)

        self.preview_next_btn = ttk.Button(nav_frame, text="Next", command=self._show_next_image)
        self.preview_next_btn.pack(side=tk.RIGHT)

        self.preview_page_label = ttk.Label(nav_frame, text="0/0", anchor="center")
        self.preview_page_label.pack(fill=tk.X, expand=True)

        self.preview_image_label = tk.Label(
            preview_frame,
            text="Select an artwork to preview",
            anchor="center",
            justify="center",
            bg="#101010",
            fg="#f0f0f0",
            wraplength=420,
        )
        self.preview_image_label.pack(fill=tk.BOTH, expand=True)

        self.preview_path_label = ttk.Label(preview_frame, text="", wraplength=420)
        self.preview_path_label.pack(fill=tk.X, pady=(8, 0))

        preview_hint = "Double-click row: open current preview image in system picture viewer."
        self.preview_hint_label = ttk.Label(preview_frame, text=preview_hint, wraplength=420)
        self.preview_hint_label.pack(fill=tk.X, pady=(6, 0))

        self.preview_image_label.bind("<Configure>", lambda _e: self._render_preview())
        self.root.bind("<Left>", lambda _e: self._show_prev_image())
        self.root.bind("<Right>", lambda _e: self._show_next_image())
        self._update_preview_controls()

        bottom = ttk.Frame(self.root, padding=8)
        bottom.pack(fill=tk.X)
        ttk.Button(bottom, text="Open Current Preview In Viewer", command=self.open_selected_image).pack(side=tk.LEFT)

    def reset_filters(self):
        self.include_entry.delete(0, tk.END)
        self.any_entry.delete(0, tk.END)
        self.exclude_entry.delete(0, tk.END)
        self.sort_by.set("post_date")
        self.sort_order.set("desc")
        self.apply_filters()

    def _filter_ids(self, include_tags, any_tags, exclude_tags):
        all_ids = set(self.by_id.keys())
        candidates = set(all_ids)

        for tag in include_tags:
            ids = self.tag_to_ids.get(tag, set())
            candidates &= ids

        if any_tags:
            any_ids = set()
            for tag in any_tags:
                any_ids |= self.tag_to_ids.get(tag, set())
            candidates &= any_ids

        if exclude_tags:
            exclude_ids = set()
            for tag in exclude_tags:
                exclude_ids |= self.tag_to_ids.get(tag, set())
            candidates -= exclude_ids

        return candidates

    def apply_filters(self):
        include_tags = _split_tags(self.include_entry.get())
        any_tags = _split_tags(self.any_entry.get())
        exclude_tags = _split_tags(self.exclude_entry.get())
        sort_by = self.sort_by.get().strip() or "post_date"
        order = self.sort_order.get().strip() or "desc"

        filtered_ids = self._filter_ids(include_tags, any_tags, exclude_tags)
        ordered_ids = self._order_filtered_ids(filtered_ids, sort_by, order)
        self.current_ordered_ids = list(ordered_ids)
        records = [self.by_id[i] for i in ordered_ids]

        for row in self.table.get_children():
            self.table.delete(row)

        for rec in records:
            tags_text = ", ".join(rec.get("tags", []))
            self.table.insert(
                "",
                tk.END,
                iid=rec["artwork_id"],
                values=(
                    rec.get("artwork_id", ""),
                    rec.get("post_date", ""),
                    rec.get("likes", ""),
                    rec.get("author_name", ""),
                    rec.get("url_status", ""),
                    rec.get("download_status", ""),
                    tags_text,
                ),
            )

        if ordered_ids:
            first_id = ordered_ids[0]
            self.table.selection_set(first_id)
            self.table.focus(first_id)
            self._show_record_preview(first_id)
        else:
            self.current_preview_pid = None
            self.current_preview_files = []
            self.current_preview_index = 0
            self._clear_preview("No results for current filters")
            self._update_preview_controls()

        self.status_label.configure(text=f"Loaded {len(records)} artworks from {self.metadata_path}")

    def _clear_preview(self, message):
        self.preview_photo = None
        self.preview_image_label.configure(image="", text=message)
        self.preview_path_label.configure(text="")

    def _on_table_select(self, _event=None):
        selected = self.table.selection()
        if not selected:
            self.current_preview_pid = None
            self.current_preview_files = []
            self.current_preview_index = 0
            self._clear_preview("Select an artwork to preview")
            self._update_preview_controls()
            return
        self._show_record_preview(selected[0])

    def _update_preview_controls(self):
        total = len(self.current_preview_files)
        if total <= 0:
            self.preview_page_label.configure(text="0/0")
            self.preview_prev_btn.configure(state=tk.DISABLED)
            self.preview_next_btn.configure(state=tk.DISABLED)
            return

        self.preview_page_label.configure(text=f"{self.current_preview_index + 1}/{total}")
        self.preview_prev_btn.configure(
            state=(tk.NORMAL if self.current_preview_index > 0 else tk.DISABLED)
        )
        self.preview_next_btn.configure(
            state=(tk.NORMAL if self.current_preview_index < total - 1 else tk.DISABLED)
        )

    def _load_preview_photo(self, path):
        if _PIL_AVAILABLE:
            try:
                with Image.open(path) as img:
                    img = ImageOps.exif_transpose(img)
                    max_width = max(220, self.preview_image_label.winfo_width() - 20)
                    max_height = max(220, self.preview_image_label.winfo_height() - 20)
                    resampling = getattr(Image, "Resampling", Image)
                    img.thumbnail((max_width, max_height), resample=resampling.LANCZOS)
                    return ImageTk.PhotoImage(img.copy()), None
            except OSError as exc:
                return None, f"Cannot preview image: {exc}"

        try:
            return tk.PhotoImage(file=path), None
        except tk.TclError:
            return None, "Preview for this format requires Pillow (pip install pillow)."

    def _render_preview(self):
        if not self.current_preview_files:
            self._update_preview_controls()
            return

        if self.current_preview_index >= len(self.current_preview_files):
            self.current_preview_index = len(self.current_preview_files) - 1
        if self.current_preview_index < 0:
            self.current_preview_index = 0

        path = self.current_preview_files[self.current_preview_index]
        photo, err = self._load_preview_photo(path)
        if photo is None:
            self._clear_preview(err or "Cannot preview this image")
            self.preview_path_label.configure(text=path)
            self._update_preview_controls()
            return

        self.preview_photo = photo
        self.preview_image_label.configure(image=self.preview_photo, text="")
        self.preview_path_label.configure(text=path)
        self._update_preview_controls()

    def _show_record_preview(self, pid):
        record = self.by_id.get(pid)
        if not record:
            self.current_preview_pid = None
            self.current_preview_files = []
            self.current_preview_index = 0
            self._clear_preview(f"Artwork {pid} not found")
            self._update_preview_controls()
            return

        files = self._resolve_all_file_paths(record)
        self.current_preview_pid = pid
        self.current_preview_files = files
        self.current_preview_index = 0

        if not files:
            self._clear_preview(f"No local files found for artwork {pid}")
            self._update_preview_controls()
            return

        self._render_preview()

    def _show_prev_image(self):
        if not self.current_preview_files or self.current_preview_index <= 0:
            return
        self.current_preview_index -= 1
        self._render_preview()

    def _show_next_image(self):
        if not self.current_preview_files or self.current_preview_index >= len(self.current_preview_files) - 1:
            return
        self.current_preview_index += 1
        self._render_preview()

    @staticmethod
    def _pid_page_sort_key(path):
        name = os.path.basename(path)
        match = re.search(r"_p(\d+)", name)
        if not match:
            return (10**9, name)
        return (int(match.group(1)), name)

    def _resolve_all_file_paths(self, record):
        resolved = []
        seen = set()
        pid = str(record.get("artwork_id", ""))

        if pid and pid in self.pid_files_cache:
            return list(self.pid_files_cache[pid])

        local_files = record.get("local_files", [])
        for file_name in local_files:
            if os.path.isabs(file_name):
                candidate = file_name
            else:
                candidate = os.path.join(self.image_root, file_name)

            if not os.path.isfile(candidate):
                continue
            norm = os.path.normcase(os.path.abspath(candidate))
            if norm in seen:
                continue
            seen.add(norm)
            resolved.append(candidate)

        if resolved:
            sorted_resolved = sorted(resolved, key=self._pid_page_sort_key)
            if pid:
                self.pid_files_cache[pid] = list(sorted_resolved)
            return sorted_resolved

        if not pid:
            return []

        fallback = []
        if os.path.isdir(self.image_root):
            prefix = f"{pid}_p"
            for name in os.listdir(self.image_root):
                if name.startswith(prefix):
                    candidate = os.path.join(self.image_root, name)
                    if os.path.isfile(candidate):
                        fallback.append(candidate)

        sorted_fallback = sorted(fallback, key=self._pid_page_sort_key)
        if pid:
            self.pid_files_cache[pid] = list(sorted_fallback)
        return sorted_fallback

    def _get_current_preview_path(self):
        if not self.current_preview_files:
            return None
        if self.current_preview_index < 0 or self.current_preview_index >= len(self.current_preview_files):
            return None
        return self.current_preview_files[self.current_preview_index]

    @staticmethod
    def _open_path_in_viewer(path):
        try:
            os.startfile(path)
            return True, None
        except OSError as exc:
            return False, exc

    def open_selected_image(self, _event=None):
        path = self._get_current_preview_path()
        if not path:
            selected = self.table.selection()
            if not selected:
                messagebox.showinfo("Open Image", "Please select an artwork first.")
                return
            pid = selected[0]
            record = self.by_id.get(pid)
            if not record:
                messagebox.showerror("Open Image", f"Artwork {pid} not found in memory.")
                return
            files = self._resolve_all_file_paths(record)
            path = files[0] if files else None

        if not path:
            messagebox.showwarning("Open Image", "No local file found for selected artwork.")
            return

        ok, exc = self._open_path_in_viewer(path)
        if not ok:
            messagebox.showerror("Open Image", f"Failed to open file:\n{path}\n\n{exc}")


def main():
    parser = argparse.ArgumentParser(description="Offline local viewer for Pixiv downloader metadata")
    parser.add_argument(
        "--metadata",
        default=None,
        help="Path to tags.json. Default: <image_root>/tags.json if --image-root is provided, else ./tags.json",
    )
    parser.add_argument(
        "--image-root",
        default=None,
        help="Folder containing downloaded images. Default: folder containing metadata file.",
    )
    args = parser.parse_args()

    metadata_path = args.metadata or CONTROL_TAGS_JSON_PATH
    image_root = args.image_root

    if isinstance(metadata_path, str):
        metadata_path = metadata_path.strip()
        if not metadata_path:
            metadata_path = None

    if metadata_path is None:
        if image_root:
            metadata_path = os.path.join(image_root, "tags.json")
        else:
            metadata_path = os.path.join(os.getcwd(), "tags.json")

    metadata_path = os.path.abspath(metadata_path)
    if image_root is None:
        image_root = os.path.dirname(metadata_path)
    image_root = os.path.abspath(image_root)

    root = tk.Tk()
    app = LocalViewerApp(root, metadata_path, image_root)
    root.mainloop()


if __name__ == "__main__":
    main()
