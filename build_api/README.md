# api2app Build API

FastAPI service that accepts HTML/CSS/JS as form fields and builds packages
through the same Briefcase project that already exists in this repository.

Build requests must be sent as `multipart/form-data` when uploading images, or
as `application/x-www-form-urlencoded` when there are no files. The `html`,
`css`, and `js` fields can be sent as plain source code or wrapped in markdown
fences such as ```` ```html ... ``` ```` and `~~~css ... ~~~`. Outer fence lines
are removed before the app is generated. The `html` field must be a complete
document: `<!doctype html>`, `<html>`, `<head>`, `<body>`, and matching closing
tags are required.

Header fields use names such as `header_title`. Header and menu settings are
rendered through native Toga/Android controls, not injected into the submitted
HTML. Menu items can be sent as a JSON array in the `menu_items` form field or
as repeated `menu_label`, `menu_href`, and `menu_onclick` fields.

## Run

```bash
. venv/bin/activate
pip install -r requirements.txt
uvicorn build_api.main:app --host 0.0.0.0 --port 8000
```

Swagger UI is available at `http://localhost:8000/docs`.

Set `BUILD_API_KEY` in `.env` and pass it with protected requests:

```bash
curl -H "X-API-Key: $BUILD_API_KEY" http://localhost:8000/jobs
```

## Routes

- `POST /build/android` starts an Android build and returns a job id. Use
  `package_format=debug-apk` for APK files that can be installed directly on a
  phone. Use `package_format=apk` or `package_format=aab` for release
  packaging; the default is `debug-apk`.
- `POST /build/windows` starts a Windows build and returns a job id.
- `GET /jobs/{job_id}` returns queue/build status.
- `GET /jobs/{job_id}/download` returns the APK/AAB/MSI/EXE after completion.
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
  -H "X-API-Key: $BUILD_API_KEY" \
  -F 'package_format=debug-apk' \
  -F 'app_name=Demo App' \
  -F 'header_title=Demo App' \
  -F 'header_subtitle=Generated header' \
  -F 'header_background_color=#111827' \
  -F 'header_text_color=#ffffff' \
  -F 'menu_position=top' \
  -F 'menu_items=[{"label":"Home","href":"#home"},{"label":"Settings","href":"#settings"}]' \
  -F 'html=<!doctype html><html><head><meta charset="utf-8"></head><body><main><h1>Hello</h1><button onclick="hello()">Run</button></main></body></html>' \
  -F 'css=body { font-family: sans-serif; padding: 24px; }' \
  -F 'js=function hello() { alert("Hello from api2app"); }' \
  -F 'icon_file=@/path/to/icon.png'
```

For app icons, pass either `icon_file=@/path/to/image.png` or
`icon_url=https://example.com/icon.png`. The source image can be PNG, JPG, WEBP,
BMP, GIF, or ICO; it is converted and resized automatically for Android launcher
icons, the Play Store icon, and the Windows ICO file. To override only the
Windows icon, use `ico_file` or `ico_url`. Downloaded/uploaded source images are
stored under `build_api/runtime/uploads` only while the queued build needs them
and are deleted after the build finishes or fails.
