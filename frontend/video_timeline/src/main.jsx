import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ChevronLeft,
  ChevronRight,
  Pause,
  Play,
  Plus,
  Redo2,
  RotateCcw,
  Save,
  Scissors,
  Trash2,
  Undo2,
} from "lucide-react";
import { Timeline as TimelineEditor } from "@xzdarcy/react-timeline-editor";
import "@xzdarcy/react-timeline-editor/dist/react-timeline-editor.css";
import { Streamlit, withStreamlitConnection } from "streamlit-component-lib";
import "./style.css";

const stageMeta = {
  hook: ["开头钩子", "#d9485f"],
  pain_point: ["痛点", "#d97706"],
  product_reveal: ["产品亮相", "#12806f"],
  unboxing: ["开箱展示", "#3478c9"],
  feature_intro: ["功能介绍", "#7157a3"],
  feature_proof: ["功能证明", "#217c9a"],
  detail: ["细节特写", "#5f6f7a"],
  use_case: ["使用场景", "#427f48"],
  social_proof: ["社会证明", "#a64f7b"],
  offer: ["优惠信息", "#b7760d"],
  cta: ["引导下单", "#b93636"],
};

const makeId = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;

function recalculate(items) {
  let cursor = 0;
  return items.map((item) => {
    const duration = Math.max(0.1, Number(item.source_end) - Number(item.source_start));
    const next = {
      ...item,
      clip_id: item.clip_id || makeId(),
      timeline_start: cursor,
      timeline_end: cursor + duration,
    };
    cursor += duration;
    return next;
  });
}

function hydrateClips(items, library) {
  const bySegment = new Map(library.map((item) => [item.segment_id, item]));
  return items.map((item) => ({ ...bySegment.get(item.segment_id), ...item }));
}

function TimelineStudio({ args }) {
  const original = args.timeline || { clips: [] };
  const library = args.segment_library || [];
  const timelineRef = useRef(null);
  const videoRef = useRef(null);
  const [clips, setClips] = useState(() => recalculate(hydrateClips(original.clips || [], library)));
  const [selectedId, setSelectedId] = useState(() => original.clips?.[0]?.clip_id || "");
  const [past, setPast] = useState([]);
  const [future, setFuture] = useState([]);
  const [playhead, setPlayhead] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [zoom, setZoom] = useState(110);
  const [librarySearch, setLibrarySearch] = useState("");
  const [libraryStage, setLibraryStage] = useState("");

  useEffect(() => {
    const next = recalculate(hydrateClips(original.clips || [], library));
    setClips(next);
    setSelectedId(next[0]?.clip_id || "");
    setPast([]);
    setFuture([]);
    setPlayhead(0);
  }, [args.timeline_version]);

  useEffect(() => {
    const resize = () => Streamlit.setFrameHeight(window.innerWidth < 600 ? 1510 : 860);
    resize();
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, [clips, selectedId, zoom]);

  const commit = useCallback((next) => {
    setPast((history) => [...history.slice(-49), clips]);
    setFuture([]);
    setClips(recalculate(next));
  }, [clips]);

  const duration = clips.length ? clips[clips.length - 1].timeline_end : 0;
  const selectedIndex = clips.findIndex((clip) => clip.clip_id === selectedId);
  const active = clips[selectedIndex >= 0 ? selectedIndex : 0];

  const effects = useMemo(() => Object.fromEntries(
    Object.entries(stageMeta).map(([id, [name]]) => [id, { id, name }]),
  ), []);

  const editorData = useMemo(() => [{
    id: "video-track",
    actions: clips.map((clip) => ({
      id: clip.clip_id,
      start: clip.timeline_start,
      end: clip.timeline_end,
      effectId: clip.stage,
    })),
  }], [clips]);

  const seek = useCallback((time) => {
    const bounded = Math.max(0, Math.min(Number(time) || 0, duration));
    setPlayhead(bounded);
    timelineRef.current?.setTime(bounded);
    const index = clips.findIndex(
      (clip) => bounded >= clip.timeline_start && bounded < clip.timeline_end,
    );
    if (index < 0) return;
    const clip = clips[index];
    setSelectedId(clip.clip_id);
    requestAnimationFrame(() => {
      if (videoRef.current) {
        videoRef.current.currentTime = clip.source_start + bounded - clip.timeline_start;
      }
    });
  }, [clips, duration]);

  useEffect(() => {
    if (!active || !videoRef.current) return;
    const local = Math.max(0, playhead - active.timeline_start);
    const target = Math.min(active.source_end - 0.02, active.source_start + local);
    const video = videoRef.current;
    const apply = () => {
      video.currentTime = Math.max(active.source_start, target);
      if (playing) video.play().catch(() => setPlaying(false));
    };
    if (video.readyState >= 1) apply();
    else video.addEventListener("loadedmetadata", apply, { once: true });
  }, [active?.clip_id]);

  const onVideoTime = () => {
    if (!active || !videoRef.current) return;
    const sourceTime = videoRef.current.currentTime;
    const globalTime = active.timeline_start + sourceTime - active.source_start;
    setPlayhead(Math.max(active.timeline_start, Math.min(active.timeline_end, globalTime)));
    timelineRef.current?.setTime(globalTime);
    if (playing && sourceTime >= active.source_end - 0.06) {
      const next = clips[selectedIndex + 1];
      if (next) {
        setPlayhead(next.timeline_start);
        setSelectedId(next.clip_id);
      } else {
        setPlaying(false);
        videoRef.current.pause();
      }
    }
  };

  const togglePlayback = () => {
    if (!videoRef.current || !active) return;
    if (playing) {
      videoRef.current.pause();
      setPlaying(false);
    } else {
      if (playhead >= active.timeline_end - 0.03) seek(active.timeline_start);
      videoRef.current.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
    }
  };

  const syncEditor = (rows) => {
    const actions = [...(rows[0]?.actions || [])].sort((a, b) => a.start - b.start);
    const byId = new Map(clips.map((clip) => [clip.clip_id, clip]));
    const next = actions.map((action) => {
      const clip = byId.get(action.id);
      if (!clip) return null;
      const startDelta = action.start - clip.timeline_start;
      const endDelta = action.end - clip.timeline_end;
      const movedOnly = Math.abs(startDelta - endDelta) < 0.002;
      let sourceStart = clip.source_start;
      let sourceEnd = clip.source_end;
      if (!movedOnly) {
        if (Math.abs(startDelta) >= 0.002) sourceStart += startDelta;
        if (Math.abs(endDelta) >= 0.002) sourceEnd += endDelta;
      }
      if (sourceEnd - sourceStart < 0.1 || sourceStart < 0) return clip;
      return { ...clip, source_start: sourceStart, source_end: sourceEnd };
    }).filter(Boolean);
    commit(next);
  };

  const splitAtPlayhead = () => {
    const index = clips.findIndex(
      (clip) => playhead > clip.timeline_start + 0.099 && playhead < clip.timeline_end - 0.099,
    );
    if (index < 0) return;
    const clip = clips[index];
    const sourceAt = clip.source_start + playhead - clip.timeline_start;
    const left = {
      ...clip,
      clip_id: makeId(),
      source_end: sourceAt,
      label: `${clip.label || stageMeta[clip.stage]?.[0]}（前段）`,
    };
    const right = {
      ...clip,
      clip_id: makeId(),
      source_start: sourceAt,
      label: `${clip.label || stageMeta[clip.stage]?.[0]}（后段）`,
    };
    commit([...clips.slice(0, index), left, right, ...clips.slice(index + 1)]);
    setSelectedId(right.clip_id);
  };

  const undo = () => {
    if (!past.length) return;
    const previous = past[past.length - 1];
    setPast(past.slice(0, -1));
    setFuture([clips, ...future].slice(0, 50));
    setClips(previous);
  };

  const redo = () => {
    if (!future.length) return;
    const next = future[0];
    setFuture(future.slice(1));
    setPast([...past, clips].slice(-50));
    setClips(next);
  };

  const addClip = (candidate) => {
    const next = { ...candidate, clip_id: makeId() };
    commit([...clips, next]);
    setSelectedId(next.clip_id);
  };

  const deleteActive = () => {
    if (!active) return;
    const next = clips.filter((clip) => clip.clip_id !== active.clip_id);
    commit(next);
    setSelectedId(next[Math.min(selectedIndex, next.length - 1)]?.clip_id || "");
  };

  const updateActive = (changes) => {
    if (!active) return;
    const next = clips.map((clip) => clip.clip_id === active.clip_id ? { ...clip, ...changes } : clip);
    const changed = next.find((clip) => clip.clip_id === active.clip_id);
    if (changed.source_end - changed.source_start < 0.1 || changed.source_start < 0) return;
    commit(next);
  };

  const filteredLibrary = library.filter((clip) => {
    const text = `${clip.label || ""} ${clip.stage_cn || ""} ${clip.video_id || ""}`.toLowerCase();
    return (!libraryStage || clip.stage === libraryStage)
      && (!librarySearch || text.includes(librarySearch.toLowerCase()));
  });

  const save = () => Streamlit.setComponentValue({
    ...original,
    clips: recalculate(clips),
    duration: Number(duration.toFixed(3)),
  });

  return (
    <main>
      <header className="studio-header">
        <div>
          <strong>时间线版本 v{args.timeline_version || 1}</strong>
          <span>{duration.toFixed(2)} 秒 · 竖屏 9:16 · {clips.length} 个片段</span>
        </div>
        <div className="toolbar">
          <button title="撤销" onClick={undo} disabled={!past.length}><Undo2 size={17} /></button>
          <button title="恢复" onClick={redo} disabled={!future.length}><Redo2 size={17} /></button>
          <button title="恢复当前版本" onClick={() => setClips(recalculate(hydrateClips(original.clips || [], library)))}>
            <RotateCcw size={17} />
          </button>
          <button className="primary" title="保存时间线" onClick={save}>
            <Save size={17} /><span>保存调整</span>
          </button>
        </div>
      </header>

      <section className="workspace">
        <aside className="library-panel">
          <div className="panel-title"><strong>片段库</strong><span>{filteredLibrary.length} 条</span></div>
          <input
            className="library-search"
            value={librarySearch}
            onChange={(event) => setLibrarySearch(event.target.value)}
            placeholder="搜索片段内容"
          />
          <select value={libraryStage} onChange={(event) => setLibraryStage(event.target.value)}>
            <option value="">全部销售阶段</option>
            {Object.entries(stageMeta).map(([id, [name]]) => <option key={id} value={id}>{name}</option>)}
          </select>
          <div className="library-list">
            {filteredLibrary.slice(0, 100).map((clip) => (
              <div
                className="library-item"
                key={`${clip.segment_id}-${clip.source_start}-${clip.source_end}`}
                draggable
                onDragStart={(event) => event.dataTransfer.setData("segment", JSON.stringify(clip))}
              >
                <div><strong>{clip.stage_cn || stageMeta[clip.stage]?.[0]}</strong><small>{clip.label}</small></div>
                <button title="加入时间线" onClick={() => addClip(clip)}><Plus size={15} /></button>
                <span>{(clip.source_end - clip.source_start).toFixed(1)} 秒</span>
              </div>
            ))}
          </div>
        </aside>

        <section className="preview-panel">
          <div className="video-shell">
            {active ? (
              <video
                ref={videoRef}
                key={active.preview_url || active.source_path}
                src={active.preview_url}
                preload="metadata"
                onTimeUpdate={onVideoTime}
                onPlay={() => setPlaying(true)}
                onPause={() => setPlaying(false)}
              />
            ) : <div className="empty-preview">从片段库加入素材</div>}
          </div>
          <div className="transport">
            <button title="后退一帧" onClick={() => seek(playhead - 1 / 30)}><ChevronLeft size={18} /></button>
            <button className="play" title={playing ? "暂停" : "播放"} onClick={togglePlayback}>
              {playing ? <Pause size={19} /> : <Play size={19} />}
            </button>
            <button title="前进一帧" onClick={() => seek(playhead + 1 / 30)}><ChevronRight size={18} /></button>
            <code>{playhead.toFixed(3)} / {duration.toFixed(3)} 秒</code>
            <button title="在播放头处分割" onClick={splitAtPlayhead} disabled={!active}>
              <Scissors size={17} /><span>分割</span>
            </button>
            <button title="删除所选片段" onClick={deleteActive} disabled={!active}><Trash2 size={17} /></button>
          </div>
        </section>

        <aside className="inspector-panel">
          <div className="panel-title"><strong>片段属性</strong><span>{active ? stageMeta[active.stage]?.[0] : "未选择"}</span></div>
          {active && <>
            <label>片段内容<strong>{active.label || stageMeta[active.stage]?.[0]}</strong></label>
            <label>来源视频<small>{active.video_id}</small></label>
            <div className="field-row">
              <label>入点（秒）<input type="number" step="0.04" value={active.source_start.toFixed(3)} onChange={(e) => updateActive({ source_start: Number(e.target.value) })} /></label>
              <label>出点（秒）<input type="number" step="0.04" value={active.source_end.toFixed(3)} onChange={(e) => updateActive({ source_end: Number(e.target.value) })} /></label>
            </div>
            <label>销售阶段<select value={active.stage} onChange={(e) => updateActive({ stage: e.target.value, stage_cn: stageMeta[e.target.value]?.[0] })}>
              {Object.entries(stageMeta).map(([id, [name]]) => <option key={id} value={id}>{name}</option>)}
            </select></label>
            <label>片段时长<strong>{(active.source_end - active.source_start).toFixed(3)} 秒</strong></label>
            <label>分析置信度<strong>{Math.round((active.confidence || 0) * 100)}%</strong></label>
          </>}
        </aside>
      </section>

      <section className="timeline-section">
        <div className="timeline-heading">
          <strong>视频轨道</strong>
          <label>时间线缩放<input type="range" min="55" max="220" step="5" value={zoom} onChange={(e) => setZoom(Number(e.target.value))} /></label>
        </div>
        <div
          className="timeline-dropzone"
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            const raw = event.dataTransfer.getData("segment");
            if (raw) addClip(JSON.parse(raw));
          }}
        >
          <TimelineEditor
            ref={timelineRef}
            editorData={editorData}
            effects={effects}
            scale={1}
            scaleSplitCount={10}
            scaleWidth={zoom}
            minScaleCount={Math.max(20, Math.ceil(duration) + 3)}
            rowHeight={76}
            gridSnap
            dragLine
            autoScroll
            onChange={syncEditor}
            onClickTimeArea={(time) => { seek(time); return false; }}
            onCursorDrag={(time) => seek(time)}
            onClickAction={(_, { action, time }) => { setSelectedId(action.id); seek(time); }}
            getActionRender={(action) => {
              const clip = clips.find((item) => item.clip_id === action.id);
              return <div className="timeline-clip" style={{ borderTopColor: stageMeta[clip?.stage]?.[1] }}>
                <strong>{stageMeta[clip?.stage]?.[0] || "片段"}</strong>
                <small>{(action.end - action.start).toFixed(1)} 秒</small>
              </div>;
            }}
          />
        </div>
        <p className="timeline-help">拖动片段可调整顺序，拖动两侧边缘可裁剪；将播放头移到目标位置后点击“分割”。</p>
      </section>
    </main>
  );
}

const ConnectedTimeline = withStreamlitConnection(TimelineStudio);
createRoot(document.getElementById("root")).render(<ConnectedTimeline />);
