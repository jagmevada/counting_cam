"""Record both gates' camera video, for training data and for replaying the counter.

    python recorder.py                    both gates, both streams, until 23:30 today
    python recorder.py --until 22:00 --streams 1

ffmpeg copies the cameras' own H.265 video straight to disk (no re-encoding, almost no CPU),
a new .mkv per gate and stream every 10 minutes, named by its start time:
    recordings/<date>/gate1_sub_<HHMMSS>.mkv     1280x720, exactly what the counter sees
    recordings/<date>/gate1_main_<HHMMSS>.mkv    2560x1440
About 3.8 GB per hour for both gates with both streams (measured 2026-11-21).
Stops by itself at --until, or when the disk has less than --min-free GB left; Ctrl+C stops
it earlier. A stream that drops is restarted within 5 s.
Replay a file: python counter.py <file.mkv> --nogui --line x1,y1,x2,y2,ix,iy
"""
import argparse
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

# ponytail: reusing counter's camera list and password lookup also loads torch (~0.5 GB RAM
# for this process). Move them to a small shared module if that ever matters.
from counter import CAMERAS, HERE, cam_pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--until", default="23:30", help="stop time today, HH:MM")
    ap.add_argument("--streams", default="1,0", help="1 = sub (720p), 0 = main (1440p)")
    ap.add_argument("--minutes", type=int, default=10, help="length of each file")
    ap.add_argument("--min-free", type=float, default=20, help="stop when the disk has fewer GB free")
    ap.add_argument("--out", default=str(HERE / "recordings"))
    args = ap.parse_args()

    out = Path(args.out) / time.strftime("%Y-%m-%d")
    out.mkdir(parents=True, exist_ok=True)
    end = datetime.combine(datetime.now().date(), datetime.strptime(args.until, "%H:%M").time())
    pw = quote(cam_pass(), safe="")
    jobs = {}  # name -> [ffmpeg command, running process]
    for ip, label in CAMERAS.items():
        for sub in args.streams.split(","):
            name = f"{label.lower().replace(' ', '')}_{'sub' if sub == '1' else 'main'}"
            # ponytail: the password sits in ffmpeg's command line, visible to other programs on
            # this laptop while it runs. Fine on the owner's own machine.
            jobs[name] = [["ffmpeg", "-hide_banner", "-loglevel", "error", "-rtsp_transport", "tcp",
                           "-timeout", "10000000",  # 10 s of silence = give up, so a dead stream gets restarted
                           "-use_wallclock_as_timestamps", "1",
                           "-i", f"rtsps://admin:{pw}@{ip}:554/video/live?channel=1&subtype={sub}",
                           "-map", "0:v:0", "-c", "copy",  # video only: no audio is kept
                           "-f", "segment", "-segment_time", str(args.minutes * 60), "-segment_atclocktime", "1",
                           "-reset_timestamps", "1", "-strftime", "1", str(out / f"{name}_%H%M%S.mkv")], None]

    def size_gb():
        return sum(f.stat().st_size for f in out.glob("*.mkv")) / 2**30

    print(f"recording {', '.join(jobs)} to {out} until {args.until}", flush=True)
    last = time.time()
    try:
        while datetime.now() < end and shutil.disk_usage(out).free > args.min_free * 2**30:
            for name, job in jobs.items():
                if job[1] is None or job[1].poll() is not None:
                    if job[1] is not None:
                        print(time.strftime("%H:%M:%S"), name, "stopped, restarting", flush=True)
                    job[1] = subprocess.Popen(job[0], stdin=subprocess.PIPE)
            if time.time() - last >= 600:
                last = time.time()
                print(time.strftime("%H:%M:%S"), f"{size_gb():.1f} GB written,",
                      f"{shutil.disk_usage(out).free / 2**30:.0f} GB free", flush=True)
            time.sleep(5)
    except KeyboardInterrupt:
        pass
    for _, p in jobs.values():
        if p is not None and p.poll() is None:
            try:
                p.communicate(b"q", timeout=10)  # ffmpeg closes its file cleanly on q
            except (subprocess.TimeoutExpired, OSError):
                p.kill()
    print(time.strftime("%H:%M:%S"), f"stopped. {size_gb():.1f} GB in {out}", flush=True)


if __name__ == "__main__":
    main()
