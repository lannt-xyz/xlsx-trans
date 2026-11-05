# syntax=docker/dockerfile:1
# Ảnh chạy xlsx-trans ở chế độ dòng lệnh (không có giao diện tkinter).
#   docker build -t xlsx-trans .                       # có llama-cpp-python (chạy file .gguf)
#   docker build -t xlsx-trans --build-arg WITH_LLAMA=0 .   # bản nhẹ, chỉ dùng Ollama

FROM python:3.12-slim AS builder
ARG WITH_LLAMA=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
# llama-cpp-python build từ source nên cần compiler (chỉ có ở stage này, không vào ảnh cuối)
RUN if [ "$WITH_LLAMA" = "1" ]; then \
      apt-get update && apt-get install -y --no-install-recommends build-essential cmake \
      && rm -rf /var/lib/apt/lists/* \
      && CMAKE_ARGS="-DGGML_NATIVE=OFF" pip install --no-cache-dir llama-cpp-python; \
    fi

FROM python:3.12-slim
# libgomp1: llama.cpp cần OpenMP khi chạy
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY app.py config.toml config.docker.toml ./
COPY xlsx_trans ./xlsx_trans
COPY prompts ./prompts
# Dữ liệu nằm ở /work (mount từ máy), model .gguf ở /models (mount từ máy)
WORKDIR /work
ENTRYPOINT ["python", "/app/app.py"]
CMD ["--help"]
