"""Guion del video: arma el prompt, llama a Ollama y valida/repara la respuesta para
que el renderizador siempre reciba algo coherente (aunque el modelo se equivoque)."""
import json
import os
import re
import urllib.request

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

PROMPT = """Sos guionista de videos cortos que explican como funciona un proyecto de GitHub. Con el RESUMEN de abajo (puede estar en ingles), devolve SOLO un JSON valido, escrito en espanol, con este formato:
{"titulo":"nombre","escenas":[
{"tipo":"titulo","subtitulo":"que hace, en una frase","narracion":"..."},
{"tipo":"diagrama","titulo":"Como esta armado","nodos":["..."],"conexiones":[["origen","destino"]],"narracion":"..."},
{"tipo":"flujo","titulo":"Que pasa cuando...","pasos":["..."],"narracion":"..."},
{"tipo":"stack","titulo":"Tecnologias","items":["..."],"narracion":"..."}]}
Reglas: usa SOLO nombres que aparecen en el resumen, sin inventar. Etiquetas de hasta 3 palabras. 4 a 7 nodos y 4 a 6 pasos. El flujo va de lo que hace el usuario a lo que obtiene. Narracion: 1 o 2 frases de hasta 25 palabras que expliquen, sin repetir las etiquetas.

RESUMEN DEL PROYECTO:
"""

GENERIC = {"usuario", "cliente", "servidor", "base", "datos", "api", "web", "app", "aplicacion",
           "interfaz", "navegador", "cola", "cache", "archivo", "archivos", "repositorio",
           "codigo", "modelo", "bot", "frontend", "backend", "servicio", "red", "proceso"}


class StoryboardError(Exception):
    pass


def call_ollama(prompt: str, timeout: int = 1500) -> str:
    body = json.dumps({
        "model": OLLAMA_MODEL, "prompt": prompt, "stream": False, "format": "json",
        "keep_alive": 0,  # descarga el modelo al terminar y libera la RAM para el render
        "options": {"temperature": 0.2, "num_ctx": 3072, "num_predict": 800},
    }).encode()
    req = urllib.request.Request(OLLAMA_URL + "/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["response"]


def _parse(text: str) -> dict:
    try:
        return json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise


def generate(info: dict, llm=call_ollama, retries: int = 1) -> dict:
    last = None
    for _ in range(retries + 1):
        try:
            return repair(_parse(llm(PROMPT + info["summary"])), info)
        except (ValueError, StoryboardError, KeyError, TypeError) as e:
            last = e
    raise StoryboardError(f"El modelo no devolvió un guion válido ({last}).")


# ---------- validacion / reparacion ----------

DANGLING = {"a", "al", "con", "de", "del", "el", "en", "la", "las", "los", "un", "una", "y", "o",
            "que", "para", "por", "su", "sus", "se", "es", "e", "u"}


def _trim_dangling(text):
    words = text.split(" ")
    while len(words) > 1 and words[-1].lower().strip(".,;:") in DANGLING:
        words.pop()
    return " ".join(words).rstrip(",;:")


def _s(x, maxlen):
    x = re.sub(r"\s+", " ", str(x or "")).strip()
    if len(x) <= maxlen:
        return x
    cut = x[:maxlen].rsplit(" ", 1)[0] if " " in x[:maxlen] else x[:maxlen]
    return _trim_dangling(cut)


def _narr(x, maxwords=28):
    words = re.sub(r"\s+", " ", str(x or "")).strip().split(" ")
    words = [w for w in words if w]
    if len(words) > maxwords:
        cut = " ".join(words[:maxwords])
        k = max(cut.rfind(". "), cut.rfind("; "), cut.rfind(", "))
        cut = cut[:k] if k > len(cut) * 0.5 else cut
        cut = _trim_dangling(cut).rstrip(".;:,")
        return cut + "."
    return " ".join(words)


def _tokens(label):
    return [t for t in re.findall(r"[a-z0-9áéíóúñü]+", label.lower()) if len(t) >= 3]


def _grounded(label, haystack, lenient):
    toks = _tokens(label)
    return any(t in haystack or (lenient and t in GENERIC) for t in toks)


def _dedupe(seq):
    out, seen = [], []
    for x in seq:
        k = re.sub(r"\W+", " ", x.lower()).strip()
        if not k or any(k == s or k.startswith(s) or s.startswith(k) for s in seen):
            continue
        seen.append(k)
        out.append(x)
    return out


def repair(sb: dict, info: dict) -> dict:
    if not isinstance(sb, dict) or not isinstance(sb.get("escenas"), list):
        raise StoryboardError("sin escenas")
    haystack = (info["summary"] + " " + info["name"]).lower()
    by = {}
    for e in sb["escenas"]:
        if isinstance(e, dict) and e.get("tipo") not in by:
            by[e.get("tipo")] = e
    pretty = re.sub(r"[-_]+", " ", info["name"]).strip()
    pretty = pretty[:1].upper() + pretty[1:] if pretty.islower() else pretty
    out = []

    t = by.get("titulo", {})
    out.append({"tipo": "titulo", "titulo": _s(pretty, 40),
                "subtitulo": _s(t.get("subtitulo") or info["description"], 70),
                "narracion": _narr(t.get("narracion") or info["description"])})

    d = by.get("diagrama")
    if d:
        nodes = _dedupe([_s(n, 28) for n in d.get("nodos", []) if isinstance(n, str)])
        nodes = [n for n in nodes if _grounded(n, haystack, True)][:7]
        if len(nodes) >= 3:
            low = {n.lower(): n for n in nodes}
            edges, seen = [], set()
            for c in d.get("conexiones", []):
                if isinstance(c, (list, tuple)) and len(c) == 2:
                    a, b = low.get(str(c[0]).lower()), low.get(str(c[1]).lower())
                    if a and b and a != b and (a, b) not in seen:
                        seen.add((a, b))
                        edges.append([a, b])
            out.append({"tipo": "diagrama", "titulo": _s(d.get("titulo") or "Cómo está armado", 36),
                        "nodos": nodes, "conexiones": edges, "narracion": _narr(d.get("narracion"))})

    f = by.get("flujo")
    if f:
        steps = _dedupe([_s(p, 70) for p in f.get("pasos", []) if isinstance(p, str)])[:6]
        if len(steps) >= 3:
            out.append({"tipo": "flujo", "titulo": _s(f.get("titulo") or "Cómo funciona", 36),
                        "pasos": steps, "narracion": _narr(f.get("narracion"))})

    s = by.get("stack")
    if s:
        items = _dedupe([_s(i, 24) for i in s.get("items", []) if isinstance(i, str)])
        items = [i for i in items if _grounded(i, haystack, False)][:8]
        if len(items) >= 2:
            out.append({"tipo": "stack", "titulo": "Tecnologías", "items": items,
                        "narracion": _narr(s.get("narracion"))})

    if len(out) < 3:
        raise StoryboardError("guion demasiado pobre")
    # El cierre no lo escribe el modelo: asi queda siempre correcto y sin relleno.
    out.append({"tipo": "cierre", "titulo": "Mirá el código", "texto": f"github.com/{info['owner']}/{info['repo']}",
                "narracion": ""})
    return {"titulo": _s(pretty, 40), "escenas": out}
