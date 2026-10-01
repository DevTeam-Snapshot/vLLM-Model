FROM python:3.12-slim

WORKDIR /app
COPY requirements-v2-contract.txt requirements-v2-server.txt ./
RUN python -m pip install --no-cache-dir -r requirements-v2-server.txt
COPY proto/hotel_ad_image.proto proto/hotel_ad_v2.proto proto/
RUN mkdir generated && python -m grpc_tools.protoc -I proto --python_out=generated --pyi_out=generated --grpc_python_out=generated proto/hotel_ad_image.proto proto/hotel_ad_v2.proto
COPY grpc_server.py image_service.py ./
COPY v2/ v2/
COPY assets/fonts/ assets/fonts/
COPY examples/ examples/
ENV PYTHONPATH=/app/generated:/app/examples:/app PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENV MODEL_MODE=fake GRPC_HOST=0.0.0.0 PORT=50051
EXPOSE 50051
HEALTHCHECK --interval=30s --timeout=12s --start-period=15s --retries=3 CMD ["python", "-m", "v2.healthcheck"]
CMD ["python", "-m", "v2.server"]
