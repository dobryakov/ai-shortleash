FROM python:3.12-slim-bookworm

LABEL org.agent-run.aider-version="0.86.1"

RUN apt-get update \
    && apt-get install -y --no-install-recommends git bash ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Pin aider for reproducibility
RUN pip install --no-cache-dir \
    "aider-chat==0.86.1" \
    "pytest>=8.0" \
    "httpx>=0.27"

WORKDIR /workspace
ENV HOME=/tmp
ENV PYTHONUNBUFFERED=1

CMD ["bash"]
