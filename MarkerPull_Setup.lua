-- MarkerPull_Setup.lua  (generated — do not edit manually)
-- Self-contained installer for MarkerPull
--
-- HOW TO USE:
--   1. Open DaVinci Resolve
--   2. Go to the Fusion page
--   3. Open the scripting console (Script > Show Console  or  Shift+Cmd+C)
--   4. Drag this file onto the console window
--   The installer runs automatically and shows a result dialog.

local SCRIPT_NAME = "MarkerPull.py"
local is_windows   = package.config:sub(1,1) == "\\"

-- ---- Paths ----

local function get_install_dir()
    if is_windows then
        local appdata = os.getenv("APPDATA") or ""
        return appdata .. "\\Blackmagic Design\\DaVinci Resolve\\Fusion\\Scripts\\Utility"
    else
        local home = os.getenv("HOME") or ""
        return home .. "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility"
    end
end

-- ---- Helpers ----

local function mkdir_p(path)
    if is_windows then
        os.execute('mkdir "' .. path .. '" 2>nul')
    else
        os.execute('mkdir -p "' .. path .. '"')
    end
end

local function exec_ok(cmd)
    local r = os.execute(cmd)
    -- Lua 5.1 (LuaJIT): returns integer exit code; Lua 5.2+: returns bool
    if type(r) == "boolean" then return r end
    return r == 0
end

-- ---- wavinfo installer ----

local function try_install_wavinfo()
    if is_windows then
        for _, cmd in ipairs({
            "py -m pip install --quiet wavinfo",
            "python3 -m pip install --quiet wavinfo",
            "python -m pip install --quiet wavinfo",
        }) do
            if exec_ok(cmd) then return true, nil end
        end
        return false, "py -m pip install wavinfo"
    else
        for _, py in ipairs({
            "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12",
            "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11",
            "/Library/Frameworks/Python.framework/Versions/3.10/bin/python3.10",
        }) do
            local probe = io.open(py, "r")
            if probe then
                probe:close()
                if exec_ok('"' .. py .. '" -m pip install --quiet wavinfo') then
                    return true, nil
                end
                return false, py .. " -m pip install wavinfo"
            end
        end
        return false, "python3.12 -m pip install wavinfo"
    end
end

-- ---- Embedded script ----

local MARKERPULL_CONTENT = [=[
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


def get_timeline_fps(timeline, project=None):
    """FPS for TimelineItem.AddMarker — prefers timeline.GetSetting."""
    for obj in [timeline, project]:
        if not obj:
            continue
        try:
            v = float(obj.GetSetting("timelineFrameRate"))
            if v > 0:
                return v
        except (TypeError, ValueError):
            pass
    return 25.0


def get_mpi_fps(project):
    """FPS for MediaPoolItem.AddMarker — uses project.GetSetting (not timeline)."""
    try:
        v = float(project.GetSetting("timelineFrameRate"))
        if v > 0:
            print(f"[MarkerPull] mpi_fps from project.GetSetting={v}")
            return v
    except (TypeError, ValueError):
        pass
    print(f"[MarkerPull] mpi_fps fallback=25.0")
    return 25.0


# ---------------------------------------------------------------------------
# WAV scanner
# ---------------------------------------------------------------------------

def scan_timeline_wav_files(timeline):
    """Return list of {path, name, media_pool_item, timeline_items}, deduplicated by path."""
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
                    "timeline_items": [],
                }
            seen[path]["timeline_items"].append(clip)

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

    # wavinfo 4.x API: reader.fmt, reader.cues
    fmt = reader.fmt
    if not fmt:
        return []
    sample_rate = fmt.sample_rate

    cues_reader = reader.cues
    if not cues_reader or not cues_reader.cues:
        return []

    label_map = {}
    for entry in (cues_reader.labels or []):
        label_map[entry.name] = entry.text

    cues = []
    for i, point in enumerate(cues_reader.cues):
        raw = label_map.get(point.name, "").strip()
        cues.append({
            "name": raw if raw else f"Marker {i + 1}",
            "sample_offset": point.sample_offset,
            "sample_rate": sample_rate,
        })

    return cues


# ---------------------------------------------------------------------------
# Marker injection
# ---------------------------------------------------------------------------

def import_markers_for_file(file_entry, ti_fps, mpi_fps):
    """Import cue points as markers on both MediaPoolItem and all TimelineItems.

    ti_fps  — timeline fps (from timeline.GetSetting), used for TimelineItem frames
    mpi_fps — project fps  (from project.GetSetting),  used for MediaPoolItem frames

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

    count = 0
    for i, cue in enumerate(cues):
        time_secs = cue["sample_offset"] / cue["sample_rate"]
        name = cue["name"] or f"Marker {i + 1}"

        # MediaPoolItem uses project fps
        mpi_frame = round(time_secs * mpi_fps)
        file_entry["media_pool_item"].AddMarker(mpi_frame, MARKER_COLOR, name, "", 1, "")

        # TimelineItem uses timeline fps, clip-relative
        ti_frame_base = round(time_secs * ti_fps)
        for ti in file_entry.get("timeline_items", []):
            clip_frame = ti_frame_base - ti.GetLeftOffset()
            if clip_frame < 0 or clip_frame >= ti.GetDuration():
                continue
            result = ti.AddMarker(clip_frame, MARKER_COLOR, name, "", 1, "")
            if result is not False:
                count += 1

    return count, None


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------



def run_ui(resolve, project):
    ui = fusion.UIManager  # noqa: F821 — injected by Resolve
    disp = bmd.UIDispatcher(ui)  # noqa: F821

    ti_fps = 25.0
    mpi_fps = get_mpi_fps(project) if project else 25.0

    wav_files = []  # list of {path, name, media_pool_item}, parallel to tree rows

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

    # Fusion UIManager Tree API: use ColumnCount property + SetHeaderItem()
    tree.ColumnCount = 2
    hdr = tree.NewItem()
    hdr.Text[0] = "Fil"
    hdr.Text[1] = "Markører"
    tree.SetHeaderItem(hdr)
    tree.ColumnWidth[0] = 300
    tree.ColumnWidth[1] = 70

    def set_status(msg):
        itm["StatusLabel"].Text = f"Status: {msg}"

    def cue_count_label(file_path):
        cues = read_wav_cues(file_path)
        if isinstance(cues, dict):
            err = cues.get("error", "")
            if err == "missing_wavinfo":
                return "?"
            return "feil"
        return str(len(cues))

    def populate_tree(files):
        tree.Clear()
        for entry in files:
            row = tree.NewItem()
            row.Text[0] = entry["name"]
            row.Text[1] = cue_count_label(entry["path"])
            tree.AddTopLevelItem(row)

    def refresh():
        nonlocal wav_files, ti_fps
        if not project:
            set_status("Ingen aktiv prosjekt funnet.")
            return
        current_timeline = project.GetCurrentTimeline()
        if not current_timeline:
            set_status("Ingen aktiv tidslinje funnet.")
            wav_files = []
            tree.Clear()
            return
        ti_fps = get_timeline_fps(current_timeline, project)
        wav_files = scan_timeline_wav_files(current_timeline)
        if not wav_files:
            set_status("Ingen WAV-filer funnet i aktiv tidslinje.")
            tree.Clear()
        else:
            populate_tree(wav_files)
            set_status(f"{len(wav_files)} fil(er) funnet.")

    def on_import(_ev):
        try:
            _do_import()
        except Exception as e:
            set_status(f"FEIL: {e}")
            print(f"[MarkerPull] Import exception: {e}")

    def _do_import():
        if not wav_files:
            set_status("Ingen filer å importere.")
            return

        total = 0
        skipped = 0
        for entry in wav_files:
            count, err = import_markers_for_file(entry, ti_fps, mpi_fps)
            if err == "missing_wavinfo":
                set_status("Mangler wavinfo. Kjør: pip3 install wavinfo")
                return
            if err:
                set_status(f"Feil for {entry['name']}: {err}")
                return
            if count == 0:
                skipped += 1
            else:
                total += count

        if total > 0:
            set_status(f"Importerte {total} markør(er). {skipped} fil(er) hadde ingen.")
        else:
            set_status("Ingen markører funnet i noen av filene.")

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

def show_error_dialog(message):
    """Show a modal error dialog using Fusion UIManager."""
    ui = fusion.UIManager  # noqa: F821
    disp = bmd.UIDispatcher(ui)  # noqa: F821
    dlg = disp.AddWindow(
        {"WindowTitle": "MarkerPull — Feil", "ID": "ErrWin", "Geometry": [100, 100, 400, 110]},
        [ui.VGroup({"Spacing": 8}, [
            ui.Label({"Text": message, "Alignment": {"AlignHCenter": True, "AlignVCenter": True}}),
            ui.Button({"ID": "OkBtn", "Text": "OK", "Weight": 0}),
        ])],
    )
    dlg.On.ErrWin.Close = lambda ev: disp.ExitLoop()
    dlg.On.OkBtn.Clicked = lambda ev: disp.ExitLoop()
    dlg.Show()
    disp.RunLoop()
    dlg.Hide()


def main():
    resolve, err = get_resolve()
    if not resolve:
        show_error_dialog(err or "Kunne ikke koble til DaVinci Resolve.")
        return

    project, timeline, err = get_active_project_and_timeline(resolve)
    if err:
        print(f"[MarkerPull] {err}")

    run_ui(resolve, project)


# Resolve Utility scripts run with __name__ == "__main__" AND inject fusion/bmd
# as globals. We detect the Resolve context by checking for fusion.
try:
    _ = fusion  # noqa: F821
    _in_resolve = True
except NameError:
    _in_resolve = False

if _in_resolve:
    try:
        main()
    except Exception as e:
        try:
            show_error_dialog(f"Uventet feil: {e}")
        except Exception:
            print(f"[MarkerPull] FEIL: {e}")
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

]=]

-- ---- Install ----

local install_dir = get_install_dir()
mkdir_p(install_dir)

local sep  = is_windows and "\\" or "/"
local dest = install_dir .. sep .. SCRIPT_NAME

local ok, err_msg, wavinfo_ok, pip_cmd

local fh, ferr = io.open(dest, "w")
if not fh then
    ok      = false
    err_msg = "Kunne ikke skrive til:\n" .. dest .. "\n\n" .. (ferr or "Ukjent feil")
else
    fh:write(MARKERPULL_CONTENT)
    fh:close()
    ok = true
    wavinfo_ok, pip_cmd = try_install_wavinfo()
end

-- ---- Result dialog ----

local msg
if not ok then
    msg = "Installasjon feilet:\n\n" .. err_msg
elseif wavinfo_ok then
    msg = "MarkerPull er installert!\n\nStart DaVinci Resolve pa nytt og finn\nscriptet under:\nWorkspace -> Scripts -> Utility -> MarkerPull"
else
    msg = "MarkerPull er kopiert til Resolve.\n\nwavinfo ma installeres manuelt.\nAapne terminalen og kjor:\n\n"
        .. pip_cmd
        .. "\n\nDeretter: restart Resolve og kjor\nWorkspace -> Scripts -> Utility -> MarkerPull"
end

local fusion_obj = fu or fusion
local ui   = fusion_obj.UIManager
local disp = bmd.UIDispatcher(ui)

local btn_row = {}
if ok and not wavinfo_ok then
    table.insert(btn_row, ui:Button({ ID = "CopyBtn", Text = "Kopier kommando", Weight = 1 }))
end
if ok then
    table.insert(btn_row, ui:Button({ ID = "UninstallBtn", Text = "Avinstaller", Weight = 0 }))
end
table.insert(btn_row, ui:Button({ ID = "OkBtn", Text = "OK", Weight = 0 }))

local dlg = disp:AddWindow(
    { WindowTitle = "MarkerPull Setup", ID = "SetupWin", Geometry = {200, 200, 520, 300} },
    {
        ui:VGroup({ Spacing = 10, Weight = 1 }, {
            ui:Label({ ID = "Msg", Text = msg, Weight = 1 }),
            ui:HGroup({ Spacing = 6, Weight = 0 }, btn_row),
        }),
    }
)

local itm = dlg:GetItems()

function dlg.On.SetupWin.Close(ev) disp:ExitLoop() end
function dlg.On.OkBtn.Clicked(ev)  disp:ExitLoop() end

if ok and not wavinfo_ok then
    function dlg.On.CopyBtn.Clicked(ev)
        if is_windows then
            os.execute('echo ' .. pip_cmd .. ' | clip')
        else
            os.execute("echo '" .. pip_cmd .. "' | pbcopy")
        end
        itm["CopyBtn"].Text = "Kopiert!"
    end
end

if ok then
    function dlg.On.UninstallBtn.Clicked(ev)
        local removed = os.remove(dest)
        if removed then
            itm["Msg"].Text = "MarkerPull er avinstallert."
            itm["UninstallBtn"].Enabled = false
        else
            itm["Msg"].Text = "Fjerning feilet. Slett manuelt:\n" .. dest
        end
    end
end

dlg:Show()
disp:RunLoop()
dlg:Hide()
