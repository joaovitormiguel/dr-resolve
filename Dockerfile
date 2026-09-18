FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir pillow numpy
ENV PORT=8765 HOST=0.0.0.0
EXPOSE 8765
CMD ["sh", "-c", "python3 app.py ${PORT}"]
