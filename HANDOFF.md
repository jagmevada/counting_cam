# Dome entry people counter — handoff

Goal: count people entering the dome through **2 entry gates**, one CP Plus 4MP camera per
gate, live total = gate 1 IN + gate 2 IN. This repo has a working 2-camera viewer and a
first-version counter. Counting needs an **NVIDIA GPU laptop** (old laptop: 0.8 fps).

## Status (2026-11-21, at the venue)
- Both cameras installed at the gates and streaming: 1280x720 sub stream at 25 fps each,
  via `camviewer.py`. Link to PoE switch 1 Gbps.
- `counter.py` written, tested once on last year's phone clip (eye-level, dense crowd):
  stock YOLO **person** model detected only ~7 of ~150 people. Cause: eye-level angle +
  full-body model. Not yet tested on the real gate cameras.
- Cam 2 view (looking down the entry lane from above, steep angle) is a much better angle.

## Cameras
| | Cam 1 | Cam 2 |
|---|---|---|
| IP (static) | 192.168.1.251 | 192.168.1.252 |
| MAC | F8:20:97:BD:55:13 | F8:20:97:BD:54:FC |
| Mask / GW | 255.255.255.0 / 192.168.1.1 | same |

- Brand CP Plus (Dahua-based firmware), 4MP. User `admin`, password: **ask the owner**
  (not stored in this repo). Camera clock is wrong (shows 15-11-2026) — fix in
  Setup → System → General → Date & Time.
- **Stream URL** (from the camera page):
  `rtsp://<user>:<pass>@<ip>:554/video/live?channel=1&subtype=0`
  - `subtype=0` main: 2560x1440, 25 fps, **H.265**
  - `subtype=1` sub: 1280x720, 25 fps (light)
  - Port 554 currently accepts **RTSP over TLS only** → use `rtsps://`. Plain `rtsp://`
    gets reset. The scripts try plain first, then rtsps, so both cases work.
- Web UI: https://<ip> (self-signed cert).
- Camera old CGI/RPC APIs (`/cgi-bin/...`, `/RPC2`) return 404 on this firmware.

## Network setup on the PC
Cameras are on 192.168.1.x. If the PC's Wi-Fi is **also** on 192.168.1.x, don't give the
Ethernet a /24 (overlap). Instead (admin PowerShell):
```powershell
New-NetIPAddress -InterfaceAlias Ethernet -IPAddress 192.168.1.201 -PrefixLength 32
New-NetRoute -InterfaceAlias Ethernet -DestinationPrefix 192.168.1.251/32 -RouteMetric 1
New-NetRoute -InterfaceAlias Ethernet -DestinationPrefix 192.168.1.252/32 -RouteMetric 1
```
If Wi-Fi is on another subnet, just set Ethernet static `192.168.1.201/24`.
Check: `ping 192.168.1.251` and `.252`.

Known issue seen in the office: PoE switch link dropped repeatedly + cameras clicking
(IR-cut filter on reboot) → switch power/adapter. At the venue the link was stable.

## Password
Scripts read the camera password from env var `CAM_PASS` (falls back to
`HKCU\Environment`, so `setx` works without a new shell):
```
setx CAM_PASS "<camera password>"
```

## New laptop setup
```
git clone <this repo> && cd <repo>
python -m pip install -r requirements.txt
# GPU: install CUDA torch first, see https://pytorch.org/get-started/locally/
python -c "import torch; print(torch.cuda.is_available())"   # must print True
```
Python 3.11+ (tested on 3.13). `yolo11s.pt` downloads automatically on first run.

## Files
- `camviewer.py` — Tk viewer, both cams side by side, auto-connects with `CAM_PASS`,
  shows transport/resolution/fps per tile. Run: `pythonw camviewer.py`.
  Sub stream by default; Main (HD) is H.265 4MP — old laptop's iGPU can't decode it
  (lag); any modern NVIDIA/Intel laptop is fine.
- `counter.py` — YOLO + ByteTrack line-crossing counter.
  - Live: `python counter.py 192.168.1.251 192.168.1.252`
  - Clip: `python counter.py clip.mp4 --save out.mp4 [--line x1,y1,x2,y2,ix,iy] [--nogui]`
  - First run per camera: click 2 points = count line, 3rd click = INSIDE (dome) side.
    Saved to `line_<ip>.json`.
  - Keys: `l` redraw line, `r` then `y` reset, `q` quit.
  - Totals persist in `counts.json` (restart resumes); per-minute rows in `counts.csv`.
  - Defaults: `--model yolo11s.pt --imgsz 960 --conf 0.3 --subtype 0`.

## Next steps (in order)
1. On the GPU laptop: run `counter.py` on both live cameras, draw lines across each gate.
2. Walk-test: 10 in / 5 out per gate → expect IN=10, OUT=5. Note accuracy.
3. If people in dense flow are missed: switch to a **head-detection** model (crowd-trained
   YOLO head weights) and count by head position instead of box centre
   (`counter.py`, the `ponytail:` comment in `Gate.run`). Use `--subtype 0` (4MP) on GPU.
4. Record 5 min of real crowd per gate, manual-count it, compare (target ≥ 90–95%).

## Exact working stream URL (test in VLC: Media → Open Network Stream)
```
rtsps://admin:<password>@192.168.1.251:554/video/live?channel=1&subtype=1
rtsps://admin:<password>@192.168.1.252:554/video/live?channel=1&subtype=1
```
- `rtsps` (TLS), not `rtsp`.
- Any `@` inside the password must be written `%40` in a URL (`@` separates login from IP).
  The scripts encode this automatically.
- `subtype=1` = 1280x720 light; `subtype=0` = 4MP.

## Troubleshooting: viewer window blank
Read the status text above each tile:
| Status | Cause | Fix |
|---|---|---|
| `idle` | no password → never connected | type it + Connect, or `setx CAM_PASS "..."` then **reopen** the viewer (setx only affects programs started after it) |
| stuck `connecting...` | PC can't reach camera | `ping 192.168.1.251`; fix Ethernet IP/routes (Network setup above) |
| `cannot open stream (check login)` | wrong password / old OpenCV | check password; `pip install -U opencv-python` |
| one tile missing / off-screen | old layout bug (fixed in this repo) | `git pull` |

Start the viewer with `pythonw camviewer.py` (don't launch it with a hidden window style —
the Tk window gets hidden too).

## Not in repo (gitignored)
`counts.json`, `counts.csv`, `line_*.json` (site-specific), `*.mp4`, `*.pt`, logs.
Reference clip of last year's crowd: `Downloads/20251107_175906.mp4` on the old laptop
(1080p60, 36 s) — copy manually if needed.
