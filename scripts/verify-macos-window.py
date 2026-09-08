"""Launch an existing Mac release and capture only its window on an ephemeral CI runner.

No model settings, document input, system permission changes, or security bypasses.
Window metadata API: https://developer.apple.com/documentation/coregraphics/cgwindowlistcopywindowinfo(_:_:)
Screenshots still require visual inspection; a process or window alone is not UI acceptance.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time


def main() -> int:
    if sys.platform != "darwin":
        raise SystemExit("This check requires a macOS GUI session")
    import Quartz

    app = Path(sys.argv[1]).resolve()
    output = Path(sys.argv[2]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    binary = app / "Contents" / "MacOS" / "WenLint"
    if not binary.is_file():
        raise SystemExit("Published app executable missing")
    report: dict[str, object] = {"app": str(app), "window_found": False, "screenshot_created": False}
    with (output / "application.log").open("wb") as log:
        process = subprocess.Popen([str(binary)], stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"Application exited before window capture: {process.returncode}")
                windows = Quartz.CGWindowListCopyWindowInfo(
                    Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID
                ) or []
                candidates = [w for w in windows
                              if w.get("kCGWindowOwnerName") == "WenLint"
                              and w.get("kCGWindowLayer") == 0
                              and w.get("kCGWindowBounds", {}).get("Width", 0) >= 800]
                if len(candidates) == 1:
                    window = candidates[0]
                    report.update(window_found=True, window_id=int(window["kCGWindowNumber"]),
                                  bounds=dict(window["kCGWindowBounds"]))
                    time.sleep(5)
                    image = output / "window.png"
                    captured = subprocess.run(
                        ["/usr/sbin/screencapture", "-x", "-l", str(report["window_id"]), str(image)],
                        capture_output=True, text=True, timeout=15,
                    )
                    if captured.returncode or not image.exists() or image.stat().st_size < 1000:
                        raise RuntimeError(f"Window capture unavailable: {captured.stderr.strip()}")
                    report["screenshot_created"] = True
                    return 0
                time.sleep(1)
            raise RuntimeError("No unique visible WenLint window in the runner GUI session")
        except Exception as exc:
            report["error"] = str(exc)
            return 1
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            (output / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(report))


if __name__ == "__main__":
    raise SystemExit(main())
