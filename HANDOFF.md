# Dome entry people counter — handoff

Goal: live count of people entering the dome's drama show (**capacity 1000**) through
**2 entry gates**, one CP Plus 4MP camera per gate, so staff can stop the queue when the
house is nearly full. Shows run roughly every 30 min from 4:30 pm, peak rush 7–10 pm.
7-day event, 19–25 Nov 2026; the counter started on day 3 (21 Nov). The owner's rule:
never miss a person or a walking child; counting a carried infant now and then is fine.

## Status (2026-11-21 evening, at the venue)
- `counter.py` runs live on the venue laptop (Core Ultra 7 255H, Intel Arc 140T, **no
  NVIDIA needed**): both gates at 25 fps.
- Tuned and checked on recordings of real afternoon entry at both gates (light crowd).
- Phone page with live numbers, reset and undo: https://jagmevada.github.io/counting_cam/
- `recorder.py` is saving both cameras' video for training and later checks.
- **Not yet checked:** peak-hour density (7–10 pm) and after-dark lighting.

## Run it
For the event, start the counter and the recorder detached, with no viewer window:
```
powershell -File start.ps1
```
They then keep running when the terminal, or Claude, is closed (on 2026-11-22 a restarted
Claude session took both down, because they had been started from inside it). The script
starts whichever of the two is not running; `start.ps1 -Takeover` replaces the running
counter with the code on disk without a gap. Output goes to `counter.log` and
`recorder.log`. Stop command: see the top of `start.ps1`.

To watch the video with the count line and the dots:
```
python counter.py              # or: python counter.py --takeover, if one is already running
```
Opens the "Dome entry counter" window: both gates, the count line, and a header with
`INSIDE n / 1000`, per-gate numbers and the total. Header turns orange in the last 100
places and red at house full. `NO VIDEO: Gate n - NOT COUNTING` in red means that feed
has stopped for 5 s.

- **Keep the laptop on its charger.** On 2026-11-21 the charger came out at about 22:10;
  on battery Windows sleeps after 15 idle minutes, and the laptop slept from 22:30:36 to
  22:33:38, three minutes into a rush: nothing was counted or recorded, and that show's
  count is short by several hundred. The counter now asks Windows to stay awake while it
  runs, and the phone page shows a red line while the laptop is on battery. Windows' own
  setting was not changed (Settings > System > Power & battery > Screen, sleep &
  hibernate timeouts: "On battery" is 15 minutes, "Plugged in" is never). A battery lasts
  about 2.5 hours under this load.

- **Before each show's entry: reset.** The two gates work independently, so each has its
  own reset: the "Reset" button beside the gate on the phone page, or `1` / `2` then `y` in
  the window (click it first). "Reset both gates" on the page, or `r` then `y`, is the
  master reset. A reset files that gate's finished count in today's list and in
  `counts.csv` and starts it from 0. The day and event totals are not reset.
- **A day runs from 06:00 to 06:00** (`DAY_START` in `counter.py`), not midnight to
  midnight: on 2026-11-21 shows were still going in at 23:50, and a day change at 00:00
  would have zeroed both gates mid-entry and split that evening's total over two dates.
  Shows after midnight count with the evening they belong to.
- **The 4-minute show window** (`SHOW_WINDOW` in `counter.py`). Each volunteer resets their
  own gate when they start admitting the next show, so the two resets come up to 4 minutes
  apart; a show is about 30 minutes entry to entry. Resets within 4 minutes of each other
  start the same show. After the first gate is reset, the other gate's count still belongs
  to the show that ended and is left out of `INSIDE` until it is reset too. A gate nobody
  resets within 4 minutes is reset automatically, dated back to the first gate's reset:
  its count up to that moment is filed with the old show and the rest counts for the new
  one. Today's list shows one row per show.
- **Correcting a count by hand:** "Set number" beside a gate on the phone page. That gate's
  running count becomes the number entered and the camera carries on from it; the old and
  new values go to `counts.csv` ("count set by hand: a -> b"). Use it after a hand count.
- Reset by mistake: "Undo last reset" on the page, or `u` then `y`. It takes back the last
  press (one gate or both); the count is reopened with whatever was counted since.
- `l` redraw a line, `q` quit. Everything survives a restart (`counts.json`).
- **To load a new version while people are entering: `python counter.py --takeover`.** It
  loads and starts tracking first, then stops the running counter and carries on from its
  numbers, with no gap. If it fails to load, the running counter is left alone. A plain
  stop and start loses about 13 s of counting.
- Each picture shows its gate number large, with the camera address and that gate's in /
  out / frame rate small beneath. The header's second line ends with `TODAY: n`.
- Head dots: yellow = not in yet, green = counted in, red = inside but never counted.
- Gate 1 = camera .251, Gate 2 = camera .252 since 2026-11-22, when the owner moved the
  cameras; on 2026-11-21 it was the other way round, so that day's recordings and tests
  are named `gate1` = .252. IN = walking towards the camera.

## Phone page
https://jagmevada.github.io/counting_cam/ (the `gh-pages` branch; source in `web/index.html`).
It shows each gate's running count, today's finished counts (one row per gate per reset),
each day of the event and the event total, and has the per-gate reset, master reset and
undo buttons.

- How it connects: GitHub Pages cannot reach the laptop, so `counter.py` publishes the
  numbers every 2 s to a free public MQTT broker (`WEB_HOST`, `WEB_TOPIC` at the top of
  `counter.py`; the same two values are at the top of the page's script) and listens there
  for commands. Only counts, gate names and camera addresses go out. No video.
- Anyone with the link can see the numbers. Reset and undo need the **PIN in
  `web_pin.txt`** (made on first start; edit the file and restart to change it). The PIN
  is a guard against casual taps, not strong security.
- The page says `LIVE hh:mm:ss` while numbers arrive, `OFFLINE` when they stop.
- It needs internet on the laptop and the phone. Counting never depends on it:
  `--no-web` turns it off, and the keys above always work.
- To publish a changed page: commit `web/index.html` as `index.html` on `gh-pages`.

## Recording video
```
python recorder.py            # both gates, both streams, 15:45 to 23:59 every day
```
Leave it running: it records in that window each day and waits in between. If the laptop
or the session it runs in is restarted, start it again.
ffmpeg copies the cameras' own H.265 video to `recordings/<date>/` with no re-encoding
(almost no CPU): `gateN_sub_<time>.mkv` (720p, exactly what the counter sees) and
`gateN_main_<time>.mkv` (2560x1440), a new file every 10 minutes. About 3.6 GB per hour
in total, about 29 GB a day. It restarts a dropped stream, and ends for good when the disk
has less than 20 GB free. Replay a file through the counter:
`python counter.py <file.mkv> --nogui --line x1,y1,x2,y2,ix,iy`.
`recordings/2026-11-21/early_tests/` holds the short clips the numbers below came from.

## How it counts
- Detector: YOLO26-L (people), exported once to OpenVINO and run on the Intel GPU
  (`--device xpu`), 640 px input, 720p sub stream. First run downloads and exports it.
- Tracker: ByteTrack, set explicitly (see the comment in `Gate.track`).
- A person counts when the **top-centre of their box (the head)** crosses the line. The
  cameras look down steeply, so heads stay visible in a group.
- Hysteresis (`MARGIN`, `OUT_MARGIN` at the top of `counter.py`): IN once the head is
  11 px past the line, OUT only when it is 90 px back. Pausing on the line does not count.
- `INSIDE` = in − out, so staff walking in and out cancel.
- **Seen-late rule** (`LATE_*` at the top of `counter.py`). In a dense rush a child, or a
  short adult, hidden behind the people in front is first detected already past the line and
  would never count. Such a track counts once it has lasted 8 frames and walked 30 px further
  in within 3 s, unless it starts outside the drawn line's ends, at the picture's edge, or
  within 90 px of a track that ended inside in the last 15 frames (a track that broke).
  `LATE_FRAMES = 0` turns it off.
- Walking children must count. Carried infants are sometimes detected and counted, which
  the owner accepts.

## Count lines
Stored in `line_<ip>.json` as fractions of the frame: `[[x1,y1],[x2,y2],[inside x,y]]`.
**From 2026-11-22 the cameras are in new positions** (and swapped between the gates), so
the lines were drawn again by the owner on a screenshot of each new view:

| | Gate 1 (.251) | Gate 2 (.252) |
|---|---|---|
| line | (0.032, 0.453) – (0.952, 0.456) | (0.002, 0.396) – (0.996, 0.440) |
| height at 720p | y ≈ 327 | y ≈ 285 at the left, 317 at the right |
| drawing | `xx251_new_position_cross_line_blue.png` | `252_new_blue_crossline.png` (both in `D:/Project/JJ119`) |

Both cameras now look along the four queue lanes of their gate; people come down the lanes towards
the camera and leave them at the red mats. Measured on a setup clip: an adult's head is at
y ≈ 246 when the feet reach the mats, so adults cross this line a step after the mats and
a 1.1 m child crosses it at the mats. Yesterday's line files are kept beside the new ones
as `line_<ip>.json.2026-11-21`.

Until 2026-11-21 (old positions, the owner's blue lines from `new_line.png`):

| | Gate 1 (.252) | Gate 2 (.251) |
|---|---|---|
| line | (0.114, 0.5245) – (0.839, 0.53) | (0.191, 0.5788) – (0.761, 0.581) |
| height at 720p | y ≈ 380 | y ≈ 418 |

The left ends were later extended 10% at the owner's request. The drawn ends are for
display only: counting uses the line's height across the whole frame (limiting it to the
drawn ends lost 4 of 67 people at gate 1 in testing).

Gate 2, people counted in on three recordings (6 min total), same rule:

| line height (720p) | in | out |
|---|---|---|
| y = 356 (first line) | 85 | 11 |
| **y = 418 (current)** | **90** | **7** |
| y = 450 | 93 | 7 |
| y = 480 | 94 | 8 |

The first line missed short children: coming round the left post, their heads first
appear already below it. Lower lines count 3–4% more than the current one; the owner
judged y = 480 too low on the live view. Gate 1 is flat from y = 360 to 520 (66–69 in on
a 2.5 min recording), so its line is not critical.

## Measured
- Speed on the Arc 140T at 384x640, per frame: YOLO26-S 5.8 ms, -M 8.8 ms, -L 10.7 ms,
  -X 16.6 ms. L at 544x960 is 19.6 ms (too slow for two cameras at 25 fps).
- Tracker check, gate 1, 2.5 min: library default tracker 61 in, ByteTrack 67 in. Of the
  6 extra, 5 were real people (4 of them children in a group) and 1 was a child counted
  twice. So expect ByteTrack to run about 1–2% high, not low.
- **Hand count, gate 1, night rush 2026-11-21 18:54–18:58** (about 100 people a minute):
  owner counted 205, the counter showed about 175 (in 179, out 8 on the recording). So the
  daytime tuning missed about 15% in a dense burst. Light was fine (bright, colour).
- Three reviews of that recording (`recordings/2026-11-21/gate1_sub_185000.mkv` from 230 s):
  - Of 24 uncounted tracks past the line viewed one by one: 13 real people never counted
    (6 children, 7 short or bent adults), 6 new ids on people already counted, 3 people
    standing inside, 2 unclear.
  - The misses are mostly a detection limit, not true invisibility: in 5 dense frames a
    person could see 18 children above the line; the live tracks held 6, the same model at
    1280 px on the 2560x1440 stream found 17. A bigger model at the same resolution did not
    help. Hidden children often score 0.1–0.3, under ByteTrack's 0.25 for a new track.
  - The seen-late rule on the recorded tracks: 179 becomes 214 in (206 in − out), against
    the hand count of 205–210. Viewed one by one, 10 of 14 additions were real, 2 unclear,
    2 double counts; so it over-adds a little, which the owner prefers to missing people.
    On the daytime recordings it adds 0–4 per clip.
- Still do a hand count of 50–100 people at each gate after any change.

## Open items
1. **4MP stream** (`--subtype 0 --imgsz 960 --no-late`): tried live on 2026-11-21 from
   20:15. It held 25 fps on both gates for 37 minutes, then fell to 16-18 fps from 20:52
   and stayed there (GPU at about 79%, CPU at about 45%; cause not found, the laptop
   heating up is the likely one), so the counter was switched back at 20:55. The one full
   show on 4MP counted 1,047 with no hand count to compare. Replayed on the recorded rush
   it scored about the same as 720p with the seen-late rule (152 against 158, true figure
   about 156), and with the rule left on it double counted (178).
   The whole hand-counted clip (gate 1, 18:54, hand count 205, 250 s), people counted in:

   | Setup | In |
   |---|---|
   | 720p, plain | 179 |
   | 720p with the seen-late rule (the running setup) | 214 |
   | Full resolution at 960, full frame, no rule | 196 |
   | Full resolution at 960, cropped to x 200-2360, y 110-1440, no rule | 201 |
   | Full resolution at 960, tighter 16:9 crop (x 205-2253, y 288-1440), no rule | 197 |
   | Full resolution with the rule on top | 228-237 |

   So full resolution with a crop gets within 2% of the hand count by real detections, but
   it is not better than the running setup, the crop itself is worth only 2-3%, and the
   rule must stay off with it. Before trying again:
   find the slowdown (cooling, power plan, a lighter model such as YOLO26-M at 960) and
   get a hand count. Also untested: ByteTrack's `new_track_thresh` at about 0.15, and a
   crowd-trained **head** detector (the recordings are the training data).
2. After dark: confirm detection still works under the venue lights / camera night mode.
3. Never run a second GPU job next to the live counter during entry: on 2026-11-21 at
   19:19 a test run plus a reviewer's job dropped the live counter to 0.3 fps for about
   20 s. Replay recorded tracks through the counting code on the CPU instead (no video).
4. Gate 2's line 30 px lower counted 3% more in testing (table above). With the owner's
   "never miss a child" rule this is worth re-offering.
5. A start-up stall happened once (both gates froze after loading). Models now load one
   at a time at start-up; watch the first start of each day.
6. A paper RESET sign held up to the camera was considered and dropped in favour of the
   phone page. If wanted later, use a printed ArUco code (`cv2.aruco`), not plain text.

## Cameras
| | Cam 1 = Gate 2 | Cam 2 = Gate 1 |
|---|---|---|
| IP (static) | 192.168.1.251 | 192.168.1.252 |
| MAC | F8:20:97:BD:55:13 | F8:20:97:BD:54:FC |
| Mask / GW | 255.255.255.0 / 192.168.1.1 | same |

- Brand CP Plus (Dahua-based firmware), 4MP. User `admin`, password: **ask the owner**
  (not stored in this repo). Camera clock is wrong (shows 15-11-2026) — fix in
  Setup → System → General → Date & Time.
- **Stream URL** (checked 2026-11-21 with login):
  `rtsps://<user>:<pass>@<ip>:554/video/live?channel=1&subtype=N`
  - `subtype=0` main: 2560x1440, 25 fps, H.265
  - `subtype=1` sub: 1280x720, 25 fps, H.265
  - The standard Dahua path `/cam/realmonitor` returns **404** on this firmware.
  - Port 554 accepts **RTSP over TLS only** (`rtsps://`); plain `rtsp://` is dropped.
- Web UI: https://<ip> (self-signed cert).
- Camera old CGI/RPC APIs (`/cgi-bin/...`, `/RPC2`) return 404 on this firmware.

## Network setup on the PC
Cameras are on 192.168.1.x. On the venue laptop the USB Ethernet adapter is
"Ethernet 2", set to static `192.168.1.201/24` with no gateway (Wi-Fi is on 172.16.x and
carries the internet). Admin PowerShell:
```powershell
Set-NetIPInterface -InterfaceAlias 'Ethernet 2' -Dhcp Disabled
New-NetIPAddress -InterfaceAlias 'Ethernet 2' -IPAddress 192.168.1.201 -PrefixLength 24
```
If the PC's Wi-Fi is **also** on 192.168.1.x, don't give the Ethernet a /24 (overlap):
```powershell
New-NetIPAddress -InterfaceAlias Ethernet -IPAddress 192.168.1.201 -PrefixLength 32
New-NetRoute -InterfaceAlias Ethernet -DestinationPrefix 192.168.1.251/32 -RouteMetric 1
New-NetRoute -InterfaceAlias Ethernet -DestinationPrefix 192.168.1.252/32 -RouteMetric 1
```
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
python counter.py
```
- Tested on Python 3.14, Ultralytics 8.4, OpenVINO 2026.4.
- **OpenCV is pinned to 4.10.0.84.** OpenCV 5.x's bundled FFmpeg rejects the cameras'
  self-signed certificate (`tls ... 0x80090325`) and no stream opens.
- NVIDIA laptop instead: install CUDA torch, then `python counter.py --device 0`.
- The laptop screen is scaled 200%, so the counter window is resizable; drag or maximise it.

## Files
- `counter.py` — the counter (above).
  - Clip test: `python counter.py clip.avi --nogui --save out.mp4 --line x1,y1,x2,y2,ix,iy`
    (fractions 0–1). Clip runs never touch the live totals.
  - Defaults: `--model yolo26l.pt --imgsz 640 --device xpu --conf 0.1 --subtype 1
    --capacity 1000`. `--conf 0.1` is deliberate: the tracker uses weak detections to hold
    a half-hidden person.
- `recorder.py` — saves the cameras' video with ffmpeg (see Recording video).
- `web/index.html` — the phone page (see Phone page). Needs `paho-mqtt` on the laptop.
- `camviewer.py` — plain Tk viewer, both cams side by side. Run: `pythonw camviewer.py`.
- `251_cam.png`, `252_cam.png`, `new_line.png` — the owner's line drawings.

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
| `cannot open stream (check login)` | wrong password, or OpenCV 5.x (it rejects the cameras' certificate) | check password; `pip install opencv-python==4.10.0.84`. Do **not** upgrade to 5.x |
| one tile missing / off-screen | old layout bug (fixed in this repo) | `git pull` |

Start the viewer with `pythonw camviewer.py` (don't launch it with a hidden window style —
the Tk window gets hidden too).

## Not in repo (gitignored)
`counts.json`, `counts.csv`, `line_*.json` (site-specific), `web_pin.txt`, `recordings/`,
`*.mp4`, `*.pt`, `*_openvino_model/`, logs.
Reference clip of last year's crowd: `Downloads/20251107_175906.mp4` on the old laptop
(1080p60, 36 s) — copy manually if needed.
