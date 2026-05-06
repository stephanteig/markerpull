import sys
import os

try:
    import DaVinciResolveScript as dvr_script
except ImportError:
    dvr_script = None


def get_resolve():
    if dvr_script is None:
        print("[MarkerPull] ERROR: DaVinciResolveScript not available.")
        return None
    resolve = dvr_script.scriptapp("Resolve")
    if not resolve:
        print("[MarkerPull] ERROR: Could not connect to DaVinci Resolve.")
        return None
    return resolve


def get_active_timeline(resolve):
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        print("[MarkerPull] ERROR: Could not get ProjectManager.")
        return None, None
    project = project_manager.GetCurrentProject()
    if not project:
        print("[MarkerPull] ERROR: No active project.")
        return None, None
    timeline = project.GetCurrentTimeline()
    if not timeline:
        print("[MarkerPull] ERROR: No active timeline.")
        return None, None
    return project, timeline


def scan_timeline_wav_files(timeline):
    """Return list of dicts: {path, name, media_pool_item}, deduplicated by path."""
    track_count = timeline.GetTrackCount("audio")
    seen_paths = {}

    for track_index in range(1, track_count + 1):
        items = timeline.GetItemListInTrack("audio", track_index)
        if not items:
            continue
        for clip in items:
            media_pool_item = clip.GetMediaPoolItem()
            if not media_pool_item:
                continue
            file_path = media_pool_item.GetClipProperty("File Path")
            if not file_path:
                continue
            ext = os.path.splitext(file_path)[1].lower()
            if ext != ".wav":
                continue
            if file_path not in seen_paths:
                seen_paths[file_path] = {
                    "path": file_path,
                    "name": os.path.basename(file_path),
                    "media_pool_item": media_pool_item,
                }

    return list(seen_paths.values())


def read_wav_cues(file_path):
    """Read cue points from a WAV file.

    Returns:
        list of {name, sample_offset, sample_rate}  — empty if no cues
        {"error": "missing_wavinfo"}                 — if wavinfo not installed
        {"error": "read_failed", "detail": str}      — on unexpected failure
    """
    try:
        from wavinfo import WavInfoReader
    except ImportError:
        return {"error": "missing_wavinfo"}

    try:
        reader = WavInfoReader(file_path)
    except Exception as e:
        return {"error": "read_failed", "detail": str(e)}

    fmt = reader.fmt_chunk
    if not fmt:
        return []
    sample_rate = fmt.sample_rate

    cue_chunk = reader.cue_chunk
    if not cue_chunk or not cue_chunk.cue_points:
        return []

    # Build label map from associated data list if present
    label_map = {}
    adl = getattr(reader, "adl_chunk", None)
    if adl:
        for entry in getattr(adl, "entries", []):
            label_map[entry.cue_point_id] = entry.text

    cues = []
    for i, point in enumerate(cue_chunk.cue_points):
        raw_label = label_map.get(point.cue_point_id, "").strip()
        name = raw_label if raw_label else f"Marker {i + 1}"
        cues.append({
            "name": name,
            "sample_offset": point.sample_offset,
            "sample_rate": sample_rate,
        })

    return cues


if __name__ == "__main__":
    resolve = get_resolve()
    if not resolve:
        sys.exit(1)

    project, timeline = get_active_timeline(resolve)
    if not timeline:
        sys.exit(1)

    print(f"[MarkerPull] Timeline: {timeline.GetName()}")

    wav_files = scan_timeline_wav_files(timeline)
    if not wav_files:
        print("[MarkerPull] No WAV files found in active timeline.")
    else:
        print(f"[MarkerPull] Found {len(wav_files)} unique WAV file(s):")
        for entry in wav_files:
            print(f"  - {entry['name']}  ({entry['path']})")
            cues = read_wav_cues(entry["path"])
            if isinstance(cues, dict):
                print(f"      ERROR: {cues}")
            elif not cues:
                print("      (no cue points)")
            else:
                for c in cues:
                    secs = c["sample_offset"] / c["sample_rate"]
                    print(f"      cue '{c['name']}'  offset={c['sample_offset']} samples  ({secs:.3f}s)")
