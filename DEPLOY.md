# Деплой API на Ubuntu

Этот проект поднимает FastAPI-сервис, который принимает HTML/CSS/JS и
изображения через поля формы, кладет задачи в JSON-очередь и запускает сборку
через существующий Briefcase-проект `api2app`.

Важно: Android APK можно собирать на Ubuntu при наличии JDK и Android SDK.
Windows `msi/exe` через Briefcase обычно собирается на Windows-хосте. На Ubuntu
роут `/build/windows` можно оставить включенным, но сборка будет падать, если
Briefcase не поддерживает packaging Windows на этом сервере. Для Windows
артефактов нужен отдельный Windows builder с тем же API или отдельная очередь.

## 1. Пакеты системы

```bash
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3-pip git curl unzip openjdk-17-jdk
```

Для Android установите Android SDK command line tools. Скачайте актуальный
Linux-архив `commandlinetools-linux-*.zip` со страницы
`https://developer.android.com/studio#command-tools` и положите его на сервер.

```bash
sudo mkdir -p /opt/android-sdk/cmdline-tools
sudo chown -R "$USER":"$USER" /opt/android-sdk
cd /tmp
unzip commandlinetools-linux-*.zip
mv cmdline-tools /opt/android-sdk/cmdline-tools/latest
```

Добавьте переменные в профиль пользователя сервиса:

```bash
export ANDROID_HOME="/opt/android-sdk"
export ANDROID_SDK_ROOT="/opt/android-sdk"
export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$PATH"
```

Установите SDK-компоненты:

```bash
sdkmanager --licenses
sdkmanager "platform-tools" "platforms;android-35" "build-tools;35.0.0"
```

## 2. Код и окружение

```bash
cd /opt
sudo git clone <repo-url> api2app_python_webview
sudo chown -R "$USER":"$USER" /opt/api2app_python_webview
cd /opt/api2app_python_webview

python3.12 -m venv venv
. venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Создайте `.env`:

```bash
cp .env.example .env
nano .env
```

Минимальные настройки:

```dotenv
BUILD_MAX_CONCURRENT=1
BUILD_API_STORAGE_DIR=build_api/runtime
BRIEFCASE_PROJECT_DIR=api2app
BRIEFCASE_COMMAND=venv/bin/briefcase
BUILD_TIMEOUT_SECONDS=7200
MAX_SOURCE_BYTES=5000000
MAX_IMAGE_BYTES=10000000
ARTIFACT_TTL_SECONDS=3600
CLEANUP_INTERVAL_SECONDS=300
BUILD_KEEP_WORKSPACES=false
```

`BUILD_MAX_CONCURRENT` задает, сколько сборок можно выполнять одновременно.
Для одного Ubuntu-сервера обычно начинайте с `1`, потому что Gradle и Briefcase
потребляют много CPU, RAM и места на диске.

`ARTIFACT_TTL_SECONDS=3600` означает, что готовый файл хранится один час. После
истечения TTL API удаляет каталог результата и перестает отдавать download URL.

`MAX_IMAGE_BYTES` ограничивает размер загружаемого файла и изображения,
скачанного по `icon_url`/`ico_url`. Временные исходники иконок хранятся в
`build_api/runtime/uploads` только до завершения сборки.

## 3. Проверка вручную

```bash
. venv/bin/activate
uvicorn build_api.main:app --host 0.0.0.0 --port 8000
```

Откройте Swagger:

```text
http://SERVER_IP:8000/docs
```

Проверка health:

```bash
curl http://127.0.0.1:8000/health
```

## 4. Systemd

Создайте unit:

```bash
sudo nano /etc/systemd/system/api2app-build-api.service
```

Пример:

```ini
[Unit]
Description=api2app FastAPI build API
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/api2app_python_webview
Environment=ANDROID_HOME=/opt/android-sdk
Environment=ANDROID_SDK_ROOT=/opt/android-sdk
Environment=PATH=/opt/api2app_python_webview/venv/bin:/opt/android-sdk/cmdline-tools/latest/bin:/opt/android-sdk/platform-tools:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=/opt/api2app_python_webview/venv/bin/uvicorn build_api.main:app --host 127.0.0.1 --port 8000 --workers 1
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Если запускаете сервис не от `www-data`, замените `User`, `Group` и при
необходимости пути Android SDK. Важно оставить `--workers 1`: JSON-очередь и локальный лимит
параллельных сборок рассчитаны на один процесс API.

Права на проект и runtime-каталог:

```bash
sudo chown -R www-data:www-data /opt/api2app_python_webview
sudo chown -R www-data:www-data /opt/android-sdk
sudo -u www-data mkdir -p /opt/api2app_python_webview/build_api/runtime
```

Запуск:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now api2app-build-api
sudo systemctl status api2app-build-api
```

Логи:

```bash
journalctl -u api2app-build-api -f
```

## 5. Nginx

```bash
sudo apt install -y nginx
sudo nano /etc/nginx/sites-available/api2app-build-api
```

Конфиг:

```nginx
server {
    listen 80;
    server_name build-api.example.com;

    client_max_body_size 20m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 3600;
    }
}
```

Включите сайт:

```bash
sudo ln -s /etc/nginx/sites-available/api2app-build-api /etc/nginx/sites-enabled/api2app-build-api
sudo nginx -t
sudo systemctl reload nginx
```

Для HTTPS подключите certbot или ваш стандартный выпуск сертификатов.

## 6. Эксплуатация

- Swagger: `/docs`
- Healthcheck: `/health`
- Активная очередь: `GET /jobs`
- Статус задачи: `GET /jobs/{job_id}`
- Готовый файл: `GET /jobs/{job_id}/download`
- Лог сборки: `GET /jobs/{job_id}/log`

Готовые артефакты и логи лежат в `build_api/runtime/artifacts/{job_id}` до
истечения `ARTIFACT_TTL_SECONDS`. Временные рабочие копии Briefcase лежат в
`build_api/runtime/workspaces/{job_id}` и удаляются сразу после завершения
сборки.
