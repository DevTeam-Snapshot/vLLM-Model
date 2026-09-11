FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY image_service.py grpc_server.py .
COPY proto/hotel_ad_image.proto proto/
RUN mkdir generated && python -m grpc_tools.protoc -I proto --python_out=generated --grpc_python_out=generated proto/hotel_ad_image.proto

ENV PYTHONPATH=/app/generated
EXPOSE 50051

CMD ["python", "grpc_server.py"]
