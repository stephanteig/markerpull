# MarkerPull

DaVinci Resolve Studio utility script that reads WAV cue points from Røde Caster Pro recordings and imports them as markers directly on MediaPool clips.

## Requirements

- DaVinci Resolve Studio 20.2.3+
- `wavinfo` Python package: `pip3 install wavinfo`

## Install

1. Download `MarkerPull_Setup.lua`
2. Open DaVinci Resolve and go to the **Fusion** page
3. Open the scripting console: **Script → Show Console** (or Shift+Cmd+C on macOS)
4. Drag `MarkerPull_Setup.lua` onto the console window

The installer copies MarkerPull to the correct location and attempts to install `wavinfo` automatically. A dialog confirms the result.

Then launch from inside Resolve: **Workspace → Scripts → Utility → MarkerPull**

## Usage

1. Open a project with a timeline containing WAV audio clips
2. Run MarkerPull from the Scripts menu
3. The window auto-scans the active timeline and lists all unique WAV files
4. Check/uncheck the files you want to import markers from
5. Click **Importer markører**
6. Markers appear on the MediaPool clips with color Blue

## How it works

- Scans all audio tracks in the active timeline
- Deduplicates clips that appear on multiple tracks
- Reads WAV cue chunks using `wavinfo`
- Converts sample offsets to frame numbers using the timeline frame rate
- Calls `MediaPoolItem.AddMarker()` for each cue point
