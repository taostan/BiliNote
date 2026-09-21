# app/routers/picker.py
# 本地文件/文件夹选择接口：浏览器拿不到绝对本地路径，由后端弹系统对话框回填。
import threading

from fastapi import APIRouter

from app.utils.response import ResponseWrapper as R

router = APIRouter()

# tkinter 对话框必须串行弹出，避免并发请求同时开多个窗口
_picker_lock = threading.Lock()

_VIDEO_FILETYPES = [
    ("视频/音频文件", "*.mp4 *.mkv *.avi *.mov *.flv *.wmv *.webm *.ts *.mp3 *.m4a *.wav *.aac *.flac"),
    ("所有文件", "*.*"),
]


def _run_dialog(dialog_fn):
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        path = dialog_fn(filedialog) or ""
    finally:
        root.destroy()
    return path


@router.post("/pick_file")
def pick_file():
    """弹出系统文件选择对话框，返回选中的本地视频/音频文件绝对路径。取消返回空字符串。"""
    try:
        with _picker_lock:
            path = _run_dialog(
                lambda filedialog: filedialog.askopenfilename(
                    title="选择本地视频文件",
                    filetypes=_VIDEO_FILETYPES,
                )
            )
        return R.success({"path": path})
    except Exception as e:
        return R.error(msg=f"打开文件对话框失败: {e}")


@router.post("/pick_folder")
def pick_folder():
    """弹出系统文件夹选择对话框，返回选中的本地文件夹绝对路径。取消返回空字符串。"""
    try:
        with _picker_lock:
            path = _run_dialog(
                lambda filedialog: filedialog.askdirectory(
                    title="选择包含视频文件的文件夹",
                )
            )
        return R.success({"path": path})
    except Exception as e:
        return R.error(msg=f"打开文件夹对话框失败: {e}")
