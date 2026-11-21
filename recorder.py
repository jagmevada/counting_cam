"""Record both gates' camera video, for training data and for replaying the counter.

    python recorder.py                    both gates, both streams, 15:45 to 23:59 every day
    python recorder.py --start 16:30 --until 22:00 --streams 1

Leave it running: it records between --start and --until each day and waits in between.
ffmpeg copies the cameras' own H.265 video straight to disk (no re-encoding, almost no CPU),
a new .mkv per gate and stream every 10 minutes, named by its start time:
    recordings/<date>/gate1_sub_<HHMMSS>.mkv     1280x720, exactly what the counter sees
    recordings/<date>/gate1_main_<HHMMSS>.mkv    2560x1440
About 3.5 GB per hour for both gates with both streams (measured 2026-11-21), so about 29 GB
for a 15:45 to 23:59 day. It ends for good when the disk has less than --min-free GB left;
Ctrl+C stops it earlier. A stream that drops is restarted within 5 s.
Replay a file: python counter.py <file.mkv> --nogui --line x1,y1,x2,y2,ix,iy
"""
import argparse
import shutil
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

# ponytail: reusing counter's camera list and password lookup also loads torch (~0.5 GB RAM
# for this process). Move them to a small shared module if that ever matters.
from counter import CAMERAS, HERE, cam_pass


def record(out, end, args):
    """Records every stream into `out` until `end`. Returns False when the disk is nearly full."""
    out.mkdir(parents=True, exist_ok=True)
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

    def room():
        return shutil.disk_usage(out).free > args.min_free * 2**30

    print(time.strftime("%H:%M:%S"), f"recording {', '.join(jobs)} to {out} until {end:%H:%M}", flush=True)
    last = time.time()
    try:
        while datetime.now() < end and room():
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
    finally:  # also on Ctrl+C: never leave an ffmpeg running on its own
        for _, p in jobs.values():
            if p is not None and p.poll() is None:
                try:
                    p.communicate(b"q", timeout=10)  # ffmpeg closes its file cleanly on q
                except (subprocess.TimeoutExpired, OSError):
                    p.kill()
        print(time.strftime("%H:%M:%S"), f"stopped. {size_gb():.1f} GB in {out}", flush=True)
    return room()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="15:45", help="start time each day, HH:MM")
    # ponytail: one window per calendar day, so a show that runs past midnight is cut at 23:59. If that
    # happens, run a second recorder with --start 00:00 --until 01:00.
    ap.add_argument("--until", default="23:59", help="stop time each day, HH:MM")
    ap.add_argument("--streams", default="1,0", help="1 = sub (720p), 0 = main (1440p)")
    ap.add_argument("--minutes", type=int, default=10, help="length of each file")
    ap.add_argument("--min-free", type=float, default=20, help="end when the disk has fewer GB free")
    ap.add_argument("--out", default=str(HERE / "recordings"))
    args = ap.parse_args()
    start, until = (datetime.strptime(t, "%H:%M").time() for t in (args.start, args.until))
    try:
        while True:
            now = datetime.now()
            begin, end = datetime.combine(now.date(), start), datetime.combine(now.date(), until)
            if now >= end:  # today's window is over: wait for tomorrow's
                begin += timedelta(days=1)
            if now < begin:
                print(time.strftime("%H:%M:%S"), f"waiting until {begin:%Y-%m-%d %H:%M}", flush=True)
                while datetime.now() < begin:
                    time.sleep(20)
                continue
            if not record(Path(args.out) / time.strftime("%Y-%m-%d"), end, args):
                print(time.strftime("%H:%M:%S"), f"less than {args.min_free:g} GB free: recording ended", flush=True)
                return
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
