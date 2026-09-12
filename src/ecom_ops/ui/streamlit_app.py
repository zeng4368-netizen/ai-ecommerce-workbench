from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
import streamlit as st

from ecom_ops.agents.complaints import ComplaintAgent
from ecom_ops.agents.sales import SalesAgent
from ecom_ops.core.database import connect, init_db
from ecom_ops.core.settings import get_settings
from ecom_ops.services.platform_registry import PlatformRegistry
from ecom_ops.services.tiktok_ads import TikTokAdsService
from ecom_ops.services.tiktok_monitor import TikTokMonitorService
from ecom_ops.video_mixer.ingestion import MixerImporter
from ecom_ops.video_mixer.domain import SALES_STAGE_CN
from ecom_ops.video_mixer.repository import MixerRepository
from ecom_ops.video_mixer.workflow import MixerWorkflow
from ecom_ops.ui.video_timeline import video_timeline
from ecom_ops.ui.theme import WORKBENCH_CSS


settings = get_settings()
init_db(settings.sqlite_path)

st.set_page_config(
    page_title="AI 电商工作台",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="auto",
)
st.markdown(WORKBENCH_CSS, unsafe_allow_html=True)


NAV_ITEMS = [
    "总览",
    "销售分析智能体",
    "投诉登记智能体",
    "TikTok 自然流量",
    "TikTok 广告投放",
    "视频混剪",
    "成熟平台中心",
    "系统设置",
]


def _sidebar() -> str:
    st.sidebar.markdown(
        """
        <div class="wb-brand">
          <div class="wb-brand-title">◈ AI 电商工作台</div>
          <div class="wb-brand-sub">本地电商智能运营</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    page = st.sidebar.radio("工作区", NAV_ITEMS, label_visibility="collapsed")
    st.sidebar.divider()
    st.sidebar.caption("运行方式")
    st.sidebar.markdown("**本地优先 · 人工确认 · 全程留痕**")
    if settings.automation_enabled:
        st.sidebar.warning("浏览器自动化已启用；高风险动作仍需确认。")
    else:
        st.sidebar.info("自动化写操作已关闭。")
    return page


def _hero(title: str, copy: str, eyebrow: str = "AI 电商运营工作台") -> None:
    st.markdown(
        f"""
        <section class="wb-hero">
          <div class="wb-eyebrow">{eyebrow}</div>
          <h1>{title}</h1>
          <p>{copy}</p>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _card(title: str, copy: str, badge: str, badge_class: str = "wb-off") -> None:
    st.markdown(
        f"""
        <div class="wb-card">
          <span class="wb-badge {badge_class}">{badge}</span>
          <div class="wb-card-title">{title}</div>
          <div class="wb-card-copy">{copy}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _safe_count(query: str, params: tuple[Any, ...] = ()) -> int:
    with connect(settings.sqlite_path) as conn:
        row = conn.execute(query, params).fetchone()
    return int(row[0] if row else 0)


def _save_upload(uploaded: Any, prefix: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = Path(uploaded.name).name
    path = settings.raw_dir / f"{prefix}_{stamp}_{filename}"
    path.write_bytes(uploaded.getbuffer())
    return path


def _render_home() -> None:
    _hero(
        "今天先看哪里？",
        "把销售、售后、TikTok 自然流量和广告投放放在一张运营桌面上。AI 只给出可追溯建议，所有真实业务动作由你确认。",
    )
    organic_accounts = _safe_count("SELECT COUNT(*) FROM tiktok_accounts WHERE status = 'active'")
    reports = _safe_count("SELECT COUNT(*) FROM runs WHERE status = 'completed'")
    pending_reviews = _safe_count(
        "SELECT COUNT(*) FROM decisions WHERE risk_level = 'High' OR priority_level = 'P1'"
    )
    tools = PlatformRegistry(settings).tools()
    configured_tools = sum(bool(PlatformRegistry(settings).base_url(tool)) for tool in tools)

    columns = st.columns(4)
    columns[0].metric("已连接 TikTok 账号", organic_accounts)
    columns[1].metric("已生成分析报告", reports)
    columns[2].metric("高优先级建议", pending_reviews)
    columns[3].metric("成熟平台地址", f"{configured_tools}/{len(tools)}")

    st.subheader("数据与能力状态")
    columns = st.columns(4)
    with columns[0]:
        _card(
            "TikTok 自然流量",
            "公开视频播放、点赞、评论、分享和历史增量。",
            "已连接" if organic_accounts else "待授权",
            "wb-ok" if organic_accounts else "wb-warn",
        )
    with columns[1]:
        _card(
            "TikTok 广告投放",
            "消耗、曝光、点击、转化、购买和 ROAS。",
            "已配置" if settings.tiktok_ads_configured else "待配置",
            "wb-ok" if settings.tiktok_ads_configured else "wb-warn",
        )
    with columns[2]:
        _card("销售分析智能体", "识别销量涨跌、库存风险、券与达人素材需求。", "可用", "wb-ok")
    with columns[3]:
        _card("投诉登记智能体", "投诉分类、货况判断、风险清单与人工复核队列。", "可用", "wb-ok")

    st.subheader("最近 AI 决策记录")
    with connect(settings.sqlite_path) as conn:
        rows = conn.execute(
            """
            SELECT subject_key, decision, reason, risk_level, priority_level, created_at
            FROM decisions ORDER BY created_at DESC LIMIT 8
            """
        ).fetchall()
    if rows:
        st.dataframe(pd.DataFrame([dict(row) for row in rows]), use_container_width=True, hide_index=True)
    else:
        st.info("运行销售分析或投诉登记后，这里会显示可追溯的 AI 建议。")


def _render_sales() -> None:
    _hero("销售分析智能体", "上传销售 Excel，生成日销报告、优惠券候选、达人素材需求和高风险商品清单。")
    uploaded = st.file_uploader("上传销售数据 Excel", type=["xlsx", "xls"], key="sales_upload")
    st.markdown('<div class="wb-risk">只生成建议与报告，不会自动申请优惠券、调价或发布商品。</div>', unsafe_allow_html=True)
    if uploaded and st.button("开始分析", type="primary"):
        try:
            with st.spinner("正在分析销售、流量与库存风险..."):
                result = SalesAgent(settings).run(_save_upload(uploaded, "sales"))
            st.success(f"报告已生成：{result.report_path.name}")
            left, right = st.columns(2)
            with left:
                st.download_button(
                    "下载 Markdown 日报",
                    result.markdown_path.read_text(encoding="utf-8"),
                    file_name=result.markdown_path.name,
                )
            with right:
                st.caption(f"运行 ID：{result.run_id}")
            tabs = st.tabs(["高风险商品", "优惠券候选", "达人素材需求", "日销明细"])
            tabs[0].dataframe(result.analysis.high_risk_product_list, use_container_width=True)
            tabs[1].dataframe(result.analysis.coupon_application_list, use_container_width=True)
            tabs[2].dataframe(result.analysis.creator_material_demand_list, use_container_width=True)
            tabs[3].dataframe(result.analysis.daily_sales_report, use_container_width=True)
        except Exception as exc:
            st.error(f"分析失败：{exc}")


def _render_complaints() -> None:
    _hero("投诉登记智能体", "上传售后或投诉 Excel，自动分类问题、判断货况并整理人工复核清单。")
    uploaded = st.file_uploader("上传投诉数据 Excel", type=["xlsx", "xls"], key="complaint_upload")
    st.markdown('<div class="wb-risk">不会自动退款、补发或回复客户；所有补偿与责任判定必须人工确认。</div>', unsafe_allow_html=True)
    if uploaded and st.button("生成投诉登记", type="primary"):
        try:
            with st.spinner("正在分类投诉并生成可追溯建议..."):
                result = ComplaintAgent(settings).run(_save_upload(uploaded, "complaints"))
            st.success(f"登记表已生成：{result.report_path.name}")
            tabs = st.tabs(["类别汇总", "人工复核", "缺陷商品", "良品/疑似良品", "全部登记"])
            tabs[0].dataframe(result.analysis.category_summary, use_container_width=True)
            tabs[1].dataframe(result.analysis.human_review_list, use_container_width=True)
            tabs[2].dataframe(result.analysis.defective_products, use_container_width=True)
            tabs[3].dataframe(result.analysis.good_or_suspected_good_products, use_container_width=True)
            tabs[4].dataframe(result.analysis.complaint_registration, use_container_width=True)
        except Exception as exc:
            st.error(f"处理失败：{exc}")


def _render_tiktok_organic() -> None:
    _hero("TikTok 自然流量", "通过官方 Login Kit 与 Display API 读取账号公开视频指标，并把每次同步保存为本地历史快照。")
    service = TikTokMonitorService(settings)
    if not settings.tiktok_configured:
        st.warning("尚未配置 TikTok 开发者应用。")
        st.code(
            "TIKTOK_CLIENT_KEY=你的ClientKey\n"
            "TIKTOK_CLIENT_SECRET=你的ClientSecret\n"
            "TIKTOK_REDIRECT_URI=http://127.0.0.1:8000/tiktok/oauth/callback",
            language="text",
        )
        return
    if st.button("生成官方授权链接"):
        try:
            st.session_state["tiktok_auth_url"] = service.create_authorization_url()
        except Exception as exc:
            st.error(f"无法生成授权链接：{exc}")
    if st.session_state.get("tiktok_auth_url"):
        st.link_button("连接 TikTok 账号", st.session_state["tiktok_auth_url"], type="primary")
    accounts = service.repository.list_accounts()
    if not accounts:
        st.info("完成 TikTok 授权后刷新本页。OAuth 回调 API 需要同时运行。")
        return
    labels = {row["open_id"]: row["display_name"] or f"TikTok {row['open_id'][:8]}" for row in accounts}
    top_left, top_right = st.columns([3, 1])
    with top_left:
        open_id = st.selectbox("监控账号", list(labels), format_func=lambda value: labels[value])
    with top_right:
        st.write("")
        if st.button("立即同步", type="primary", use_container_width=True):
            try:
                with st.spinner("正在读取官方公开视频指标..."):
                    summary = service.sync(open_id)
                st.success(f"已同步 {summary.videos_synced} 条视频")
            except Exception as exc:
                st.error(f"同步失败：{exc}")
    overview = service.repository.overview(open_id)
    specs = [
        ("总播放量", "view_count", "view_count_delta"),
        ("总点赞量", "like_count", "like_count_delta"),
        ("总评论量", "comment_count", "comment_count_delta"),
        ("总分享量", "share_count", "share_count_delta"),
        ("视频数", "video_count", None),
    ]
    for column, (label, value_key, delta_key) in zip(st.columns(5), specs):
        column.metric(label, f"{overview.get(value_key, 0):,}", overview.get(delta_key, 0) if delta_key else None)
    st.caption(f"最近同步：{overview.get('last_synced_at') or '尚未同步'}（UTC）")
    series = service.repository.timeseries(open_id)
    if series:
        chart = pd.DataFrame(series)
        chart["collected_at"] = pd.to_datetime(chart["collected_at"])
        st.subheader("累计指标趋势")
        st.line_chart(chart.set_index("collected_at")[["view_count", "like_count", "comment_count", "share_count"]])
    videos = service.repository.videos(open_id)
    st.subheader("视频表现")
    if videos:
        st.dataframe(pd.DataFrame(videos), use_container_width=True, hide_index=True)
    else:
        st.info("暂无视频快照，请执行一次同步。")


def _render_tiktok_ads() -> None:
    _hero("TikTok 广告投放", "通过 TikTok API for Business 读取只读报表，汇总花费、曝光、点击、转化、购买和 ROAS。")
    st.markdown('<div class="wb-risk">本模块只读取报表，不创建、暂停或修改 Campaign、Ad Group 与广告。</div>', unsafe_allow_html=True)
    if not settings.tiktok_ads_configured:
        st.warning("尚未配置 TikTok Business 授权信息。")
        st.code(
            "TIKTOK_BUSINESS_ACCESS_TOKEN=你的只读AccessToken\n"
            "TIKTOK_BUSINESS_ADVERTISER_ID=你的AdvertiserID\n"
            "TIKTOK_ADS_REPORT_DAYS=30",
            language="text",
        )
        st.caption("在 TikTok Business Center 创建开发者应用并完成广告账户授权。凭据仅保存在本地 .env。")
        return
    service = TikTokAdsService(settings)
    default_days = min([7, 14, 30, 60, 90], key=lambda value: abs(value - settings.tiktok_ads_report_days))
    selected_days = st.select_slider(
        "报表窗口（天）", options=[7, 14, 30, 60, 90], value=default_days
    )
    days = int(selected_days or settings.tiktok_ads_report_days)
    if st.button("同步广告报表", type="primary"):
        try:
            with st.spinner("正在读取 TikTok Business 报表..."):
                summary = service.sync(days)
            st.success(f"同步完成：{summary.rows_synced} 行，{summary.start_date} 至 {summary.end_date}")
        except Exception as exc:
            st.error(f"广告报表同步失败：{exc}")
    advertiser_id = settings.tiktok_business_advertiser_id
    overview = service.repository.overview(advertiser_id, days)
    metrics = [
        ("广告花费", f"{overview.get('spend', 0):,.2f}"),
        ("曝光量", f"{overview.get('impressions', 0):,.0f}"),
        ("点击量", f"{overview.get('clicks', 0):,.0f}"),
        ("CTR", f"{overview.get('ctr', 0):.2f}%"),
        ("CPC", f"{overview.get('cpc', 0):.2f}"),
        ("ROAS", f"{overview.get('purchase_roas', 0):.2f}"),
    ]
    for column, (label, value) in zip(st.columns(6), metrics):
        column.metric(label, value)
    st.caption(f"广告账户：{advertiser_id} · 最近同步：{overview.get('last_synced_at') or '尚未同步'}")
    trend = service.repository.trend(advertiser_id, days)
    if trend:
        frame = pd.DataFrame(trend)
        frame["stat_date"] = pd.to_datetime(frame["stat_date"])
        tabs = st.tabs(["花费与转化", "曝光与点击"])
        tabs[0].line_chart(frame.set_index("stat_date")[["spend", "conversions", "purchases"]])
        tabs[1].line_chart(frame.set_index("stat_date")[["impressions", "clicks"]])
    campaigns = service.repository.campaigns(advertiser_id, days)
    st.subheader("Campaign 表现")
    if campaigns:
        st.dataframe(pd.DataFrame(campaigns), use_container_width=True, hide_index=True)
    else:
        st.info("暂无广告报表，请配置权限后执行同步。")


def _render_integrations() -> None:
    _hero("成熟平台中心", "Postiz、BrightBean 与 Multica 保持完整、独立运行；工作台通过服务地址检测状态并提供统一入口。", "OPEN-SOURCE ECOSYSTEM")
    registry = PlatformRegistry(settings)
    tools = registry.tools()
    if st.button("检测全部服务"):
        with st.spinner("正在检测本地服务..."):
            st.session_state["platform_statuses"] = {status.key: status for _, status in registry.statuses()}
    statuses = st.session_state.get("platform_statuses", {})
    for tool in tools:
        status = statuses.get(tool.key)
        configured = bool(registry.base_url(tool))
        left, right = st.columns([4, 1])
        with left:
            if status:
                badge = "在线" if status.healthy else "无法连接"
                badge_class = "wb-ok" if status.healthy else "wb-warn"
                status_copy = status.message
            else:
                badge = "已配置" if configured else "待配置"
                badge_class = "wb-off" if configured else "wb-warn"
                status_copy = "点击上方按钮执行健康检查" if configured else "请在 .env 中配置服务地址"
            _card(
                f"{tool.name} · {tool.role}",
                f"{tool.description}<br><br><b>能力：</b>{' · '.join(tool.capabilities)}<br>"
                f"<b>许可：</b>{tool.license} · <b>状态：</b>{status_copy}<br>{tool.safety_note}",
                badge,
                badge_class,
            )
        with right:
            st.write("")
            if configured:
                st.link_button("打开服务", registry.base_url(tool), use_container_width=True)
            st.link_button("查看源码", tool.repository, use_container_width=True)
        st.write("")
    st.info("当前机器未检测到 Docker。Multica CLI 可以连接云端；完整自托管服务源码保留在 external/，安装 Docker Desktop 后可启动官方 Compose。")


def _render_settings() -> None:
    _hero("系统设置", "集中检查本地目录、凭据状态、只读安全边界和外部服务地址。", "LOCAL CONTROL PLANE")
    checks = pd.DataFrame(
        [
            {"模块": "TikTok 自然流量", "状态": "已配置" if settings.tiktok_configured else "待配置", "凭据显示": "否"},
            {"模块": "TikTok 广告报表", "状态": "已配置" if settings.tiktok_ads_configured else "待配置", "凭据显示": "否"},
            {"模块": "自动化写操作", "状态": "已关闭" if not settings.automation_enabled else "已启用", "凭据显示": "不适用"},
            {"模块": "人工确认", "状态": "强制" if settings.require_human_confirmation else "未强制", "凭据显示": "不适用"},
        ]
    )
    st.dataframe(checks, use_container_width=True, hide_index=True)
    st.subheader("本地目录")
    st.code(
        f"原始数据: {settings.raw_dir}\n"
        f"处理数据: {settings.processed_dir}\n"
        f"输出报告: {settings.output_dir}\n"
        f"截图: {settings.screenshot_dir}\n"
        f"日志: {settings.log_dir}\n"
        f"SQLite: {settings.sqlite_path}",
        language="text",
    )
    st.caption("工作台不会在界面中显示 Client Secret、Access Token、Cookie 或 Session Token。")


PROJECT_STATUS_CN = {
    "draft": "草稿",
    "rendering": "正在渲染",
    "review": "待审核",
    "approved": "已批准",
    "rejected": "已驳回",
    "render_failed": "渲染失败",
}

MIXER_FIELD_CN = {
    "id": "记录编号",
    "product_id": "商品 ID",
    "product_name": "商品名称",
    "material_count": "素材数量",
    "taxonomy_status": "标签模板状态",
    "video_id": "视频编号",
    "platform_video_id": "平台视频 ID",
    "url": "视频链接",
    "title": "视频标题",
    "creator_name": "创作者",
    "published_at": "发布时间",
    "authorization_status": "授权状态",
    "latest_score": "素材评分",
    "latest_tier": "素材等级",
    "low_sample": "低样本",
    "source_path": "视频表路径",
    "ad_source_path": "广告表路径",
    "status": "状态",
    "row_count": "数据行数",
    "product_count": "商品数量",
    "error_message": "错误信息",
    "created_at": "创建时间",
    "completed_at": "完成时间",
    "updated_at": "更新时间",
    "job_type": "任务类型",
    "payload": "任务参数",
    "result": "执行结果",
    "requires_confirmation": "需要人工确认",
    "lease_until": "任务租约到期",
    "heartbeat_at": "任务心跳时间",
    "attempts": "已尝试次数",
    "max_attempts": "最大尝试次数",
    "estimated_cost": "预计成本",
    "actual_cost": "实际成本",
}

STATUS_CN = {
    "queued": "排队中",
    "running": "执行中",
    "completed": "已完成",
    "failed": "失败",
    "paused": "已暂停",
    "awaiting_confirmation": "等待人工确认",
    "approved": "已批准",
    "pending": "待确认",
    "missing": "未生成",
    "authorized": "已授权",
}

JOB_TYPE_CN = {
    "analyze_product": "分析商品视频",
    "render_project": "渲染混剪视频",
    "test": "测试任务",
}


def _mixer_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    if "status" in frame.columns:
        frame["status"] = frame["status"].map(lambda value: STATUS_CN.get(value, value))
    if "taxonomy_status" in frame.columns:
        frame["taxonomy_status"] = frame["taxonomy_status"].map(
            lambda value: STATUS_CN.get(value, value)
        )
    if "authorization_status" in frame.columns:
        frame["authorization_status"] = frame["authorization_status"].map(
            lambda value: STATUS_CN.get(value, value)
        )
    if "low_sample" in frame.columns:
        frame["low_sample"] = frame["low_sample"].map(lambda value: "是" if value else "否")
    if "requires_confirmation" in frame.columns:
        frame["requires_confirmation"] = frame["requires_confirmation"].map(
            lambda value: "是" if value else "否"
        )
    if "job_type" in frame.columns:
        frame["job_type"] = frame["job_type"].map(lambda value: JOB_TYPE_CN.get(value, value))
    return frame.rename(columns=MIXER_FIELD_CN)


def _segment_to_clip(segment: dict[str, Any]) -> dict[str, Any]:
    analysis = segment.get("analysis", {})
    return {
        "clip_id": uuid4().hex,
        "segment_id": segment["id"],
        "asset_id": segment["asset_id"],
        "product_id": segment["product_id"],
        "video_id": segment["video_id"],
        "source_path": segment["source_path"],
        "source_start": float(segment["start_seconds"]),
        "source_end": float(segment["end_seconds"]),
        "timeline_start": 0.0,
        "timeline_end": float(segment["duration_seconds"]),
        "stage": segment["stage"],
        "stage_cn": segment["stage_cn"],
        "label": analysis.get("visual_summary") or segment["stage_cn"],
        "confidence": float(segment["confidence"]),
        "preview_url": segment["preview_url"],
    }


def _render_segment_library(repository: MixerRepository, product_id: str) -> None:
    st.subheader("可复用片段库")
    st.caption("片段只保存原视频时间引用，不复制视频文件；人工修改会生成新版本。")
    all_tags = repository.product_tags(product_id)
    tag_names = [row["name_cn"] for row in all_tags if row["category"] == "商品标签"]
    f1, f2, f3, f4 = st.columns([1.4, 1, 1.4, 1])
    query = f1.text_input("搜索字幕、画面摘要或卖点", key="segment_query")
    stage = f2.selectbox(
        "销售阶段",
        [""] + list(SALES_STAGE_CN),
        format_func=lambda value: "全部阶段" if not value else SALES_STAGE_CN[value],
        key="segment_stage_filter",
    )
    duration_range = f3.slider(
        "片段时长（秒）", 0.1, 20.0, (0.1, 8.0), 0.1, key="segment_duration_filter"
    )
    confidence = f4.slider(
        "最低置信度", 0.0, 1.0, 0.5, 0.05, key="segment_confidence_filter"
    )
    f5, f6, f7 = st.columns(3)
    tag = f5.selectbox("商品标签", [""] + tag_names, format_func=lambda x: x or "全部标签")
    verification = f6.selectbox(
        "人工确认",
        ["全部", "人工已确认", "待人工确认"],
        key="segment_verified_filter",
    )
    usage = f7.selectbox(
        "使用情况",
        ["all", "used", "unused"],
        format_func=lambda value: {"all": "全部", "used": "已使用", "unused": "未使用"}[value],
    )
    verified_value = None
    if verification == "人工已确认":
        verified_value = True
    elif verification == "待人工确认":
        verified_value = False
    segments = repository.search_segments(
        product_id,
        stage=stage,
        tag=tag,
        duration_min=duration_range[0],
        duration_max=duration_range[1],
        confidence_min=confidence,
        human_verified=verified_value,
        usage=usage,
        query=query,
        limit=300,
    )
    if not segments:
        st.info("当前筛选条件下没有片段。完成视频分析后，片段会自动进入这里。")
        return
    table = pd.DataFrame(
        [
            {
                "片段编号": row["id"][:10],
                "销售阶段": row["stage_cn"],
                "片段时长（秒）": row["duration_seconds"],
                "开始时间（秒）": row["start_seconds"],
                "结束时间（秒）": row["end_seconds"],
                "商品标签": "、".join(row["tags"]),
                "分析置信度": row["confidence"],
                "人工确认": row["verified_cn"],
                "使用次数": row["usage_count"],
                "素材等级": row["video_tier"],
            }
            for row in segments
        ]
    )
    st.dataframe(table, use_container_width=True, hide_index=True, height=330)
    labels = {
        row["id"]: (
            f"{row['stage_cn']} · {row['start_seconds']:.2f}–{row['end_seconds']:.2f} 秒 · "
            f"{row['verified_cn']} · {row['id'][:8]}"
        )
        for row in segments
    }
    selected_id = st.selectbox(
        "选择要预览或调整的片段",
        list(labels),
        format_func=lambda value: labels[value],
        key="segment_selected_id",
    )
    selected = next(row for row in segments if row["id"] == selected_id)
    analysis = selected.get("analysis", {})
    preview, editor = st.columns([1, 1.25])
    with preview:
        st.video(selected["source_path"], start_time=int(selected["start_seconds"]))
        st.caption(
            f"原视频位置：{selected['start_seconds']:.3f}–{selected['end_seconds']:.3f} 秒 · "
            f"当前版本 v{selected.get('active_version') or 1}"
        )
    with editor:
        e1, e2 = st.columns(2)
        new_start = e1.number_input(
            "入点（秒）",
            min_value=0.0,
            max_value=float(selected["asset_duration"] or selected["end_seconds"]),
            value=float(selected["start_seconds"]),
            step=0.04,
            format="%.3f",
        )
        new_end = e2.number_input(
            "出点（秒）",
            min_value=0.1,
            max_value=float(selected["asset_duration"] or selected["end_seconds"]),
            value=float(selected["end_seconds"]),
            step=0.04,
            format="%.3f",
        )
        new_stage = st.selectbox(
            "销售阶段标签",
            list(SALES_STAGE_CN),
            index=list(SALES_STAGE_CN).index(selected["stage"]),
            format_func=lambda value: SALES_STAGE_CN[value],
        )
        new_summary = st.text_area(
            "片段内容摘要", value=str(analysis.get("visual_summary", "")), height=90
        )
        new_tags = st.text_input("商品专属标签（用逗号分隔）", value="，".join(selected["tags"]))
        save_col, split_col = st.columns(2)
        if save_col.button("保存为人工确认版本", type="primary", use_container_width=True):
            tags = [item.strip() for item in new_tags.replace(",", "，").split("，") if item.strip()]
            try:
                repository.update_segment(
                    selected_id,
                    {
                        "start_seconds": new_start,
                        "end_seconds": new_end,
                        "stage": new_stage,
                        "visual_summary": new_summary,
                        "product_tags": tags,
                        "product_tag_names": {item: item for item in tags},
                    },
                    source="human",
                )
                st.success("已保存新版本，后续混剪会优先使用人工确认边界。")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        split_at = st.number_input(
            "分割位置（原视频秒数）",
            min_value=float(selected["start_seconds"]),
            max_value=float(selected["end_seconds"]),
            value=float((selected["start_seconds"] + selected["end_seconds"]) / 2),
            step=0.04,
            format="%.3f",
        )
        if split_col.button("在指定位置分割", use_container_width=True):
            try:
                repository.split_segment(selected_id, split_at)
                st.success("已生成两个可独立使用的子片段，原片段已保留为历史版本。")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    st.divider()
    selected_for_project = st.multiselect(
        "选择片段并新建手动混剪（选择顺序就是初始拼接顺序）",
        list(labels),
        format_func=lambda value: labels[value],
        key="manual_mix_segments",
    )
    if st.button(
        "用所选片段新建手动混剪",
        disabled=not selected_for_project,
        type="primary",
    ):
        by_id = {row["id"]: row for row in segments}
        clips = [_segment_to_clip(by_id[item]) for item in selected_for_project]
        project = repository.create_project(
            product_id,
            target_duration=max(20, min(35, sum(c["source_end"] - c["source_start"] for c in clips))),
            language="ms",
            audio_mode="original",
        )
        saved = repository.save_timeline(
            project["id"],
            {
                "product_id": product_id,
                "aspect_ratio": "9:16",
                "language": "ms",
                "audio_mode": "original",
                "clips": clips,
                "script": "",
                "subtitles": [],
                "warnings": [],
            },
            source="human",
        )
        st.success(f"已新建手动混剪，时间线版本 v{saved['version']}。")


def _render_video_mixer() -> None:
    _hero(
        "视频混剪智能体",
        "按商品筛选优质素材，理解脚本与镜头，生成可人工调整的马来语混剪候选。",
        "AI 混剪工作台",
    )
    st.markdown(
        '<div class="wb-risk">仅处理已授权素材；不会绕过登录验证、自动发布或自动删除素材。所有成片必须人工审核。</div>',
        unsafe_allow_html=True,
    )
    repository = MixerRepository(settings.sqlite_path)
    workflow = MixerWorkflow(repository, settings)
    tabs = st.tabs(
        ["数据导入", "商品与素材", "片段库", "分析任务", "模板确认", "时间线编辑", "成片审核"]
    )

    with tabs[0]:
        left, right = st.columns(2)
        uploaded = left.file_uploader(
            "视频表现表", type=["xlsx", "xls", "csv"], key="mixer_video_import"
        )
        ad_uploaded = right.file_uploader(
            "广告表现表", type=["xlsx", "xls", "csv"], key="mixer_ad_import"
        )
        if st.button("导入指标快照", type="primary", disabled=uploaded is None):
            try:
                with st.spinner("正在按商品评分并写入本地快照..."):
                    result = MixerImporter(repository).import_file(
                        _save_upload(uploaded, "mixer_videos"),
                        ad_source_path=(
                            _save_upload(ad_uploaded, "mixer_ads") if ad_uploaded else None
                        ),
                    )
                st.success(f"已导入 {result['rows']:,} 条视频，覆盖 {result['products']:,} 个商品")
            except Exception as exc:
                st.error(f"导入失败：{exc}")
        imports = repository.imports()
        if imports:
            st.dataframe(_mixer_dataframe(imports), use_container_width=True, hide_index=True)

    products = repository.products()
    selected_product = None
    labels: dict[str, str] = {}
    if products:
        labels = {
            row["product_id"]: (
                f"{row['product_name'] or row['product_id']} · {row['material_count']} 条"
            )
            for row in products
        }
        selected_product = st.selectbox(
            "当前商品",
            list(labels),
            format_func=lambda value: labels[value],
            key="mixer_selected_product",
        )

    with tabs[1]:
        if not products:
            st.info("先导入视频表现表。")
        else:
            st.dataframe(_mixer_dataframe(products), use_container_width=True, hide_index=True)
            videos = repository.product_videos(str(selected_product), 30)
            st.caption("仅展示当前商品 Top 30；下载和分析不会跨商品。")
            st.dataframe(_mixer_dataframe(videos), use_container_width=True, hide_index=True)

    with tabs[2]:
        if selected_product:
            _render_segment_library(repository, str(selected_product))
        else:
            st.info("请先导入视频数据并选择商品。")

    with tabs[3]:
        if selected_product:
            estimate = workflow.estimate_analysis_cost(str(selected_product))
            c1, c2, c3 = st.columns(3)
            c1.metric("候选下载", "Top 30")
            c2.metric("深度分析", f"{estimate['videos']} 条")
            c3.metric("预计 API 成本", f"USD {estimate['estimated_cost_usd']:.2f}")
            if st.button("加入分析队列", type="primary"):
                try:
                    job = workflow.queue_analysis(str(selected_product))
                    st.success(f"任务已创建：{job['id'][:10]} · {job['status']}")
                except Exception as exc:
                    st.error(str(exc))
        jobs = repository.jobs()
        if jobs:
            st.dataframe(_mixer_dataframe(jobs), use_container_width=True, hide_index=True)
            waiting = [job for job in jobs if job["status"] == "awaiting_confirmation"]
            if waiting:
                waiting_id = st.selectbox(
                    "超预算待确认任务",
                    [job["id"] for job in waiting],
                    format_func=lambda value: value[:10],
                )
                if st.button("确认预算并放行"):
                    repository.confirm_job(waiting_id)
                    st.success("任务已放入执行队列。")
        if st.button("运行下一个本地任务"):
            try:
                with st.spinner("正在执行任务，登录或验证码出现时会自动暂停..."):
                    result = workflow.run_next_job()
                st.success("任务完成" if result else "当前没有待处理任务")
                if result:
                    st.json(result)
            except Exception as exc:
                st.error(f"任务暂停或失败：{exc}")

    with tabs[4]:
        if selected_product:
            taxonomy = repository.latest_taxonomy(str(selected_product))
            if not taxonomy:
                st.info("完成首次视频分析后，系统会生成待确认的商品专属标签模板。")
            else:
                definition = taxonomy["definition"]
                stage_order = definition.get("stage_order", [])
                if stage_order:
                    st.dataframe(
                        pd.DataFrame(
                            [
                                {"顺序": index, "销售阶段": SALES_STAGE_CN.get(stage, stage)}
                                for index, stage in enumerate(stage_order, start=1)
                            ]
                        ),
                        use_container_width=True,
                        hide_index=True,
                    )
                product_tags = definition.get("product_tags", [])
                if product_tags:
                    st.markdown("**商品专属标签：** " + "、".join(map(str, product_tags)))
                recommended = definition.get("recommended_structure", "")
                if recommended:
                    st.markdown(f"**推荐结构：** {recommended}")
                taxonomy_status = STATUS_CN.get(taxonomy["status"], taxonomy["status"])
                st.caption(f"模板版本 {taxonomy['version']} · 状态：{taxonomy_status}")
                if taxonomy["status"] != "approved" and st.button("批准此商品模板"):
                    repository.approve_taxonomy(taxonomy["id"])
                    st.success("模板已批准，后续混剪将版本化复用。")

    with tabs[5]:
        if selected_product:
            p1, p2, p3 = st.columns(3)
            target = p1.number_input("目标秒数", 20, 35, 30)
            language = p2.selectbox("脚本语言", ["ms"], format_func=lambda _: "马来语")
            audio_mode = p3.selectbox(
                "默认音频",
                ["voiceover", "original"],
                format_func=lambda x: "AI 旁白" if x == "voiceover" else "原声",
            )
            if st.button("生成 3 条候选时间线", type="primary"):
                try:
                    with st.spinner("正在按销售逻辑搜索不同的片段组合..."):
                        created = workflow.create_projects(
                            str(selected_product),
                            target_duration=float(target),
                            language=language,
                            audio_mode=audio_mode,
                        )
                    st.success(f"已生成 {len(created)} 条候选")
                except Exception as exc:
                    st.error(str(exc))
        projects = [
            row for row in repository.projects()
            if not selected_product or row["product_id"] == str(selected_product)
        ]
        if projects:
            project_labels = {
                row["id"]: (
                    f"{labels.get(row['product_id'], row['product_id'])} · "
                    f"{PROJECT_STATUS_CN.get(row['status'], row['status'])} · {row['id'][:8]}"
                )
                for row in projects
            }
            project_id = st.selectbox(
                "混剪项目", list(project_labels), format_func=lambda value: project_labels[value]
            )
            version = repository.latest_timeline(project_id)
            if version:
                library_rows = repository.search_segments(
                    str(projects[[row["id"] for row in projects].index(project_id)]["product_id"]),
                    duration_min=0.1,
                    duration_max=20,
                    confidence_min=0,
                    limit=300,
                )
                edited = video_timeline(
                    version["timeline"],
                    timeline_version=version["version"],
                    segment_library=[_segment_to_clip(row) for row in library_rows],
                    key=f"timeline_{project_id}_{version['version']}",
                )
                if edited and st.button("保存人工调整为新版本"):
                    try:
                        saved = repository.save_timeline(project_id, edited, source="human")
                        st.success(f"已保存时间线 v{saved['version']}，旧版本仍可追溯。")
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
                if st.button("加入渲染队列", type="primary"):
                    job = repository.create_job("render_project", {"project_id": project_id})
                    st.success(f"渲染任务已创建：{job['id'][:10]}")
        else:
            st.info("当前商品还没有混剪项目，可由 AI 生成，或在“片段库”中手动选择片段新建。")

    with tabs[6]:
        renders = repository.renders()
        completed = [
            row for row in renders
            if row["status"] == "completed"
            and (not selected_product or row["product_id"] == str(selected_product))
        ]
        if not completed:
            st.info("渲染完成后，原声版和 AI 旁白版会出现在这里。")
        else:
            render_labels = {
                row["id"]: (
                    f"{labels.get(row['product_id'], row['product_id'])} · "
                    f"{row['created_at']} · {row['id'][:8]}"
                )
                for row in completed
            }
            render_id = st.selectbox(
                "待审核成片", list(render_labels), format_func=lambda value: render_labels[value]
            )
            render = next(row for row in completed if row["id"] == render_id)
            if render.get("voiceover_path"):
                st.video(render["voiceover_path"])
            if render.get("original_audio_path"):
                st.caption("保留原声版")
                st.video(render["original_audio_path"])
            st.caption("需要修改时，请回到“时间线编辑”调整片段顺序或时长，再重新渲染。")
            reason = st.text_area("审核备注")
            approve, reject = st.columns(2)
            if approve.button("批准成片", type="primary", use_container_width=True):
                repository.review(
                    render["project_id"],
                    "approved",
                    reason=reason,
                    render_path=render.get("voiceover_path") or render["original_audio_path"],
                )
                st.success("已批准，仅记录审核结果，不会自动发布。")
            if reject.button("驳回并返修", use_container_width=True):
                repository.review(
                    render["project_id"],
                    "rejected",
                    reason=reason,
                    render_path=render.get("voiceover_path") or render["original_audio_path"],
                )
                st.warning("已驳回，可返回时间线继续调整。")


page = _sidebar()
if page == "总览":
    _render_home()
elif page == "销售分析智能体":
    _render_sales()
elif page == "投诉登记智能体":
    _render_complaints()
elif page == "TikTok 自然流量":
    _render_tiktok_organic()
elif page == "TikTok 广告投放":
    _render_tiktok_ads()
elif page == "视频混剪":
    _render_video_mixer()
elif page == "成熟平台中心":
    _render_integrations()
else:
    _render_settings()
