# The FL aggregator (aggregator.py), built on the Raspberry Pi (arm64) by
# pi/docker-compose.yml. Plain Python: FedAvg of 5 weights needs no math library.
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
RUN pip install --no-cache-dir paho-mqtt==2.1.0
COPY aggregator.py .
CMD ["python", "aggregator.py"]
