"""Renderiza un storyboard (JSON) como video vertical 720x1280.

    python render.py guion.json salida.mp4
    python render.py guion.json salida.mp4 --frames 1,5,9   # solo capturas PNG de esos segundos
"""
import json
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "template.html"
W, H = 720, 1280


def _open(p, storyboard):
    browser = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
    page = browser.new_page(viewport={"width": W, "height": H})
    page.goto(TEMPLATE.as_uri())
    page.evaluate("sb => init(sb)", storyboard)
    page.evaluate("document.fonts.ready.then(() => true)")
    return browser, page


def render_video(storyboard: dict, out: Path, fps: int = 30) -> float:
    """Genera el mp4 (sin audio). Devuelve la duracion en segundos."""
    with sync_playwright() as p:
        browser, page = _open(p, storyboard)
        total = page.evaluate("window.TOTAL")
        ff = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(fps),
             "-c:v", "mjpeg", "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)],
            stdin=subprocess.PIPE)
        for i in range(int(total * fps) + 1):
            page.evaluate("t => seek(t)", i / fps)
            ff.stdin.write(page.screenshot(type="jpeg", quality=92))
        ff.stdin.close()
        ff.wait()
        browser.close()
    return total


def render_frames(storyboard: dict, seconds, outdir: Path):
    outdir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser, page = _open(p, storyboard)
        print("duracion total:", round(page.evaluate("window.TOTAL"), 1), "s")
        for t in seconds:
            page.evaluate("t => seek(t)", t)
            page.screenshot(path=str(outdir / f"f_{t:05.1f}.png"))
        browser.close()


if __name__ == "__main__":
    sb = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if "--frames" in sys.argv:
        secs = [float(x) for x in sys.argv[sys.argv.index("--frames") + 1].split(",")]
        render_frames(sb, secs, Path(sys.argv[2]))
    else:
        d = render_video(sb, Path(sys.argv[2]))
        print(f"Listo: {sys.argv[2]} ({d:.1f} s)")
