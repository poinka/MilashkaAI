FROM --platform=linux/amd64 python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    software-properties-common \
    git \
    cmake \
    ninja-build \
    libc++-dev \
    libc++abi-dev \
    ffmpeg \
    && curl https://sh.rustup.rs -sSf | sh -s -- -y \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip

COPY requirements.txt .

RUN export PATH="$PATH:/root/.cargo/bin" && \
    pip install -r requirements.txt && \
    python -m spacy download en_core_web_lg && \
    python -m spacy download ru_core_news_lg

RUN pip install --no-binary=llama-cpp-python llama-cpp-python

COPY app/ app/

RUN mkdir -p /app/uploads /models data

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]