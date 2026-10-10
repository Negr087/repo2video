"""Link de GitHub -> video vertical explicativo.

    python pipeline.py https://github.com/usuario/repo [salida.mp4]
"""
import json
import sys
from pathlib import Path

import storyboard
from github_summary import fetch_summary
from render import render_video


def run(url_text: str, out_dir: Path, status=lambda msg: None, llm=storyboard.call_ollama) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    status("Leyendo el repo...")
    info = fetch_summary(url_text)
    status("Escribiendo el guion (con el modelo local, tarda unos minutos)...")
    sb = storyboard.generate(info, llm=llm)
    (out_dir / "guion.json").write_text(json.dumps(sb, ensure_ascii=False, indent=2), encoding="utf-8")
    status("Armando el video...")
    mp4 = out_dir / "video.mp4"
    seconds = render_video(sb, mp4)
    return {"video": mp4, "guion": out_dir / "guion.json", "info": info, "segundos": seconds}


if __name__ == "__main__":
    out = Path(sys.argv[2]).parent if len(sys.argv) > 2 else Path("salida")
    r = run(sys.argv[1], out, status=print)
    print("Listo:", r["video"], f"({r['segundos']:.0f} s)")
