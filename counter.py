"""Dome entry counter: people crossing a line at each gate, total = sum of gates.

Live:  python counter.py 192.168.1.251 192.168.1.252
Clip:  python counter.py clip.mp4 --save out.mp4 [--line x1,y1,x2,y2,ix,iy] [--nogui]

Line setup (first run per source): click 2 points for the line, then 1 point on the
INSIDE (dome) side. Saved to line_<name>.json. Keys: l = redraw line, r then y = reset,
q = quit. Live totals persist in counts.json; per-minute rows go to counts.csv.
"""
import argparse
import csv
import json
import os
import threading
import time
from pathlib import Path
from urllib.parse import quote

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS",
                      "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay")
import cv2  # noqa: E402
from ultralytics import YOLO  # noqa: E402

HERE = Path(__file__).parent
COUNTS = HERE / "counts.json"
LOG = HERE / "counts.csv"
lock = threading.Lock()


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
    (x1, y1), (x2, y2) = line[0], line[1]
    return (x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)


class Gate:
    def __init__(self, src, args, totals):
        self.src, self.args = src, args
        self.name = src if is_ip(src) else Path(src).stem
        self.live = is_ip(src)
        self.url = (f"rtsps://admin:{quote(cam_pass(), safe='')}@{src}:554/video/live"
                    f"?channel=1&subtype={args.subtype}") if self.live else src
        t = totals.get(self.name, {})
        self.n_in, self.n_out = t.get("in", 0), t.get("out", 0)
        self.line_file = HERE / f"line_{self.name}.json"
        self.line = json.loads(self.line_file.read_text()) if self.line_file.exists() else None
        if args.line:
            v = [int(a) for a in args.line.split(",")]
            self.line = [v[0:2], v[2:4], v[4:6]]
        self.model = YOLO(args.model)  # one model per gate = separate tracker state
        self.cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
        self.latest, self.view, self.fps, self.done = None, None, 0.0, False
        self.sides, self.went_in, self.went_out = {}, set(), set()

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
        inside_sign = side(self.line, *self.line[2]) > 0
        s = (side(self.line, x, y) > 0) == inside_sign  # True = inside
        prev = self.sides.get(tid)
        self.sides[tid] = s
        if prev is None or prev == s:
            return
        # ponytail: each track counted at most once per direction, absorbs jitter on the line
        if s and tid not in self.went_in:
            self.went_in.add(tid)
            self.n_in += 1
        elif not s and tid not in self.went_out:
            self.went_out.add(tid)
            self.n_out += 1
        else:
            return
        save_totals()

    def run(self, writer=None):
        n, t0 = 0, time.time()
        while not self.done:
            f = self.next_frame()
            if f is None:
                break
            r = self.model.track(f, persist=True, classes=[0], imgsz=self.args.imgsz,
                                 conf=self.args.conf, verbose=False)[0]
            if r.boxes.id is not None and self.line:
                for (x1, y1, x2, y2), tid in zip(r.boxes.xyxy.tolist(), r.boxes.id.int().tolist()):
                    # ponytail: box centre; switch to top-centre (head) if mount is very steep
                    self.count(tid, (x1 + x2) / 2, (y1 + y2) / 2)
            v = r.plot(labels=False, line_width=2)
            if self.line:
                cv2.line(v, tuple(self.line[0]), tuple(self.line[1]), (0, 255, 255), 3)
                cv2.circle(v, tuple(self.line[2]), 8, (0, 255, 0), -1)
            cv2.putText(v, f"{self.name}  IN {self.n_in}  OUT {self.n_out}  {self.fps:.0f}fps",
                        (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 255, 0), 3)
            self.view = v
            if writer is not None:
                writer.write(v)
            n += 1
            if time.time() - t0 >= 2:
                self.fps, n, t0 = n / (time.time() - t0), 0, time.time()
                print(f"{self.name}: in={self.n_in} out={self.n_out} fps={self.fps:.1f}", flush=True)
        self.done = True


gates = []


def save_totals():
    with lock:
        COUNTS.write_text(json.dumps({g.name: {"in": g.n_in, "out": g.n_out} for g in gates}))


def pick_line(frame, name):
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
    return pts


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
    ap.add_argument("sources", nargs="+", help="camera IPs or video files")
    ap.add_argument("--model", default="yolo11s.pt")
    ap.add_argument("--imgsz", type=int, default=960)
    ap.add_argument("--conf", type=float, default=0.3)
    ap.add_argument("--subtype", type=int, default=0, help="0 main (4MP), 1 sub")
    ap.add_argument("--line", help="x1,y1,x2,y2,ix,iy (skip clicking)")
    ap.add_argument("--save", help="write annotated video (single file source)")
    ap.add_argument("--nogui", action="store_true")
    args = ap.parse_args()

    live = all(is_ip(s) for s in args.sources)
    totals = json.loads(COUNTS.read_text()) if live and COUNTS.exists() else {}
    for s in args.sources:
        g = Gate(s, args, totals)
        if not g.line or (not args.nogui and not g.line_file.exists() and not args.line):
            g.line = pick_line(first_frame(g), g.name)
            g.line_file.write_text(json.dumps(g.line))
        gates.append(g)

    writer = None
    for g in gates:
        if g.live:
            threading.Thread(target=g.grab, daemon=True).start()
        elif args.save:
            fps = g.cap.get(cv2.CAP_PROP_FPS) or 25
            w, h = int(g.cap.get(3)), int(g.cap.get(4))
            writer = cv2.VideoWriter(args.save, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
        threading.Thread(target=g.run, args=(writer if not g.live else None,), daemon=True).start()

    last_log, armed_reset = time.time(), False
    while not all(g.done for g in gates):
        if time.time() - last_log >= 60 and live:
            last_log = time.time()
            new = not LOG.exists()
            with LOG.open("a", newline="") as fh:
                w = csv.writer(fh)
                if new:
                    w.writerow(["time", "gate", "in", "out"])
                for g in gates:
                    w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), g.name, g.n_in, g.n_out])
        total_in = sum(g.n_in for g in gates)
        total_out = sum(g.n_out for g in gates)
        if args.nogui:
            time.sleep(0.2)
            continue
        views = [g.view for g in gates if g.view is not None]
        if views:
            h = 540
            row = cv2.hconcat([cv2.resize(v, (int(v.shape[1] * h / v.shape[0]), h)) for v in views])
            banner = row[:90].copy()
            banner[:] = (20, 20, 20)
            cv2.putText(banner, f"TOTAL ENTERED {total_in}   (exited {total_out}, inside ~{total_in - total_out})",
                        (20, 62), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 255, 255), 4)
            cv2.imshow("Dome entry counter", cv2.vconcat([banner, row]))
        k = cv2.waitKey(30) & 0xFF
        if k == ord("q"):
            break
        if k == ord("r"):
            armed_reset = True
            print("Reset all counts? press y", flush=True)
        elif k == ord("y") and armed_reset:
            for g in gates:
                g.n_in = g.n_out = 0
                g.went_in.clear()
                g.went_out.clear()
            save_totals()
            armed_reset = False
        elif k == ord("l"):
            for g in gates:
                if g.view is not None:
                    g.line = pick_line(g.view, g.name)
                    g.line_file.write_text(json.dumps(g.line))
        elif k != 255:
            armed_reset = False
    for g in gates:
        g.done = True
    time.sleep(0.5)
    if writer is not None:
        writer.release()
    print(f"FINAL entered={sum(g.n_in for g in gates)} exited={sum(g.n_out for g in gates)}")


if __name__ == "__main__":
    main()
