"""Dome entry counter: people crossing a line at each gate, house-full check against capacity.

Live:  python counter.py                    both gates (Gate 1 = .252, Gate 2 = .251)
Clip:  python counter.py clip.avi --save out.mp4 --line x1,y1,x2,y2,ix,iy [--nogui]

A person is counted when their head (top-centre of their box) crosses the line.
Lines are stored as fractions of the frame (0-1) in line_<name>.json, so one line fits both
the sub and the main stream. To draw one: delete the file or press l, click 2 points for
the line, then 1 point on the INSIDE (dome) side.
Keys: r then y = reset for the next show, u then y = undo the last reset, l = redraw line,
q = quit. The same reset and undo are on the phone page (see WEB_HOST below).
One show = from one reset to the next. counts.json keeps the running show, today's finished
shows and the finished days, so nothing is lost on a restart. counts.csv gets a row per gate
every minute and at every reset (= that show's final count).
"""
import argparse
import csv
import hashlib
import hmac
import json
import math
import os
import secrets
import threading
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS",
                      "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay")
import cv2  # noqa: E402
import numpy as np  # noqa: E402
from ultralytics import YOLO  # noqa: E402

HERE = Path(__file__).parent
COUNTS = HERE / "counts.json"
LOG = HERE / "counts.csv"
CAMERAS = {"192.168.1.252": "Gate 1", "192.168.1.251": "Gate 2"}
WIN = "Dome entry counter"
# ponytail: line hysteresis, as fractions of the frame (11 px / 90 px at 720p). A head counts
# IN once it is MARGIN past the line, and OUT only when it is OUT_MARGIN back on the other
# side, so someone pausing, bending or waving on the line is not counted out again.
# Tuned on recordings of gate 2; raise OUT_MARGIN if people waiting inside cause OUT counts.
MARGIN = 0.015
OUT_MARGIN = 0.125
EVENT_START, EVENT_DAYS = "2026-11-19", 7  # 2026-11-21 was day 3
# Phone page (index.html on the gh-pages branch): the numbers go out and the reset / undo
# commands come in through a free public MQTT broker, nothing else leaves the laptop.
# --no-web turns it off; counting never depends on it. The PIN in web_pin.txt keeps casual
# visitors from resetting; it is not strong security. WEB_TOPIC must match the page.
WEB_HOST, WEB_PORT, WEB_TOPIC = "broker.emqx.io", 8084, "cnt-1223d72e6c6d8499"
PIN_FILE = HERE / "web_pin.txt"
LIVE = None  # True when every source is a camera: only then are the files and the phone page touched
lock = threading.RLock()  # counts, history and files are used from the gate, window and phone threads
state = {"date": "", "show_start": "", "shows": [], "days": {}}  # shows = today's finished ones


def today():
    return time.strftime("%Y-%m-%d")


def clock():
    return time.strftime("%H:%M:%S")


def cam_pass():
    p = os.environ.get("CAM_PASS")
    if not p:  # setx writes HKCU\Environment; older shells don't see it
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            p = winreg.QueryValueEx(k, "CAM_PASS")[0]
    return p


def is_ip(s):
    return s.replace(".", "").isdigit()


def side(line, x, y):
    """Signed distance of (x, y) from the line, in frame fractions."""
    (x1, y1), (x2, y2) = line[0], line[1]
    return ((x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)) / math.hypot(x2 - x1, y2 - y1)


def weights(args):
    """Intel GPU: run the model through OpenVINO, exported once from the .pt (auto-downloads)."""
    if not args.device.startswith(("xpu", "intel")):
        return args.model, args.imgsz  # e.g. --device 0 on an NVIDIA laptop runs the .pt directly
    size = [-(-args.imgsz * 9 // 16 // 32) * 32, args.imgsz]  # 16:9 cameras, rounded up to stride 32
    stem = Path(args.model).stem
    ov = HERE / f"{stem}_{args.imgsz}_openvino_model"
    if not ov.exists():
        made = YOLO(str(HERE / f"{stem}.pt")).export(format="openvino", imgsz=size, half=True)
        Path(made).rename(ov)
    return str(ov), size


class Gate:
    def __init__(self, src, args, totals):
        self.src, self.args = src, args
        self.name = src if is_ip(src) else Path(src).stem
        self.label = CAMERAS.get(src, self.name)
        self.live = is_ip(src)
        self.url = (f"rtsps://admin:{quote(cam_pass(), safe='')}@{src}:554/video/live"
                    f"?channel=1&subtype={args.subtype}") if self.live else src
        t = totals.get(self.name, {})
        self.n_in, self.n_out = t.get("in", 0), t.get("out", 0)
        self.line_file = HERE / f"line_{self.name}.json"
        self.line = json.loads(self.line_file.read_text()) if self.line_file.exists() else None
        if args.line:
            v = [float(a) for a in args.line.split(",")]
            self.line = [v[0:2], v[2:4], v[4:6]]
        if self.line and max(map(max, self.line)) > 1:
            self.line = None  # old pixel-format line file: redraw it
        self.model = YOLO(args.weights, task="detect")  # one model per gate = separate tracker state
        self.cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
        self.latest, self.view, self.fps, self.done = None, None, 0.0, False
        self.seen = time.time()  # when a frame was last processed, for the NO VIDEO warning
        self.sides, self.counted = {}, set()  # track id -> inside?, ids currently counted in

    def grab(self):  # live: keep only the newest frame so we never lag behind
        while not self.done:
            ok, f = self.cap.read()
            if not ok:
                time.sleep(1)
                self.cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
                continue
            self.latest = f

    def next_frame(self):
        if self.live:
            while self.latest is None and not self.done:
                time.sleep(0.01)
            f, self.latest = self.latest, None
            return f
        ok, f = self.cap.read()
        return f if ok else None

    def count(self, tid, x, y):
        d = side(self.line, x, y)
        if side(self.line, *self.line[2]) < 0:
            d = -d  # d > 0 = inside
        inside = self.sides.get(tid)
        if inside is None:  # first sighting clear of the line fixes the starting side
            if abs(d) >= MARGIN:
                self.sides[tid] = d > 0
            return
        # Every real change of side counts, so in - out stays right for each track.
        with lock:  # a reset from the window or the phone must not land in the middle of this
            if not inside and d > MARGIN:
                self.n_in += 1
                self.counted.add(tid)
            elif inside and d < -OUT_MARGIN:
                self.n_out += 1
                self.counted.discard(tid)
            else:
                return
            self.sides[tid] = not inside
            save_state()

    def track(self, f):
        # ByteTrack, set on purpose. The library default (tracktrack in Ultralytics 8.4) starts
        # tracks too late for children half hidden in a group: on a 2.5 min gate 1 recording it
        # counted 61 in, ByteTrack 67; by eye 5 of the extra 6 were real people, 1 a duplicate.
        return self.model.track(f, persist=True, classes=[0], imgsz=self.args.size, tracker="bytetrack.yaml",
                                device=self.args.device, conf=self.args.conf, verbose=False)[0]

    def run(self, writer=None):
        n, t0 = 0, time.time()
        while not self.done:
            f = self.next_frame()
            if f is None:
                break
            r = self.track(f)
            self.seen = time.time()
            h, w = f.shape[:2]
            v = r.plot(labels=False, conf=False, line_width=2)
            if r.boxes.id is not None and self.line:
                for (x1, y1, x2, y2), tid in zip(r.boxes.xyxy.tolist(), r.boxes.id.int().tolist()):
                    # Head, not body centre: from these steep cameras the head stays visible in a
                    # crowd, and it reaches the line when the person is nearest and least hidden.
                    x = (x1 + x2) / 2
                    self.count(tid, x / w, y1 / h)
                    # dot: green = counted in, red = inside but never counted, yellow = not in yet
                    dot = (0, 255, 0) if tid in self.counted else (0, 0, 255) if self.sides.get(tid) else (0, 255, 255)
                    cv2.circle(v, (int(x), int(y1)), 7, dot, -1)
            if self.line:
                a, b, c = [(int(px * w), int(py * h)) for px, py in self.line]
                cv2.line(v, a, b, (0, 255, 255), 3)
                cv2.putText(v, "IN side", c, cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 3)
            # gate number big, camera address and numbers small under it; dark outline so it reads on any picture
            for colour, extra in (((0, 0, 0), 4), ((0, 255, 0), 0)):
                cv2.putText(v, self.label, (20, 66), cv2.FONT_HERSHEY_SIMPLEX, 2.2, colour, 5 + extra)
                cv2.putText(v, f"{self.name}   in {self.n_in}   out {self.n_out}   {self.fps:.0f} fps",
                            (24, 106), cv2.FONT_HERSHEY_SIMPLEX, 0.9, colour, 2 + extra // 2)
            self.view = v
            if writer is not None:
                writer.write(v)
            n += 1
            if time.time() - t0 >= 2:
                self.fps, n, t0 = n / (time.time() - t0), 0, time.time()
                print(f"{self.label} ({self.name}): in={self.n_in} out={self.n_out} fps={self.fps:.1f}", flush=True)
        self.done = True


gates = []


def inside_now():
    return sum(g.n_in - g.n_out for g in gates)


def today_total():
    return sum(s["people"] for s in state["shows"]) + inside_now()


def load_state():
    """Fills `state` from counts.json and returns the running show's per-gate counts. Accepts the
    older file (camera -> counts at the top level); a damaged file means start from zero, not no start."""
    d = {}
    if LIVE and COUNTS.exists():
        try:
            d = json.loads(COUNTS.read_text())
        except (OSError, ValueError) as e:
            print("counts.json unreadable, starting from zero:", e, flush=True)
    state.update(date=d.get("date", today()), show_start=d.get("show_start", clock()),
                 shows=d.get("shows", []), days=d.get("days", {}))
    return d.get("gates") or {k: v for k, v in d.items() if isinstance(v, dict) and "in" in v}


def save_state():
    if not LIVE:  # a clip test must not overwrite the live numbers
        return
    with lock:
        try:  # write then swap, so a crash or power cut cannot leave half a file
            tmp = COUNTS.with_suffix(".tmp")
            tmp.write_text(json.dumps({**state, "gates": {g.name: {"in": g.n_in, "out": g.n_out} for g in gates}}))
            tmp.replace(COUNTS)
        except OSError as e:  # file busy: skip this save, the next count saves again. Never stop counting.
            print("could not save counts.json:", e, flush=True)


def log_counts(note=""):
    if not LIVE:
        return
    with lock:
        try:
            new = not LOG.exists()
            with LOG.open("a", newline="") as fh:
                w = csv.writer(fh)
                if new:
                    w.writerow(["time", "gate", "in", "out", "note"])
                for g in gates:
                    w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), g.label, g.n_in, g.n_out, note])
        except OSError as e:  # counts.csv open in Excel is locked: lose the row, never stop counting
            print("could not write counts.csv:", e, flush=True)


def reset(note="show end"):
    """Starts a new show: the finished one goes to the log and to today's list, the counts go to zero."""
    with lock:
        if any(g.n_in or g.n_out for g in gates):
            log_counts(note)
            state["shows"].append({"start": state["show_start"], "end": clock(), "people": inside_now(),
                                   "gates": {g.label: [g.n_in, g.n_out] for g in gates}})
        for g in gates:
            g.n_in = g.n_out = 0
            g.counted.clear()
        state["show_start"] = clock()
        save_state()


def undo_reset():
    """Takes back the last reset (pressed by mistake): that show is reopened and keeps counting."""
    with lock:
        if not state["shows"]:
            return False
        s = state["shows"].pop()
        for g in gates:
            a, b = s["gates"].get(g.label, [0, 0])
            g.n_in, g.n_out = g.n_in + a, g.n_out + b
        state["show_start"] = s["start"]
        log_counts("reset undone")
        save_state()
        return True


def new_day():
    """The date changed (midnight, or the first start of a day): file the old day's total, start clean."""
    with lock:
        reset("day end")
        total = sum(s["people"] for s in state["shows"])
        state["days"][state["date"]] = total
        log_counts(f"day total {state['date']}: {total}")
        state.update(date=today(), shows=[])
        save_state()


def web(args):
    """Connects the phone page. Returns the function that sends it the current numbers."""
    import paho.mqtt.client as mqtt
    if not PIN_FILE.exists():
        PIN_FILE.write_text(f"{secrets.randbelow(10**6):06d}")
    pin = PIN_FILE.read_text().strip()
    nonce = [secrets.token_hex(8)]  # changes after every accepted command, so a copied command can't be replayed

    def publish():
        first = date.fromisoformat(EVENT_START)
        days = [(first + timedelta(days=i)).isoformat() for i in range(EVENT_DAYS)]
        with lock:
            msg = {"at": clock(), "capacity": args.capacity, "date": state["date"],
                   "show_start": state["show_start"], "gates": {g.label: [g.n_in, g.n_out] for g in gates},
                   "cams": {g.label: g.name for g in gates},
                   "no_video": [g.label for g in gates if not g.done and time.time() - g.seen > 5],
                   "shows": state["shows"], "nonce": nonce[0],
                   "days": [[d, today_total() if d == state["date"] else state["days"].get(d)] for d in days]}
        c.publish(WEB_TOPIC + "/status", json.dumps(msg), retain=True)

    def on_message(c, _, m):
        try:
            msg = json.loads(m.payload)
            cmd = msg["cmd"]
            want = hmac.new(pin.encode(), f"{cmd}|{nonce[0]}".encode(), hashlib.sha256).hexdigest()
            ok = cmd in ("reset", "undo") and hmac.compare_digest(want, str(msg["mac"]))
        except (ValueError, KeyError, TypeError):
            return
        if ok:
            nonce[0] = secrets.token_hex(8)
            if cmd == "undo":
                ok = undo_reset()
            else:
                reset("show end (phone)")
            print(clock(), "phone:", cmd, "done" if ok else "nothing to undo", flush=True)
        c.publish(WEB_TOPIC + "/ack", json.dumps({"id": msg.get("id"), "cmd": cmd, "ok": ok}))
        publish()

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, transport="websockets")
    c.ws_set_options(path="/mqtt")
    c.tls_set()
    c.on_connect = lambda c, *_: c.subscribe(WEB_TOPIC + "/cmd")
    c.on_message = on_message
    c.connect_async(WEB_HOST, WEB_PORT, keepalive=30)
    c.loop_start()  # its own thread, reconnects by itself
    print("phone page link started, reset PIN is in", PIN_FILE.name, flush=True)
    return publish


def pick_line(frame, name):
    """Returns [line start, line end, inside point] as fractions of the frame."""
    pts, win = [], f"Set line: {name}  (2 clicks = line, 3rd = INSIDE side)"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(win, lambda e, x, y, *_: e == cv2.EVENT_LBUTTONDOWN and pts.append([x, y]))
    while len(pts) < 3:
        v = frame.copy()
        for p in pts:
            cv2.circle(v, tuple(p), 8, (0, 255, 255), -1)
        if len(pts) >= 2:
            cv2.line(v, tuple(pts[0]), tuple(pts[1]), (0, 255, 255), 3)
        cv2.imshow(win, v)
        if cv2.waitKey(30) == 27:
            raise SystemExit("line setup cancelled")
    cv2.destroyWindow(win)
    h, w = frame.shape[:2]
    return [[round(x / w, 4), round(y / h, 4)] for x, y in pts]


def first_frame(g):
    for _ in range(100):
        ok, f = g.cap.read()
        if ok:
            if not g.live:
                g.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            return f
    raise SystemExit(f"{g.name}: no video")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sources", nargs="*", default=list(CAMERAS), help="camera IPs or video files")
    ap.add_argument("--capacity", type=int, default=1000, help="house-full number")
    ap.add_argument("--model", default="yolo26l.pt")
    ap.add_argument("--imgsz", type=int, default=640, help="model input width")
    ap.add_argument("--device", default="xpu", help="xpu = Intel GPU via OpenVINO, 0 = NVIDIA, cpu")
    # 0.1 on purpose: the tracker uses weak detections to hold a half-hidden person's track
    ap.add_argument("--conf", type=float, default=0.1)
    ap.add_argument("--subtype", type=int, default=1, help="1 sub (720p), 0 main (4MP)")
    ap.add_argument("--line", help="x1,y1,x2,y2,ix,iy as frame fractions 0-1 (skip clicking)")
    ap.add_argument("--save", help="write annotated video (single file source)")
    ap.add_argument("--nogui", action="store_true")
    ap.add_argument("--no-web", action="store_true", help="don't connect the phone page")
    args = ap.parse_args()
    args.weights, args.size = weights(args)

    global LIVE
    if LIVE is None:
        LIVE = all(is_ip(s) for s in args.sources)
    totals = load_state()
    for s in args.sources:
        g = Gate(s, args, totals)
        if not g.line or (not args.nogui and not g.line_file.exists() and not args.line):
            g.line = pick_line(first_frame(g), g.name)
            g.line_file.write_text(json.dumps(g.line))
        gates.append(g)

    # Load the models one after the other. Seen once on 2026-11-21: with both gate threads loading
    # on the GPU at the same moment, both hung right after "Using OpenVINO..." and nothing counted.
    for g in gates:
        g.track(first_frame(g))

    writer = None
    for g in gates:
        g.seen = time.time()
        if g.live:
            threading.Thread(target=g.grab, daemon=True).start()
        elif args.save:
            fps = g.cap.get(cv2.CAP_PROP_FPS) or 25
            w, h = int(g.cap.get(3)), int(g.cap.get(4))
            writer = cv2.VideoWriter(args.save, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
        threading.Thread(target=g.run, args=(writer if not g.live else None,), daemon=True).start()

    if state["date"] != today():
        new_day()
    publish = None
    if LIVE and not args.no_web:
        try:
            publish = web(args)
        except Exception as e:  # no paho-mqtt, no network: count without the phone page
            print("phone page off:", e, flush=True)

    if not args.nogui:  # resizable: the 1920-px mosaic doesn't fit a display-scaled laptop screen
        cv2.namedWindow(WIN, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)
        cv2.resizeWindow(WIN, 1280, 460)
    last_log, last_pub, armed = time.time(), 0, ""
    while not all(g.done for g in gates):
        if time.time() - last_log >= 60:
            last_log = time.time()
            log_counts()
            if state["date"] != today():
                new_day()
        if publish and time.time() - last_pub >= 2:
            last_pub = time.time()
            try:
                publish()
            except Exception as e:
                print("phone page off:", e, flush=True)
                publish = None
        total_in = sum(g.n_in for g in gates)
        total_out = sum(g.n_out for g in gates)
        if args.nogui:
            time.sleep(0.2)
            continue
        h = 540  # a gate with no picture yet gets a black tile, so a stall is visible, not a blank window
        row = cv2.hconcat([np.zeros((h, h * 16 // 9, 3), np.uint8) if g.view is None else
                           cv2.resize(g.view, (int(g.view.shape[1] * h / g.view.shape[0]), h)) for g in gates])
        banner = row[:150].copy()
        banner[:] = (20, 20, 20)
        # inside = in - out: staff walking in and out cancel, only people who stay count
        inside = total_in - total_out
        left = args.capacity - inside
        colour = (0, 0, 255) if left <= 0 else (0, 165, 255) if left <= args.capacity // 10 else (0, 255, 0)
        status = "HOUSE FULL" if left <= 0 else f"{left} left"
        if armed:
            status = "RESET? press y" if armed == "r" else "UNDO LAST RESET? press y"
        stuck = [g.label for g in gates if not g.done and time.time() - g.seen > 5]
        if stuck:  # a frozen picture looks like a quiet gate, so say it loudly
            status, colour = "NO VIDEO: " + ", ".join(stuck) + " - NOT COUNTING", (0, 0, 255)
        s = row.shape[1] / 1200
        cv2.putText(banner, f"INSIDE {inside} / {args.capacity}   {status}",
                    (20, 62), cv2.FONT_HERSHEY_SIMPLEX, s, colour, 4)
        per_gate = "    ".join(f"{g.label}: {g.n_in - g.n_out} (in {g.n_in}, out {g.n_out})" for g in gates)
        cv2.putText(banner, f"{per_gate}    TOTAL: {inside} (in {total_in}, out {total_out})"
                            f"    TODAY: {today_total()}",
                    (20, 125), cv2.FONT_HERSHEY_SIMPLEX, s * 0.55, (255, 255, 255), 2)
        cv2.imshow(WIN, cv2.vconcat([banner, row]))
        k = cv2.waitKey(30) & 0xFF
        if k == ord("q"):
            break
        if k in (ord("r"), ord("u")):  # both need y next, so a stray key can't change the count
            armed = chr(k)
        elif k == ord("y") and armed:
            if armed == "r":
                reset()
            else:
                undo_reset()
            armed = ""
        elif k == ord("l"):
            for g in gates:
                if g.view is not None:
                    g.line = pick_line(g.view, g.name)
                    g.line_file.write_text(json.dumps(g.line))
        elif k != 255:
            armed = ""
    for g in gates:
        g.done = True
    time.sleep(0.5)
    if writer is not None:
        writer.release()
    print(f"FINAL entered={sum(g.n_in for g in gates)} exited={sum(g.n_out for g in gates)}")


if __name__ == "__main__":
    main()
