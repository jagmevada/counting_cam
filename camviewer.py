"""Two-camera live viewer for the CP Plus cameras on the PoE switch.

Run:  python C:\\Users\\Administrator\\camviewer\\camviewer.py
Type the camera username/password in the window and press Connect.
"""
import os
import threading
import time
import tkinter as tk
from tkinter import ttk
from urllib.parse import quote

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS",
                      "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay")
import cv2  # noqa: E402
from PIL import Image, ImageTk  # noqa: E402

CAMERAS = [("Cam 1", "192.168.1.251"), ("Cam 2", "192.168.1.252")]
SUBTYPE = 1  # 0 = main stream (full res), 1 = sub stream (lighter)
TILE_W, TILE_H = 640, 360  # display size per tile


class Feed(threading.Thread):
    def __init__(self, ip):
        super().__init__(daemon=True)
        self.ip, self.url, self.frame = ip, None, None
        self.status, self.running = "idle", True

    def run(self):
        while self.running:
            if not self.url:
                time.sleep(0.2)
                continue
            cap = None
            # Plain RTSP first (works once "RTSP over TLS" is off), then RTSPS.
            for scheme in ("rtsp", "rtsps"):
                url = self.url.replace("rtsps://", "rtsp://", 1)
                if scheme == "rtsps":
                    url = url.replace("rtsp://", "rtsps://", 1)
                self.status = f"connecting ({scheme})..."
                cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG, [
                    cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 8000,
                    cv2.CAP_PROP_READ_TIMEOUT_MSEC, 8000,
                    cv2.CAP_PROP_HW_ACCELERATION, cv2.VIDEO_ACCELERATION_ANY])
                if cap.isOpened():
                    break
                cap.release()
            if not cap.isOpened():
                self.status = "cannot open stream (check login)"
                time.sleep(3)
                continue
            fcc = int(cap.get(cv2.CAP_PROP_FOURCC))
            codec = "".join(chr((fcc >> 8 * i) & 0xFF) for i in range(4))
            print(self.ip, "codec", codec, "hw", cap.get(cv2.CAP_PROP_HW_ACCELERATION),
                  "cam fps", cap.get(cv2.CAP_PROP_FPS), flush=True)
            self.status = f"live {scheme}/TCP"
            n, t0 = 0, time.time()
            while self.running and self.url:
                ok, img = cap.read()
                if not ok:
                    self.status = "stream lost, reconnecting..."
                    break
                # Resize here (decoder thread, fast cv2) so the Tk thread only blits.
                small = cv2.resize(img, (TILE_W, TILE_H), interpolation=cv2.INTER_AREA)
                self.frame = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
                n += 1
                if time.time() - t0 >= 2:
                    h, w = img.shape[:2]
                    self.status = f"live {scheme}/TCP  {w}x{h}  {n / (time.time() - t0):.1f} fps"
                    print(self.ip, self.status, flush=True)
                    n, t0 = 0, time.time()
            cap.release()
            time.sleep(1)


class App:
    def __init__(self, root):
        self.root = root
        root.title("Camera Viewer")
        root.configure(bg="#111")
        bar = ttk.Frame(root, padding=6)
        bar.pack(fill="x")
        ttk.Label(bar, text="User").pack(side="left")
        self.user = ttk.Entry(bar, width=12)
        self.user.insert(0, "admin")
        self.user.pack(side="left", padx=4)
        ttk.Label(bar, text="Password").pack(side="left")
        self.pwd = ttk.Entry(bar, width=16, show="*")
        self.pwd.pack(side="left", padx=4)
        self.pwd.bind("<Return>", lambda e: self.connect())
        self.stream = tk.StringVar(value="Sub (smooth)")
        ttk.Combobox(bar, textvariable=self.stream, width=14, state="readonly",
                     values=["Sub (smooth)", "Main (HD)"]).pack(side="left", padx=4)
        ttk.Button(bar, text="Connect", command=self.connect).pack(side="left", padx=4)

        grid = tk.Frame(root, bg="#111")
        grid.pack(fill="both", expand=True)
        self.feeds, self.views, self.labels = [], [], []
        for i, (name, ip) in enumerate(CAMERAS):
            cell = tk.Frame(grid, bg="#111")
            cell.grid(row=0, column=i, padx=4, pady=4)
            lbl = tk.Label(cell, text=f"{name}  {ip}  idle", fg="#ddd", bg="#111")
            lbl.pack(anchor="w")
            # Blank image so an empty tile is sized in pixels, not text characters.
            view = tk.Label(cell, bg="#000", bd=0)
            view.imgtk = ImageTk.PhotoImage(Image.new("RGB", (TILE_W, TILE_H)))
            view.config(image=view.imgtk)
            view.pack()
            f = Feed(ip)
            f.start()
            self.feeds.append(f)
            self.views.append(view)
            self.labels.append(lbl)
        root.protocol("WM_DELETE_WINDOW", self.close)
        # Auto-connect if the user saved their password in the CAM_PASS env var.
        saved = os.environ.get("CAM_PASS")
        if not saved:  # setx writes HKCU\Environment; already-running shells don't see it
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                    saved = winreg.QueryValueEx(k, "CAM_PASS")[0]
            except OSError:
                pass
        if saved:
            self.pwd.insert(0, saved)
            self.connect()
        self.tick()

    def connect(self):
        u, p = quote(self.user.get(), safe=""), quote(self.pwd.get(), safe="")
        sub = 1 if self.stream.get().startswith("Sub") else 0
        for f in self.feeds:
            # These cameras only accept RTSP over TLS (rtsps) on port 554.
            f.url = (f"rtsps://{u}:{p}@{f.ip}:554/video/live"
                     f"?channel=1&subtype={sub}")

    def tick(self):
        for (name, ip), f, view, lbl in zip(CAMERAS, self.feeds, self.views, self.labels):
            lbl.config(text=f"{name}  {ip}  {f.status}")
            if f.frame is not None:
                img = Image.fromarray(f.frame)
                view.imgtk = ImageTk.PhotoImage(img)
                view.config(image=view.imgtk)
        self.root.after(40, self.tick)

    def close(self):
        for f in self.feeds:
            f.running = False
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
