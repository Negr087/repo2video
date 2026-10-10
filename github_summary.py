"""Convierte un link de GitHub en un resumen corto (unos 1900 caracteres) que un
modelo local pueda leer rapido: descripcion, README limpio, dependencias,
servicios Docker y estructura de carpetas.

Usa la API de GitHub (60 consultas/hora sin token; poné GITHUB_TOKEN para mas) y
cae a raw.githubusercontent.com si la API no responde."""
import json
import os
import re
import urllib.error
import urllib.request

UA = "repo2video-bot"
TOKEN = os.getenv("GITHUB_TOKEN")
MAX_SUMMARY_CHARS = int(os.getenv("MAX_SUMMARY_CHARS", "1900"))

KEY_FILES = ["package.json", "requirements.txt", "pyproject.toml", "go.mod", "Cargo.toml",
             "docker-compose.yml", "docker-compose.yaml", "compose.yml", "Dockerfile"]
IGNORE_TOP = re.compile(r"^(\.|license|licence|changelog|code_of_conduct|contributing|security|"
                        r".*lock.*|node_modules|dist|build|__pycache__|\.github)", re.I)
SECTION_RX = re.compile(r"(feature|how it works|architecture|overview|usage|what is|about|"
                        r"caracter|funciona|arquitectura|uso|acerca)", re.I)


class RepoError(Exception):
    """Mensaje pensado para mostrarse al usuario."""


def parse_repo_url(text: str):
    m = re.search(r"github\.com[/:]([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", text or "")
    if not m:
        raise RepoError("No encontré un link de GitHub en el mensaje. Probá con "
                        "https://github.com/usuario/repo")
    owner, repo = m.group(1), m.group(2)
    repo = re.sub(r"\.git$", "", repo)
    return owner, repo


def _req(url, timeout=20):
    headers = {"User-Agent": UA}
    if TOKEN and "api.github.com" in url:
        headers["Authorization"] = f"Bearer {TOKEN}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                    timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception:
        return 0, b""


def _api_json(path):
    status, body = _req("https://api.github.com" + path)
    if status == 200:
        try:
            return status, json.loads(body)
        except ValueError:
            pass
    return status, None


# ---------- limpieza del README ----------

def clean_markdown(md: str) -> str:
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S)
    md = re.sub(r"```.*?```", "", md, flags=re.S)
    md = re.sub(r"<[^>]+>", " ", md)
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md)
    md = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", md)
    md = re.sub(r"^\s*\|.*\|\s*$", "", md, flags=re.M)
    md = re.sub(r"^\s*[-=_*]{3,}\s*$", "", md, flags=re.M)
    md = re.sub(r"https?://\S+", "", md)
    md = re.sub(r"[`*>]", "", md)
    md = re.sub(r"[ \t]+", " ", md)
    return re.sub(r"\n{2,}", "\n", md).strip()


def readme_excerpt(md: str, budget: int) -> str:
    """Intro del README + hasta 2 secciones utiles (features, how it works...)."""
    sections, cur_title, cur = [], "", []
    for line in clean_markdown(md).splitlines():
        h = re.match(r"^#{1,4}\s+(.*)", line)
        if h:
            sections.append((cur_title, " ".join(cur)))
            cur_title, cur = h.group(1).strip(), []
        elif line.strip():
            cur.append(line.strip())
    sections.append((cur_title, " ".join(cur)))
    intro = next((t for _, t in sections if t), "")
    parts = [intro[: int(budget * 0.55)]]
    extra = [f"{t}: {b}" for t, b in sections[1:] if b and SECTION_RX.search(t)][:2]
    left = budget - len(parts[0])
    for e in extra:
        parts.append(e[: max(0, min(left // 2, 350))])
    return " | ".join(p for p in parts if p)


# ---------- dependencias y estructura ----------

def _deps(name, text):
    try:
        if name == "package.json":
            d = json.loads(text)
            return list((d.get("dependencies") or {}).keys())[:14]
        if name == "requirements.txt":
            return [m.group(0) for l in text.splitlines()
                    if (m := re.match(r"^[A-Za-z0-9_.-]+", l.strip()))][:14]
        if name == "pyproject.toml":
            block = re.search(r"dependencies\s*=\s*\[(.*?)\]", text, re.S)
            return re.findall(r"[\"']([A-Za-z0-9_.-]+)", block.group(1))[:14] if block else []
        if name == "go.mod":
            return [m.group(1).split("/")[-1] for m in
                    re.finditer(r"^\s*([\w./-]+\.[\w./-]+)\s+v", text, re.M)][:12]
        if name == "Cargo.toml":
            block = re.search(r"\[dependencies\](.*?)(?:\n\[|\Z)", text, re.S)
            return re.findall(r"^([A-Za-z0-9_-]+)\s*=", block.group(1), re.M)[:14] if block else []
    except Exception:
        pass
    return []


def _compose(text):
    services = re.findall(r"^  ([A-Za-z0-9_-]+):\s*$", text, re.M)
    images = re.findall(r"image:\s*([\w./:-]+)", text)
    return services[:10], images[:6]


def _structure(paths):
    top = []
    for p, t in paths:
        if "/" in p or IGNORE_TOP.match(p):
            continue
        top.append(p + ("/" if t == "tree" else ""))
    inner = []
    for d in ("src", "app", "lib", "packages", "apps", "services", "server", "backend", "frontend"):
        kids = sorted({p.split("/")[1] for p, _ in paths
                       if p.startswith(d + "/") and p.count("/") >= 1})[:8]
        if kids:
            inner.append(f"{d}/ -> " + ", ".join(kids))
    return top[:18], inner[:3]


# ---------- principal ----------

def fetch_summary(url_text: str) -> dict:
    owner, repo = parse_repo_url(url_text)
    status, meta = _api_json(f"/repos/{owner}/{repo}")
    if status == 404:
        raise RepoError("No encontré ese repo. ¿Es privado o el link está mal escrito?")
    meta = meta or {}
    branch = meta.get("default_branch") or "HEAD"

    paths = []
    st, tree = _api_json(f"/repos/{owner}/{repo}/git/trees/{branch}?recursive=1")
    if tree:
        paths = [(t["path"], t["type"]) for t in tree.get("tree", [])
                 if t["type"] in ("blob", "tree") and t["path"].count("/") <= 2]
    root = {p for p, _ in paths if "/" not in p}

    def raw(path):
        s, b = _req(f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}")
        return b.decode("utf-8", "replace") if s == 200 else None

    readme = None
    names = [p for p in root if re.match(r"^readme(\.\w+)?$", p, re.I)] if root else []
    for n in names or ["README.md", "Readme.md", "readme.md", "README.rst", "README.markdown", "README"]:
        readme = raw(n)
        if readme:
            break
    if not readme and not meta:
        raise RepoError("No pude leer el repo (puede ser privado, o GitHub me limitó las "
                        "consultas). Probá de nuevo en un rato.")

    files = {}
    for k in KEY_FILES:
        if root and k not in root:
            continue
        txt = raw(k)
        if txt:
            files[k] = txt

    deps = []
    for k in ("package.json", "requirements.txt", "pyproject.toml", "go.mod", "Cargo.toml"):
        if k in files:
            deps += _deps(k, files[k])
    services, images = [], []
    for k in ("docker-compose.yml", "docker-compose.yaml", "compose.yml"):
        if k in files:
            services, images = _compose(files[k])
            break
    top, inner = _structure(paths)

    desc = (meta.get("description") or "").strip()
    lines = [f"Repo: {owner}/{repo}"]
    if desc:
        lines.append(f"Descripcion: {desc}")
    lang = meta.get("language")
    topics = ", ".join(meta.get("topics") or [])
    if lang or topics:
        lines.append("Lenguaje: " + (lang or "?") + (f". Temas: {topics}" if topics else ""))
    tail = []
    if deps:
        tail.append("Dependencias: " + ", ".join(dict.fromkeys(deps)))
    if services:
        tail.append("Servicios Docker: " + ", ".join(services)
                    + (f" (imagenes: {', '.join(images)})" if images else ""))
    elif "Dockerfile" in files:
        tail.append("Usa Docker.")
    if top:
        tail.append("Estructura: " + ", ".join(top) + ((" | " + " | ".join(inner)) if inner else ""))
    fixed = "\n".join(lines + tail)
    budget = max(300, MAX_SUMMARY_CHARS - len(fixed) - 12)
    body = readme_excerpt(readme, budget) if readme else ""
    summary = "\n".join(lines + ([f"README: {body}"] if body else []) + tail)
    return {"owner": owner, "repo": repo, "name": repo, "description": desc,
            "url": f"https://github.com/{owner}/{repo}", "summary": summary[:MAX_SUMMARY_CHARS + 200]}


if __name__ == "__main__":
    import sys
    info = fetch_summary(sys.argv[1])
    print(info["summary"])
    print(f"\n[{len(info['summary'])} caracteres]")
