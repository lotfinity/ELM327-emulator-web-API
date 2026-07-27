FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# ELM327-emulator 3.0.5 is currently published as a source distribution whose
# setup script imports pkg_resources. Build it in this prepared environment
# instead of pip's minimal isolated build environment.
RUN pip install --upgrade pip "setuptools<81" wheel && \
    pip install --no-build-isolation --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
