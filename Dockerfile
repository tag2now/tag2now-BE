FROM python:3.12-alpine

RUN apk add --no-cache curl

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY np2_structs.proto .
RUN python -m grpc_tools.protoc -I. --python_out=src/rpcn_client np2_structs.proto

# Migrations run from this image (`run --rm be python -m alembic upgrade head`
# during deploy), so the alembic tree has to ship with it. alembic.ini's
# prepend_sys_path=src is what lets env.py import the entity modules.
COPY alembic.ini .
COPY alembic/ ./alembic/

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "src"]
