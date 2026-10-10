# repo2video

Bot de Telegram: le pegas un link de GitHub y te devuelve un video vertical (720x1280, ~30-40 s) con motion graphics que explica como funciona el repo.

link -> resumen del repo (API de GitHub) -> guion JSON (Ollama, modelo local) -> validacion -> render (Chromium + ffmpeg) -> video

## Requisitos
- Ollama corriendo en el nodo con el modelo `qwen2.5:7b` (contenedor `ollama`, publicado en 127.0.0.1:11434, tope de ~7 GB).
- Un bot nuevo de @BotFather (distinto al del subtitulador).

## Instalar
```bash
cd ~/repo2video
cp .env.example .env && nano .env      # token y, despues, tu ID
sudo docker compose up -d --build      # la primera vez baja Chromium: tarda
sudo docker compose logs --tail 20
```
Mandale `/start` al bot: te dice tu ID. Ponelo en `ALLOWED_USER_IDS` y `sudo docker compose up -d`.

## Notas de recursos
- Un video a la vez. El modelo se descarga de la RAM al terminar el guion (`keep_alive: 0`), asi el render tiene memoria.
- Tiempo estimado: ~3-6 min de guion (7B en CPU) + ~1-2 min de render.
- Mejor no usar el subtitulador mientras se genera un guion.

## Probar sin Telegram
```bash
sudo docker compose run --rm repo2video python pipeline.py https://github.com/usuario/repo
sudo docker compose run --rm repo2video python render.py ejemplo_corcho.json /tmp/demo.mp4   # solo render
```

## Piezas
- `github_summary.py`: link -> resumen corto (~1900 caracteres).
- `storyboard.py`: prompt, llamada a Ollama, validacion/reparacion del JSON. El cierre lo genera el codigo, no el modelo.
- `template.html` + `render.py`: escenas animadas (titulo, diagrama, flujo, stack, cierre) y exportacion con ffmpeg.
- `bot.py`: bot de Telegram con cola de un trabajo.
