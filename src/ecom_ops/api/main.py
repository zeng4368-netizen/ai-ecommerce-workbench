from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from ecom_ops.agents.complaints import ComplaintAgent
from ecom_ops.agents.sales import SalesAgent
from ecom_ops.core.settings import get_settings
from ecom_ops.integrations.tiktok import TikTokAPIError
from ecom_ops.integrations.tiktok_business import TikTokBusinessAPIError
from ecom_ops.services.platform_registry import PlatformRegistry
from ecom_ops.services.tiktok_ads import TikTokAdsService
from ecom_ops.services.tiktok_monitor import TikTokMonitorService
from ecom_ops.video_mixer.ingestion import MixerImporter
from ecom_ops.video_mixer.planner import InsufficientMaterialError
from ecom_ops.video_mixer.repository import MixerRepository
from ecom_ops.video_mixer.workflow import MixerWorkflow


app = FastAPI(title="AI 电商工作台", version="0.3.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8501", "http://localhost:8501"],
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


def _save_upload(file: UploadFile, prefix: str) -> Path:
    settings = get_settings()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = Path(file.filename or f"{prefix}.xlsx").name
    path = settings.raw_dir / f"{prefix}_{stamp}_{filename}"
    with path.open("wb") as target:
        shutil.copyfileobj(file.file, target)
    return path


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/sales/analyze")
def analyze_sales(file: UploadFile = File(...)) -> dict[str, str]:
    input_path = _save_upload(file, "sales")
    result = SalesAgent().run(input_path)
    return {
        "run_id": result.run_id,
        "report_path": str(result.report_path),
        "markdown_path": str(result.markdown_path),
    }


@app.post("/complaints/register")
def register_complaints(file: UploadFile = File(...)) -> dict[str, str]:
    input_path = _save_upload(file, "complaints")
    result = ComplaintAgent().run(input_path)
    return {
        "run_id": result.run_id,
        "report_path": str(result.report_path),
    }


def _tiktok_service() -> TikTokMonitorService:
    return TikTokMonitorService()


@app.get("/tiktok/oauth/start")
def tiktok_oauth_start() -> RedirectResponse:
    try:
        url = _tiktok_service().create_authorization_url()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return RedirectResponse(url)


@app.get("/tiktok/oauth/url")
def tiktok_oauth_url() -> dict[str, str]:
    try:
        return {"authorization_url": _tiktok_service().create_authorization_url()}
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/tiktok/oauth/callback", response_class=HTMLResponse)
def tiktok_oauth_callback(
    code: str = "",
    state: str = "",
    error: str = "",
    error_description: str = "",
) -> HTMLResponse:
    if error:
        raise HTTPException(status_code=400, detail=f"{error}: {error_description}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing OAuth code or state.")
    service = _tiktok_service()
    try:
        open_id = service.complete_authorization(code, state)
        try:
            summary = service.sync(open_id)
            sync_message = f"已同步 {summary.videos_synced} 条公开视频。"
        except Exception as exc:  # Account remains connected; user can retry sync.
            sync_message = f"账号已连接，首次同步暂时失败：{exc}"
    except (ValueError, TikTokAPIError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return HTMLResponse(
        "<h2>TikTok 账号连接成功</h2>"
        f"<p>{sync_message}</p>"
        "<p>可以关闭此页面并返回本地监控看板。</p>"
    )


@app.get("/tiktok/accounts")
def tiktok_accounts() -> list[dict]:
    return _tiktok_service().repository.list_accounts()


@app.post("/tiktok/sync")
def tiktok_sync(open_id: str | None = Query(default=None)) -> dict:
    try:
        summary = _tiktok_service().sync(open_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TikTokAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "run_id": summary.run_id,
        "open_id": summary.open_id,
        "videos_synced": summary.videos_synced,
        "collected_at": summary.collected_at,
    }


@app.get("/tiktok/overview")
def tiktok_overview(open_id: str) -> dict:
    return _tiktok_service().repository.overview(open_id)


@app.get("/tiktok/videos")
def tiktok_videos(open_id: str, limit: int = Query(default=100, ge=1, le=500)) -> list[dict]:
    return _tiktok_service().repository.videos(open_id, limit)


@app.get("/tiktok/timeseries")
def tiktok_timeseries(
    open_id: str, limit: int = Query(default=288, ge=1, le=2000)
) -> list[dict]:
    return _tiktok_service().repository.timeseries(open_id, limit)


def _tiktok_ads_service() -> TikTokAdsService:
    return TikTokAdsService()


@app.post("/tiktok/ads/sync")
def tiktok_ads_sync(days: int = Query(default=30, ge=1, le=90)) -> dict:
    try:
        summary = _tiktok_ads_service().sync(days)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TikTokBusinessAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "run_id": summary.run_id,
        "advertiser_id": summary.advertiser_id,
        "rows_synced": summary.rows_synced,
        "start_date": summary.start_date,
        "end_date": summary.end_date,
    }


@app.get("/tiktok/ads/overview")
def tiktok_ads_overview(days: int = Query(default=30, ge=1, le=90)) -> dict:
    service = _tiktok_ads_service()
    return service.repository.overview(service.settings.tiktok_business_advertiser_id, days)


@app.get("/tiktok/ads/trend")
def tiktok_ads_trend(days: int = Query(default=30, ge=1, le=90)) -> list[dict]:
    service = _tiktok_ads_service()
    return service.repository.trend(service.settings.tiktok_business_advertiser_id, days)


@app.get("/tiktok/ads/campaigns")
def tiktok_ads_campaigns(days: int = Query(default=30, ge=1, le=90)) -> list[dict]:
    service = _tiktok_ads_service()
    return service.repository.campaigns(service.settings.tiktok_business_advertiser_id, days)


@app.get("/integrations")
def integrations(check_health: bool = False) -> list[dict]:
    registry = PlatformRegistry()
    result = []
    for tool in registry.tools():
        status = registry.status(tool) if check_health else None
        result.append(
            {
                "key": tool.key,
                "name": tool.name,
                "role": tool.role,
                "repository": tool.repository,
                "license": tool.license,
                "configured": bool(registry.base_url(tool)),
                "healthy": status.healthy if status else None,
                "message": status.message if status else "health check not requested",
            }
        )
    return result


class MixerProjectRequest(BaseModel):
    product_id: str
    target_duration: float = Field(default=30, ge=20, le=35)
    language: str = "ms"
    audio_mode: str = "voiceover"


class TimelineUpdate(BaseModel):
    timeline: dict
    source: str = "human"


class ReviewRequest(BaseModel):
    decision: str = "approved"
    reason: str = ""


class SegmentUpdateRequest(BaseModel):
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, gt=0)
    stage: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    visual_summary: str | None = None
    transcript: str | None = None
    on_screen_text: list[str] | None = None
    selling_points: list[str] | None = None
    product_tags: list[str] | None = None
    product_tag_names: dict[str, str] | None = None
    quality_issues: list[str] | None = None


class SegmentSplitRequest(BaseModel):
    at_seconds: float = Field(ge=0)


def _mixer_repository() -> MixerRepository:
    return MixerRepository()


def _mixer_workflow() -> MixerWorkflow:
    repository = _mixer_repository()
    return MixerWorkflow(repository)


@app.post("/mixer/imports")
def mixer_import(
    file: UploadFile = File(...),
    ad_file: UploadFile | None = File(default=None),
) -> dict:
    source_path = _save_upload(file, "mixer_videos")
    ad_path = _save_upload(ad_file, "mixer_ads") if ad_file else None
    try:
        return MixerImporter(_mixer_repository()).import_file(
            source_path, ad_source_path=ad_path
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/mixer/imports")
def mixer_imports() -> list[dict]:
    return _mixer_repository().imports()


@app.get("/mixer/products")
def mixer_products(limit: int = Query(default=500, ge=1, le=2000)) -> list[dict]:
    return _mixer_repository().products(limit)


@app.get("/mixer/products/{product_id}/videos")
def mixer_product_videos(
    product_id: str, limit: int = Query(default=30, ge=1, le=100)
) -> list[dict]:
    return _mixer_repository().product_videos(product_id, limit)


@app.get("/mixer/products/{product_id}/segments")
def mixer_product_segments(
    product_id: str,
    stage: str = "",
    tag: str = "",
    duration_min: float = Query(default=0, ge=0, le=600),
    duration_max: float = Query(default=60, ge=0.1, le=600),
    confidence_min: float = Query(default=0, ge=0, le=1),
    human_verified: bool | None = None,
    usage: str = Query(default="all", pattern="^(all|used|unused)$"),
    query: str = "",
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    if duration_max < duration_min:
        raise HTTPException(status_code=400, detail="最大时长不能小于最小时长。")
    return _mixer_repository().search_segments(
        product_id,
        stage=stage,
        tag=tag,
        duration_min=duration_min,
        duration_max=duration_max,
        confidence_min=confidence_min,
        human_verified=human_verified,
        usage=usage,
        query=query,
        limit=limit,
        offset=offset,
    )


@app.get("/mixer/products/{product_id}/tags")
def mixer_product_tags(product_id: str) -> list[dict]:
    return _mixer_repository().product_tags(product_id)


@app.get("/mixer/segments/{segment_id}")
def mixer_segment(segment_id: str) -> dict:
    segment = _mixer_repository().segment(segment_id)
    if not segment:
        raise HTTPException(status_code=404, detail="片段不存在。")
    return segment


@app.patch("/mixer/segments/{segment_id}")
def mixer_update_segment(segment_id: str, request: SegmentUpdateRequest) -> dict:
    try:
        changes = (
            request.model_dump(exclude_none=True)
            if hasattr(request, "model_dump")
            else request.dict(exclude_none=True)
        )
        return _mixer_repository().update_segment(
            segment_id, changes, source="human"
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="片段不存在。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/mixer/segments/{segment_id}/split")
def mixer_split_segment(segment_id: str, request: SegmentSplitRequest) -> list[dict]:
    try:
        return _mixer_repository().split_segment(segment_id, request.at_seconds)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="片段不存在。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/mixer/segments/{segment_id}/usage")
def mixer_segment_usage(segment_id: str) -> list[dict]:
    if not _mixer_repository().segment(segment_id):
        raise HTTPException(status_code=404, detail="片段不存在。")
    return _mixer_repository().segment_usage(segment_id)


@app.get("/mixer/assets/{asset_id}/media")
def mixer_asset_media(asset_id: str) -> FileResponse:
    asset = _mixer_repository().asset(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="素材不存在。")
    path = Path(asset["path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="本地素材文件不存在。")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@app.post("/mixer/products/{product_id}/analyze")
def mixer_analyze(product_id: str, confirmed: bool = False) -> dict:
    try:
        return _mixer_workflow().queue_analysis(product_id, confirmed=confirmed)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Product not found.") from exc
    except InsufficientMaterialError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/mixer/taxonomies/{taxonomy_id}/approve")
def mixer_approve_taxonomy(taxonomy_id: str) -> dict[str, str]:
    try:
        _mixer_repository().approve_taxonomy(taxonomy_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Taxonomy not found.") from exc
    return {"id": taxonomy_id, "status": "approved"}


@app.post("/mixer/projects")
def mixer_create_projects(request: MixerProjectRequest) -> list[dict]:
    try:
        return _mixer_workflow().create_projects(
            request.product_id,
            target_duration=request.target_duration,
            language=request.language,
            audio_mode=request.audio_mode,
        )
    except (ValueError, InsufficientMaterialError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/mixer/projects")
def mixer_projects() -> list[dict]:
    return _mixer_repository().projects()


@app.get("/mixer/projects/{project_id}/timeline")
def mixer_timeline(project_id: str) -> dict:
    timeline = _mixer_repository().latest_timeline(project_id)
    if not timeline:
        raise HTTPException(status_code=404, detail="Timeline not found.")
    return timeline


@app.patch("/mixer/projects/{project_id}/timeline")
def mixer_update_timeline(project_id: str, request: TimelineUpdate) -> dict:
    repository = _mixer_repository()
    project = repository.project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    clips = request.timeline.get("clips", [])
    if any(str(clip.get("product_id")) != project["product_id"] for clip in clips):
        raise HTTPException(status_code=400, detail="Cross-product timeline is forbidden.")
    return repository.save_timeline(project_id, request.timeline, source=request.source)


@app.post("/mixer/projects/{project_id}/render")
def mixer_render(project_id: str) -> dict:
    repository = _mixer_repository()
    if not repository.project(project_id):
        raise HTTPException(status_code=404, detail="Project not found.")
    return repository.create_job("render_project", {"project_id": project_id})


@app.get("/mixer/jobs")
def mixer_jobs(limit: int = Query(default=100, ge=1, le=500)) -> list[dict]:
    return _mixer_repository().jobs(limit)


@app.post("/mixer/jobs/{job_id}/confirm")
def mixer_confirm_job(job_id: str) -> dict:
    repository = _mixer_repository()
    try:
        repository.confirm_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return repository.job(job_id) or {}


@app.post("/mixer/jobs/run-next")
def mixer_run_next_job() -> dict:
    try:
        return _mixer_workflow().run_next_job() or {"status": "idle"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/mixer/renders/{render_id}/approve")
def mixer_approve_render(render_id: str, request: ReviewRequest) -> dict:
    repository = _mixer_repository()
    render = repository.render(render_id)
    if not render:
        raise HTTPException(status_code=404, detail="Render not found.")
    try:
        return repository.review(
            render["project_id"],
            request.decision,
            reason=request.reason,
            render_path=render.get("voiceover_path") or render.get("original_audio_path") or "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
