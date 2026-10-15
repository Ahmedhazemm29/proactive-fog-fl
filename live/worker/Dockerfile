FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1
# One BLAS thread: the container gets 0.5 CPU, more threads only add overhead.
ENV OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
WORKDIR /app
RUN pip install --no-cache-dir numpy==2.2.6
COPY server.py .
CMD ["python", "server.py"]
