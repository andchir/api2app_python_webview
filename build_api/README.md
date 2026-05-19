# api2app Build API

FastAPI service that accepts HTML/CSS/JS and builds packages through the same
Briefcase project that already exists in this repository.

The `html`, `css`, and `js` fields can be sent as plain source code or wrapped
in markdown fences such as ```` ```html ... ``` ```` and `~~~css ... ~~~`.
Outer fence lines are removed before the app is generated. The `html` field
must be a complete document: `<!doctype html>`, `<html>`, `<head>`, `<body>`,
and matching closing tags are required.

## Run

```bash
. venv/bin/activate
pip install -r requirements.txt
uvicorn build_api.main:app --host 0.0.0.0 --port 8000
```

Swagger UI is available at `http://localhost:8000/docs`.

## Routes

- `POST /build/android` starts an Android build and returns a job id.
- `POST /build/windows` starts a Windows build and returns a job id.
- `GET /jobs/{job_id}` returns queue/build status.
- `GET /jobs/{job_id}/download` returns the APK/MSI/EXE after completion.
- `GET /jobs/{job_id}/log` returns the Briefcase build log.

Queue state is stored in `build_api/runtime/queue.json`. Finished jobs are
removed from that queue file; final metadata and artifacts are stored under
`build_api/runtime/artifacts/{job_id}` and removed after `ARTIFACT_TTL_SECONDS`
from `.env`.

Each build runs in an isolated temporary Briefcase workspace under
`build_api/runtime/workspaces/{job_id}`. That workspace is deleted after the
build finishes, regardless of success or failure.

## Example

```bash
curl -X POST http://localhost:8000/build/android \
  -H 'Content-Type: application/json' \
  -d '{
    "app_name": "Demo App",
    "header": {
      "title": "Demo App",
      "subtitle": "Generated header",
      "background_color": "#111827",
      "text_color": "#ffffff"
    },
    "menu": {
      "position": "top",
      "items": [
        { "label": "Home", "href": "#home" },
        { "label": "Settings", "href": "#settings" }
      ]
    },
    "html": "<!doctype html><html><head><meta charset=\"utf-8\"></head><body><main><h1>Hello</h1><button onclick=\"hello()\">Run</button></main></body></html>",
    "css": "body { font-family: sans-serif; padding: 24px; }",
    "js": "function hello() { alert(\"Hello from api2app\"); }"
  }'
```

For app icons, pass `icon.png_base64` as a square PNG encoded in base64 or as a
`data:image/png;base64,...` value. The API generates Android launcher PNG files
and a Windows `icon.ico` from it. You can override the Windows icon with
`icon.ico_base64`.
