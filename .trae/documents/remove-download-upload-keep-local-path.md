# 删除在线下载与上传功能，只保留本地路径模式

## Context

用户不再需要"下载在线视频"和"上传视频文件"两条链路。目标：前端只能选择本地文件或本地文件夹，把路径提交给后端，后端对本地文件继续原有流程（ffmpeg 提取音频/封面 -> Whisper 转写 -> GPT 总结 -> 生成 Markdown 笔记）。所有在线平台下载器、上传接口、URL 校验、Cookie 管理全部删除。

约束：
- 不执行任何 pip install / 下载类命令（用户明确禁止），只改代码；requirements.txt 仅做文本清理。
- 不使用特殊字符（emoji 等）。
- 后端端口 8484，前端端口 3015，均不变。

## 一、后端删除

### 1. 删除在线下载器文件（backend/app/downloaders/）
- 删除：bilibili_downloader.py、bilibili_subtitle.py、bilibili_dm_patch.py、youtube_downloader.py、youtube_subtitle.py、douyin_downloader.py、douyin_helper/、kuaishou_downloader.py、kuaishou_helper/、xiaoyuzhoufm_download.py、common.py（先确认无本地引用）
- 保留：base.py（LocalDownloader 继承它，删掉其中 yt-dlp 相关常量 YDL_RETRY_OPTS/QUALITY_MAP 如无引用）、local_downloader.py

### 2. backend/app/services/constant.py
- SUPPORT_PLATFORM_MAP 只保留 `'local': LocalDownloader()`

### 3. backend/app/services/note.py
- 删除对已删下载器的 import（BilibiliDownloader、DouyinDownloader、YoutubeDownloader）
- generate() 中删除"尝试获取平台字幕"代码块与 skip_download 元信息分支（本地模式没有平台字幕，一律走 ffmpeg 提取音频 + 转写）
- _get_downloader 逻辑不变（走 SUPPORT_PLATFORM_MAP）

### 4. backend/app/routers/note.py
- 删除 POST /upload 接口、UPLOAD_DIR、UploadFile/File import
- 删除 GET /image_proxy 接口（仅服务于在线平台封面）
- 删除 prefetched_transcript 字段与 _persist_prefetched_transcript（仅浏览器插件使用）
- 删除 video_url_validator / url_parser 的 import 与调用：normalize_url、validate_supported_url、extract_video_id；video_id 改用文件名（去扩展名）
- VideoRequest 增加本地路径存在性校验：os.path.exists 不通过则 400，提示"路径不存在"
- 新增文件夹批量语义：generate_note 中若 video_url 是目录，扫描其中的视频/音频扩展名文件（mp4、mkv、avi、mov、flv、wmv、webm、ts、mp3、m4a、wav、aac、flac），每个文件建一个任务；目录为空则报错。响应统一返回 `{"task_id": 第一个, "task_ids": [...]}`（单文件时 task_ids 只有一个元素，保持向后兼容）

### 5. 新增本地路径选择接口（浏览器拿不到绝对路径，用后端 tkinter 弹系统对话框）
- 新建 backend/app/routers/picker.py（或并入 config.py）：
  - POST /api/pick_file：tkinter.filedialog.askopenfilename，filetypes 限定视频/音频，返回 {"path": ...}
  - POST /api/pick_folder：tkinter.filedialog.askdirectory，返回 {"path": ...}
  - 用一把全局锁串行化对话框调用，root.withdraw() + -topmost 保证弹窗置顶；用户取消返回 path 为空字符串
- 在 app/__init__.py 注册该 router（前缀 /api，与现有 config/note 一致）

### 6. Cookie 与 URL 校验相关删除
- 删除 backend/app/services/cookie_manager.py
- backend/app/routers/config.py：删除 get_downloader_cookie / update_downloader_cookie 两个接口与 CookieConfigManager import
- 删除 backend/app/validators/video_url_validator.py、backend/app/utils/url_parser.py（先 grep 确认无其他引用）
- 代理配置（proxy_config_manager）保留：Whisper 模型下载仍需要

### 7. backend/main.py
- 删除 uploads 目录创建与 /uploads 静态挂载

### 8. requirements.txt
- 仅文本删除 yt-dlp 相关依赖行（不执行任何卸载命令）

### 9. 删除对应测试
- backend/tests/：test_ydl_retry_behavior.py、test_ydl_retry_opts.py、test_youtube_metadata_only.py、test_bilibili_dm_patch.py、test_url_normalize.py、test_video_url_support.py

## 二、前端删除与改造（BillNote_frontend/src/）

### 1. services
- 删除 services/upload.ts、services/downloader.ts
- services/note.ts：generateNote 返回值兼容 task_ids 数组

### 2. constant/note.ts
- videoPlatforms 只保留 local（或直接删除该常量，平台固定为 local）

### 3. NoteForm.tsx（核心改造）
- 删除：uploadFile/handleFileUpload/isUploading/uploadSuccess、拖拽上传区域、withScheme 与 URL 校验、平台下拉框（平台固定 local，payload 仍带 platform: 'local' 兼容后端）
- 新增：路径输入框 + 两个按钮"选择文件""选择文件夹"，分别 POST /api/pick_file、/api/pick_folder，把返回的 path 写入 video_url 字段；用户也可手动粘贴路径
- zod schema：video_url 仅要求非空（不再校验 URL 格式）
- 提交逻辑：响应含 task_ids 时对每个 id 调 addPendingTask；currentTaskId 指向第一个
- 删除"原片跳转"（link）选项在本地模式的意义：noteFormats 中移除 link 项（本地视频没有可跳转的原片链接）

### 4. 封面显示
- VideoBanner.tsx、NoteHistory.tsx：删除 image_proxy 拼接逻辑，cover_url 直接使用（本地封面走 /static）

### 5. 设置页
- 删除 pages/SettingPage/Downloader.tsx、components/Form/DownloaderForm/ 整个目录
- App.tsx：删除 download 相关路由与 lazy import
- pages/SettingPage/Menu.tsx：删除"下载器配置"菜单项

## 三、浏览器插件（BillNote_extension/）

该插件整体围绕在线平台（抓取 B 站字幕、平台 Cookie、在线下载器配置），删除后端相关接口后已无可用功能。计划：整个 BillNote_extension 目录删除（git 可恢复）。若用户希望保留目录不动，批准计划时说明即可，不影响其余改造。

## 四、验证（全部在系统环境，不安装任何依赖）

1. 启动后端：`python main.py`（backend 目录，端口 8484），确认无 import 报错、/api/sys_check 返回 200
2. `pytest backend/tests`（仅跑保留下来的测试，确认全绿）
3. curl 调 /api/generate_note 传一个本地视频文件路径，轮询 /api/task_status/{id} 直到 SUCCESS，确认 note_results 下生成笔记 JSON
4. curl 传一个包含多个视频的文件夹路径，确认返回多个 task_ids 且任务依次完成
5. 传不存在的路径，确认返回 400 与清晰提示
6. 启动前端（3015），验证"选择文件/选择文件夹"弹出系统对话框、路径回填、任务列表轮询与笔记展示正常；确认设置页不再出现下载器配置

## 关键文件清单

| 操作 | 文件 |
|------|------|
| 删除 | backend/app/downloaders/ 在线下载器 8 个文件 + 2 个 helper 目录 |
| 删除 | backend/app/validators/video_url_validator.py、backend/app/utils/url_parser.py、backend/app/services/cookie_manager.py |
| 删除 | backend/tests/ 6 个测试文件 |
| 删除 | 前端 upload.ts、downloader.ts、Downloader 设置页、DownloaderForm 目录、BillNote_extension/ |
| 修改 | backend/app/routers/note.py、config.py、main.py、services/note.py、constant.py、requirements.txt |
| 新增 | backend/app/routers/picker.py（pick_file / pick_folder） |
| 修改 | 前端 NoteForm.tsx、note.ts、constant/note.ts、VideoBanner.tsx、NoteHistory.tsx、App.tsx、Menu.tsx、taskStore |
