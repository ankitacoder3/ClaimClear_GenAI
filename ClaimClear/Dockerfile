# ClaimClear in one image: the five MCP servers and the chat (UI2, port 80).
#   docker compose up --build          (from ClaimClear/; reads the OpenRouter key from .env at run time)
# The image never contains .env or keys (.dockerignore); uploads live in the var volume.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CLAIMCLEAR_UI_HOST=0.0.0.0 CLAIMCLEAR_AUTO_LOCAL=0

RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng build-essential \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

# both environments, the development data and the policy index, built once at image build time
RUN python start.py --setup-only --no-local-llm

EXPOSE 80
CMD ["python", "start.py", "--no-browser", "--no-local-llm"]
