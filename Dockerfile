FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY np2_structs.proto .
COPY pyproject.toml .

RUN pip install --no-cache-dir -e .
RUN python -m grpc_tools.protoc -I. --python_out=src/rpcn_client np2_structs.proto

CMD ["uvicorn", "tekken_tt2.app:app", "--host", "0.0.0.0", "--port", "8000"]
