#!/usr/bin/env python3
"""Generate MarkerPull_Setup.lua by embedding src/MarkerPull.py as a Lua string.

Run from anywhere:
    python3 scripts/build_setup.py
"""

import os

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_PATH = os.path.join(REPO_DIR, "src", "MarkerPull.py")
OUT_PATH = os.path.join(REPO_DIR, "MarkerPull_Setup.lua")

# Raw string — backslashes are literal, so Lua backslash escapes pass through unchanged.
# Placeholders %%OPEN%%, %%CLOSE%%, %%CONTENT%% are replaced by build().
LUA_TEMPLATE = r"""-- MarkerPull_Setup.lua  (generated — do not edit manually)
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
    -- Ask Fusion where it expects Utility scripts — most reliable across versions and platforms
    local fusion_obj = fu or fusion
    if fusion_obj then
        local mapped = fusion_obj:MapPath("Scripts:Utility")
        if mapped and mapped ~= "" then
            return mapped:gsub("[/\\]$", "")
        end
    end
    -- Fallback for safety
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
        -- Each entry: { path, extra_flag_or_nil }
        -- extra_flag is needed for Homebrew / system Pythons (PEP 668)
        local candidates = {
            { "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13", nil },
            { "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12", nil },
            { "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11", nil },
            { "/Library/Frameworks/Python.framework/Versions/3.10/bin/python3.10", nil },
            { "/opt/homebrew/bin/python3", "--break-system-packages" },
            { "/usr/local/bin/python3",    "--break-system-packages" },
            { "/usr/bin/python3",          "--break-system-packages" },
        }
        local first_found_py  = nil
        local first_found_flag = nil
        for _, entry in ipairs(candidates) do
            local py, flag = entry[1], entry[2]
            local probe = io.open(py, "r")
            if probe then
                probe:close()
                if not first_found_py then
                    first_found_py   = py
                    first_found_flag = flag
                end
                local install_cmd = '"' .. py .. '" -m pip install --quiet '
                    .. (flag and (flag .. ' ') or '') .. 'wavinfo'
                if exec_ok(install_cmd) then return true, nil end
            end
        end
        -- Build the manual command for the first Python we found
        if first_found_py then
            local display = first_found_py .. ' -m pip install '
                .. (first_found_flag and (first_found_flag .. ' ') or '') .. 'wavinfo'
            return false, display
        end
        return false, "python3 -m pip install --break-system-packages wavinfo"
    end
end

-- ---- Embedded script ----

local MARKERPULL_CONTENT = %%OPEN%%
%%CONTENT%%
%%CLOSE%%

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
"""


def main():
    with open(SRC_PATH, encoding="utf-8") as f:
        py_content = f.read()

    if "]=]" in py_content:
        open_str, close_str = "[==[", "]==]"
    else:
        open_str, close_str = "[=[", "]=]"

    lua = (LUA_TEMPLATE
           .replace("%%OPEN%%", open_str)
           .replace("%%CLOSE%%", close_str)
           .replace("%%CONTENT%%", py_content))

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(lua)

    print(f"Generated: {OUT_PATH}")
    print(f"  {len(py_content):,} bytes of MarkerPull.py embedded")
    print(f"  Lua long string level: {open_str}")


if __name__ == "__main__":
    main()
