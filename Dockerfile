# Dockerfile

FROM --platform=linux/amd64 python:3.6-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN set -eux; \
    sed -i \
        -e 's|http://deb.debian.org/debian|http://archive.debian.org/debian|g' \
        -e 's|http://security.debian.org/debian-security|http://archive.debian.org/debian-security|g' \
        /etc/apt/sources.list; \
    echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99no-check-valid-until; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        build-essential \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender-dev; \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

COPY . /app/

EXPOSE 7860

ENV PYTHONWARNINGS="ignore::FutureWarning"

CMD ["sh", "-c", "python manage.py migrate && python manage.py collectstatic --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:7860 --workers 1 --timeout 300 --preload"]