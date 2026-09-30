FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
RUN pip install --no-cache-dir numpy scikit-learn
COPY workload.py .
CMD ["python", "workload.py"]
