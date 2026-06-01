FROM python:3.11-slim-bookworm

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV SERVER_PORT=8000
ENV USE_MONITOR=0
ENV TZ=Asia/Shanghai
ENV HTMLSYSTM_GUNICORN_WORKERS=2
ENV HTMLSYSTM_GUNICORN_THREADS=20

RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

COPY htmlsystm/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -c "import PIL; print('Pillow', PIL.__version__)"

COPY htmlsystm/ .
# 仓库根目录品牌 logo（构建上下文为 docker版本/）
COPY logo.png static/logo.png

EXPOSE 8000

# 覆盖 gunicorn_config 中偏大的 worker 数，降低小内存环境 OOM 风险（可通过环境变量调节）
CMD gunicorn --config gunicorn_config.py \
    --workers ${HTMLSYSTM_GUNICORN_WORKERS:-2} \
    --threads ${HTMLSYSTM_GUNICORN_THREADS:-20} \
    --capture-output --enable-stdio-inheritance \
    server.wsgi_app:application
