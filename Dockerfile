FROM python:3.8.5-slim-buster

RUN apt-get update -qq \
    && DEBIAN_FRONTEND=noninteractive apt-get install -yq --no-install-recommends \
        curl \
        git \
        vim \
    && apt-get clean \
    && rm -rf /var/cache/apt/archives/* \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* \
    && truncate -s 0 /var/log/*log

RUN curl -sSL https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py > get-poetry.py \
    && python get-poetry.py --version 1.0.10 \
    && rm get-poetry.py

ENV PATH $PATH:/root/.poetry/bin
RUN poetry config virtualenvs.create false

COPY pyproject.toml poetry.lock ./
RUN poetry install  --no-interaction --no-ansi --no-root

WORKDIR /app

ADD . /app

CMD bash
