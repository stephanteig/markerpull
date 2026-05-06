# MarkerPull — Developer Reference

## Miljø
- DaVinci Resolve Studio 20.2.3 Build 6
- Python 3.10 (Resolves interne Python-versjon)
- macOS
- Scriptet plasseres i: `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/MarkerPull.py`

## Avhengigheter
- `wavinfo` — leser WAV cue points. Installeres med: `pip3 install wavinfo`
- `DaVinciResolveScript` — innebygd i Resolve, ikke pip

## Arkitektur
- Én enkelt Python-fil: `MarkerPull.py`
- UI bygges med Resolves innebygde `UIManager` (Qt-basert)
- Resolve API aksesseres via `DaVinciResolveScript`
- Marker-lesing gjøres via `wavinfo` direkte på WAV-filen på disk

## Viktige Resolve API-mønstre
- Resolve API returnerer alltid `False` eller `None` ved feil — aldri exceptions. Sjekk alltid returverdi.
- `MediaPoolItem.AddMarker(frameId, color, name, note, duration, customData)` — frameId er relativ til klippets start (ikke timeline-posisjon)
- `MediaPoolItem.GetClipProperty("File Path")` — returnerer absolutt filsti til WAV-filen
- For å finne alle klipp i tidslinjen: iterer over alle tracks via `timeline.GetItemListInTrack("audio", trackIndex)`
- Unngå duplikater: flere tracks kan inneholde klipp fra samme WAV-fil — dedupliser på filsti

## UIManager-mønstre
```python
ui = fusion.UIManager
disp = bmd.UIDispatcher(ui)
dlg = disp.AddWindow({...}, [...])
itm = dlg.GetItems()
dlg.On.MyWindow.Close = lambda ev: disp.ExitLoop()
dlg.Show()
disp.RunLoop()
dlg.Hide()
```

## Navnekonvensjoner
- Funksjoner: `snake_case`
- UI element IDs: `PascalCase`
- Konstanter: `UPPER_SNAKE_CASE`
- Ingen inline styles — bruk StyleSheet-strenger

## Ting Claude aldri skal gjøre
- Legg ALDRI markører på timeline-objektet — kun på `MediaPoolItem`
- Bruk ALDRI hardkodede filstier utenom install-stien dokumentert over
- Anta ALDRI at Resolve API-kall lyktes uten å sjekke returverdi
- Installer ALDRI wavinfo automatisk — vis heller en feilmelding i UI hvis det mangler
