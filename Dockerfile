# InvisibleGo web server image.
#
# Runs the FastAPI + WebSocket server on port 8000. Serves browser
# clients plus the static frontend files under frontend/web/.

FROM python:3.12-slim

WORKDIR /app

# Web stack only — no PySide6, no dev tooling. Keep the image small.
RUN pip install --no-cache-dir \
    "fastapi>=0.110" \
    "uvicorn[standard]>=0.27"

# Copy only what the web server touches at runtime.
COPY core ./core
COPY protocol ./protocol
COPY transport ./transport
COPY frontend ./frontend

# Drop root for runtime.
RUN useradd --system --create-home invisiblego \
 && chown -R invisiblego:invisiblego /app
USER invisiblego

EXPOSE 8000

# --app-dir /app puts the project on sys.path so the transport.web.server
# module can import core/protocol/transport and Path(__file__).parents[2]
# still resolves to frontend/web/ for static files.
CMD ["uvicorn", "transport.web.server:app", \
     "--host", "0.0.0.0", "--port", "8000", "--app-dir", "/app"]
