FROM python:3.11.4-slim-buster AS builder

WORKDIR /usr/src/app

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc

RUN pip install --upgrade pip
COPY . /usr/src/app/

COPY ./requirements.txt .
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /usr/src/app/wheels -r requirements.txt

FROM python:3.11.4-slim-buster AS final

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl

COPY --from=builder /usr/src/app/wheels /wheels
COPY --from=builder /usr/src/app/requirements.txt .

RUN pip install --upgrade pip
RUN pip install --no-cache /wheels/*

COPY . /app

RUN chmod +x deployment/start.sh