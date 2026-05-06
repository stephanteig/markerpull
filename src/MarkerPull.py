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
