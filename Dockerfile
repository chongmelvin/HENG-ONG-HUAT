FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
# DejaVu gives the PDFs their symbols (yen, minus, ticks); the code falls back to Helvetica without it
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY src ./src
ENV PYTHONPATH=/app/src
EXPOSE 8080
CMD ["python", "-m", "finbot"]
