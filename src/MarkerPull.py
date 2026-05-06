import sys
import os

MARKER_COLOR = "Blue"


# ---------------------------------------------------------------------------
# Resolve helpers
# ---------------------------------------------------------------------------

def get_resolve():
    # Inside Resolve: bmd is injected as a global by Fusion
    try:
        r = bmd.scriptapp("Resolve")  # noqa: F821
        if r:
            return r, None
    except NameError:
        pass

    # External / CLI fallback
    try:
        import DaVinciResolveScript as dvr_script
        r = dvr_script.scriptapp("Resolve")
        if r:
            return r, None
        return None, "Kunne ikke koble til DaVinci Resolve."
    except ImportError:
        return None, "Kunne ikke koble til Resolve (bmd ikke tilgjengelig)."


def get_active_project_and_timeline(resolve):
    pm = resolve.GetProjectManager()
    if not pm:
        return None, None, "Kunne ikke hente ProjectManager."
    project = pm.GetCurrentProject()
    if not project:
        return None, None, "Ingen aktiv prosjekt funnet."
    timeline = project.GetCurrentTimeline()
    if not timeline:
        return project, None, "Ingen aktiv tidslinje funnet."
    return project, timeline, None


def get_timeline_fps(project):
    raw = project.GetSetting("timelineFrameRate")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 24.0


# ---------------------------------------------------------------------------
# WAV scanner
# ---------------------------------------------------------------------------

def scan_timeline_wav_files(timeline):
    """Return list of {path, name, media_pool_item}, deduplicated by path."""
    track_count = timeline.GetTrackCount("audio")
    seen = {}

    for i in range(1, track_count + 1):
        items = timeline.GetItemListInTrack("audio", i)
        if not items:
            continue
        for clip in items:
            mpi = clip.GetMediaPoolItem()
            if not mpi:
                continue
            path = mpi.GetClipProperty("File Path")
            if not path:
                continue
            if os.path.splitext(path)[1].lower() != ".wav":
                continue
            if path not in seen:
                seen[path] = {
                    "path": path,
                    "name": os.path.basename(path),
                    "media_pool_item": mpi,
                }

    return list(seen.values())


# ---------------------------------------------------------------------------
# WAV cue reader
# ---------------------------------------------------------------------------

def read_wav_cues(file_path):
    """Read cue points from a WAV file.

    Returns:
        list of {name, sample_offset, sample_rate}
        {"error": "missing_wavinfo"}
        {"error": "read_failed", "detail": str}
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

    label_map = {}
    adl = getattr(reader, "adl_chunk", None)
    if adl:
        for entry in getattr(adl, "entries", []):
            label_map[entry.cue_point_id] = entry.text

    cues = []
    for i, point in enumerate(cue_chunk.cue_points):
        raw = label_map.get(point.cue_point_id, "").strip()
        cues.append({
            "name": raw if raw else f"Marker {i + 1}",
            "sample_offset": point.sample_offset,
            "sample_rate": sample_rate,
        })

    return cues


# ---------------------------------------------------------------------------
# Marker injection
# ---------------------------------------------------------------------------

def import_markers_for_file(file_entry, fps):
    """Import cue points as markers on the MediaPoolItem.

    Returns (count, error_string_or_None).
    """
    cues = read_wav_cues(file_entry["path"])

    if isinstance(cues, dict):
        err = cues["error"]
        if err == "missing_wavinfo":
            return 0, "missing_wavinfo"
        return 0, cues.get("detail", "Ukjent feil")

    if not cues:
        return 0, None

    mpi = file_entry["media_pool_item"]
    count = 0
    for i, cue in enumerate(cues):
        frame = round((cue["sample_offset"] / cue["sample_rate"]) * fps)
        name = cue["name"] or f"Marker {i + 1}"
        result = mpi.AddMarker(frame, MARKER_COLOR, name, "", 1, "")
        if result is not False:
            count += 1

    return count, None


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

def run_ui(resolve, project, timeline):
    ui = fusion.UIManager  # noqa: F821 — injected by Resolve
    disp = bmd.UIDispatcher(ui)  # noqa: F821

    fps = get_timeline_fps(project)

    # State: list of {path, name, media_pool_item} parallel to tree rows
    wav_files = []

    dlg = disp.AddWindow(
        {
            "WindowTitle": "MarkerPull",
            "ID": "MarkerPullWin",
            "Geometry": [100, 100, 420, 320],
        },
        [
            ui.VGroup({"Spacing": 6, "Weight": 1}, [
                ui.Label({
                    "ID": "HeaderLabel",
                    "Text": "WAV-filer i tidslinjen:",
                    "Weight": 0,
                }),
                ui.Tree({
                    "ID": "FileList",
                    "Weight": 1,
                    "RootIsDecorated": False,
                    "UniformRowHeights": True,
                    "SortingEnabled": False,
                    "AlternatingRowColors": True,
                }),
                ui.HGroup({"Spacing": 6, "Weight": 0}, [
                    ui.Button({
                        "ID": "RefreshBtn",
                        "Text": "Oppdater liste",
                        "Weight": 1,
                    }),
                    ui.Button({
                        "ID": "ImportBtn",
                        "Text": "Importer markører",
                        "Weight": 1,
                    }),
                ]),
                ui.Label({
                    "ID": "StatusLabel",
                    "Text": "Status: Klar",
                    "Weight": 0,
                }),
            ]),
        ],
    )

    itm = dlg.GetItems()
    tree = itm["FileList"]

    # Single column with checkboxes
    tree.SetColumnCount(1)
    tree.SetHeaderLabels(["Fil"])
    tree.ColumnWidth[0] = 360

    def set_status(msg):
        itm["StatusLabel"].Text = f"Status: {msg}"

    def populate_tree(files):
        tree.Clear()
        for entry in files:
            row = tree.NewItem()
            row.Text[0] = entry["name"]
            row.CheckState[0] = ui.CheckState.Checked
            tree.AddTopLevelItem(row)

    def refresh():
        nonlocal wav_files
        current_timeline = project.GetCurrentTimeline()
        if not current_timeline:
            set_status("Ingen aktiv tidslinje funnet.")
            wav_files = []
            tree.Clear()
            return
        wav_files = scan_timeline_wav_files(current_timeline)
        if not wav_files:
            set_status("Ingen WAV-filer funnet i aktiv tidslinje.")
            tree.Clear()
        else:
            populate_tree(wav_files)
            set_status(f"{len(wav_files)} fil(er) funnet.")

    def on_import(_ev):
        if not wav_files:
            set_status("Ingen filer å importere.")
            return

        checked = []
        for row_index in range(tree.TopLevelItemCount()):
            row = tree.TopLevelItem(row_index)
            if row.CheckState[0] == ui.CheckState.Checked:
                checked.append(wav_files[row_index])

        if not checked:
            set_status("Ingen filer er valgt.")
            return

        total = 0
        for entry in checked:
            count, err = import_markers_for_file(entry, fps)
            if err == "missing_wavinfo":
                set_status("Mangler wavinfo. Kjør: pip3 install wavinfo")
                return
            if err:
                set_status(f"Feil for {entry['name']}: {err}")
                return
            if count == 0:
                set_status(f"{entry['name']}: ingen markører funnet.")
            total += count

        if total > 0:
            set_status(f"Importerte {total} markør(er) fra {len(checked)} fil(er).")

    dlg.On.MarkerPullWin.Close = lambda ev: disp.ExitLoop()
    dlg.On.RefreshBtn.Clicked = lambda ev: refresh()
    dlg.On.ImportBtn.Clicked = on_import

    refresh()
    dlg.Show()
    disp.RunLoop()
    dlg.Hide()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    resolve, err = get_resolve()
    if not resolve:
        # Try to show a UI error if possible, else print
        try:
            ui = fusion.UIManager  # noqa: F821
            disp = bmd.UIDispatcher(ui)  # noqa: F821
            err_dlg = disp.AddWindow(
                {"WindowTitle": "MarkerPull — Feil", "ID": "ErrWin", "Geometry": [100, 100, 360, 100]},
                [ui.VGroup({}, [
                    ui.Label({"Text": err or "Ukjent feil", "Alignment": {"AlignCenter": True}}),
                    ui.Button({"ID": "OkBtn", "Text": "OK", "Weight": 0}),
                ])],
            )
            err_dlg.On.ErrWin.Close = lambda ev: disp.ExitLoop()
            err_dlg.On.OkBtn.Clicked = lambda ev: disp.ExitLoop()
            err_dlg.Show()
            disp.RunLoop()
            err_dlg.Hide()
        except Exception:
            print(f"[MarkerPull] ERROR: {err}")
        return

    project, timeline, err = get_active_project_and_timeline(resolve)
    if err:
        print(f"[MarkerPull] {err}")
        # Still open the window — refresh button can retry when a timeline is open
        try:
            run_ui(resolve, project or resolve.GetProjectManager().GetCurrentProject(), None)
        except Exception:
            pass
        return

    run_ui(resolve, project, timeline)


# Resolve Utility scripts run with __name__ == "__main__" AND inject fusion/bmd
# as globals. We detect the Resolve context by checking for fusion.
try:
    _ = fusion  # noqa: F821
    _in_resolve = True
except NameError:
    _in_resolve = False

if _in_resolve:
    main()
else:
    # CLI debug mode — print timeline WAV files and their cue points
    resolve, err = get_resolve()
    if not resolve:
        print(f"[MarkerPull] ERROR: {err}")
        sys.exit(1)

    project, timeline, err = get_active_project_and_timeline(resolve)
    if err:
        print(f"[MarkerPull] {err}")
        sys.exit(1)

    fps = get_timeline_fps(project)
    print(f"[MarkerPull] Timeline: {timeline.GetName()}  FPS: {fps}")

    wav_files = scan_timeline_wav_files(timeline)
    if not wav_files:
        print("[MarkerPull] Ingen WAV-filer funnet i aktiv tidslinje.")
    else:
        print(f"[MarkerPull] Fant {len(wav_files)} unike WAV-filer:")
        for entry in wav_files:
            print(f"  - {entry['name']}  ({entry['path']})")
            cues = read_wav_cues(entry["path"])
            if isinstance(cues, dict):
                print(f"      FEIL: {cues}")
            elif not cues:
                print("      (ingen cue points)")
            else:
                for c in cues:
                    secs = c["sample_offset"] / c["sample_rate"]
                    print(f"      cue '{c['name']}'  offset={c['sample_offset']}  ({secs:.3f}s)")
