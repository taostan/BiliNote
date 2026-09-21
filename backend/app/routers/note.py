# app/routers/note.py
import json
import os
import uuid
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

from app.enmus.note_enums import DownloadQuality
from app.services.note import NoteGenerator, logger
from app.services.task_serial_executor import task_serial_executor
from app.utils.response import ResponseWrapper as R
from app.enmus.task_status_enums import TaskStatus

router = APIRouter()

# 本地文件夹批量模式下识别的媒体文件扩展名
MEDIA_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".webm", ".ts",
    ".mp3", ".m4a", ".wav", ".aac", ".flac",
}


class RecordRequest(BaseModel):
    video_id: str
    platform: str


class VideoRequest(BaseModel):
    video_url: str
    platform: str
    quality: DownloadQuality
    screenshot: Optional[bool] = False
    link: Optional[bool] = False
    model_name: str
    provider_id: str
    task_id: Optional[str] = None
    format: Optional[list] = []
    style: str = None
    extras: Optional[str] = None
    video_understanding: Optional[bool] = False
    video_interval: Optional[int] = 0
    grid_size: Optional[list] = []

    def validate_local_path(self):
        path = (self.video_url or "").strip()
        if not path:
            raise HTTPException(status_code=400, detail="本地文件路径不能为空")
        if not os.path.exists(path):
            raise HTTPException(status_code=400, detail=f"路径不存在: {path}")
        self.video_url = os.path.normpath(path)


def expand_local_paths(video_url: str) -> list:
    """把提交的路径展开为待处理的媒体文件列表。

    - 文件：直接返回 [video_url]（不校验扩展名，交给后端 ffmpeg 处理）
    - 文件夹：扫描一层内的媒体文件，按文件名排序
    """
    if os.path.isdir(video_url):
        files = []
        for name in sorted(os.listdir(video_url)):
            full = os.path.join(video_url, name)
            if os.path.isfile(full) and os.path.splitext(name)[1].lower() in MEDIA_EXTENSIONS:
                files.append(os.path.normpath(full))
        return files
    return [video_url]


NOTE_OUTPUT_DIR = os.getenv("NOTE_OUTPUT_DIR", "note_results")


def save_note_to_file(task_id: str, note):
    os.makedirs(NOTE_OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(NOTE_OUTPUT_DIR, f"{task_id}.json"), "w", encoding="utf-8") as f:
        json.dump(asdict(note), f, ensure_ascii=False, indent=2)


def run_note_task(task_id: str, video_url: str, platform: str, quality: DownloadQuality,
                  link: bool = False, screenshot: bool = False, model_name: str = None, provider_id: str = None,
                  _format: list = None, style: str = None, extras: str = None, video_understanding: bool = False,
                  video_interval=0, grid_size=[]
                  ):

    if not model_name or not provider_id:
        raise HTTPException(status_code=400, detail="请选择模型和提供者")

    def _execute_note_task():
        return NoteGenerator().generate(
            video_url=video_url,
            platform=platform,
            quality=quality,
            task_id=task_id,
            model_name=model_name,
            provider_id=provider_id,
            link=link,
            _format=_format,
            style=style,
            extras=extras,
            screenshot=screenshot,
            video_understanding=video_understanding,
            video_interval=video_interval,
            grid_size=grid_size,
        )

    logger.info(f"任务进入执行队列 (task_id={task_id})")
    note = task_serial_executor.run(_execute_note_task)
    logger.info(f"Note generated: {task_id}")
    if not note or not note.markdown:
        logger.warning(f"任务 {task_id} 执行失败，跳过保存")
        return
    save_note_to_file(task_id, note)

    # 自动建立向量索引（用于 AI 问答），失败不影响笔记生成
    try:
        from app.services.vector_store import VectorStoreManager
        VectorStoreManager().index_task(task_id)
    except Exception as e:
        logger.warning(f"向量索引失败（不影响笔记）: {e}")


@router.post('/delete_task')
def delete_task(data: RecordRequest):
    try:
        # TODO: 待持久化完成
        # NoteGenerator().delete_note(video_id=data.video_id, platform=data.platform)
        return R.success(msg='删除成功')
    except Exception as e:
        return R.error(msg=e)


@router.post("/generate_note")
def generate_note(data: VideoRequest, background_tasks: BackgroundTasks):
    try:
        data.validate_local_path()

        # 就绪门禁：本地转写引擎（fast-whisper / mlx-whisper）必须等模型下载完才能跑视频，
        # 否则任务会卡在首次下载（慢 / OOM / 截断），用户只看到一个静默失败的任务。
        from app.services.transcriber_config_manager import TranscriberConfigManager
        readiness = TranscriberConfigManager().is_model_ready()
        if not readiness["ready"]:
            logger.warning(f"拒绝 generate_note：{readiness['reason']}")
            return R.error(
                msg=readiness["reason"],
                code=300102,
                data={
                    "reason": "transcriber_model_not_ready",
                    "transcriber_type": readiness["transcriber_type"],
                    "model_size": readiness["model_size"],
                    "downloading": readiness["downloading"],
                },
            )

        # 文件夹批量模式：为每个媒体文件建一个任务；单文件模式只有一个
        if data.task_id:
            # 重试模式：只处理单文件，复用已有 task_id
            paths = [data.video_url]
        else:
            paths = expand_local_paths(data.video_url)
        if not paths:
            return R.error(msg="文件夹中没有可处理的视频或音频文件")

        task_ids = []
        task_titles = []
        for path in paths:
            if data.task_id:
                task_id = data.task_id
                logger.info(f"重试模式，复用已有 task_id={task_id}")
            else:
                task_id = str(uuid.uuid4())
            task_ids.append(task_id)
            task_titles.append(os.path.splitext(os.path.basename(path))[0])

            # 统一先写入 PENDING，表示已进入队列等待串行执行
            NoteGenerator()._update_status(task_id, TaskStatus.PENDING)

            background_tasks.add_task(run_note_task, task_id, path, data.platform, data.quality, data.link,
                                      data.screenshot, data.model_name, data.provider_id, data.format, data.style,
                                      data.extras, data.video_understanding, data.video_interval, data.grid_size)
        return R.success({
            "task_id": task_ids[0],
            "task_ids": task_ids,
            "task_titles": task_titles,
            "task_paths": paths,
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/task_status/{task_id}")
def get_task_status(task_id: str):
    status_path = os.path.join(NOTE_OUTPUT_DIR, f"{task_id}.status.json")
    result_path = os.path.join(NOTE_OUTPUT_DIR, f"{task_id}.json")

    # 优先读状态文件
    if os.path.exists(status_path):
        with open(status_path, "r", encoding="utf-8") as f:
            status_content = json.load(f)

        status = status_content.get("status")
        message = status_content.get("message", "")

        if status == TaskStatus.SUCCESS.value:
            # 成功状态的话，继续读取最终笔记内容
            if os.path.exists(result_path):
                with open(result_path, "r", encoding="utf-8") as rf:
                    result_content = json.load(rf)
                return R.success({
                    "status": status,
                    "result": result_content,
                    "message": message,
                    "task_id": task_id
                })
            else:
                # 理论上不会出现，保险处理
                return R.success({
                    "status": TaskStatus.PENDING.value,
                    "message": "任务完成，但结果文件未找到",
                    "task_id": task_id
                })

        if status == TaskStatus.FAILED.value:
            return R.error(message or "任务失败", code=500)

        # 处理中状态
        return R.success({
            "status": status,
            "message": message,
            "task_id": task_id
        })

    # 没有状态文件，但有结果
    if os.path.exists(result_path):
        with open(result_path, "r", encoding="utf-8") as f:
            result_content = json.load(f)
        return R.success({
            "status": TaskStatus.SUCCESS.value,
            "result": result_content,
            "task_id": task_id
        })

    # 什么都没有，默认PENDING
    return R.success({
        "status": TaskStatus.PENDING.value,
        "message": "任务排队中",
        "task_id": task_id
    })
