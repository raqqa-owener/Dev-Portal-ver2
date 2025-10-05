#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-.}"

say() { printf "\033[1;32m==>\033[0m %s\n" "$*"; }

# =====================================================================================
# Dirs
# =====================================================================================
say "Creating directories..."
mkdir -p "$ROOT/api/app/routers" \
         "$ROOT/api/app/schemas" \
         "$ROOT/api/app/services" \
         "$ROOT/api/app/repos" \
         "$ROOT/api/app/utils" \
         "$ROOT/api/app/openapi" \
         "$ROOT/api/sql" \
         "$ROOT/k8s/base/postgres" \
         "$ROOT/k8s/base/odoo" \
         "$ROOT/k8s/base/portal-api" \
         "$ROOT/k8s/base/chroma" \
         "$ROOT/k8s/base/cronjobs" \
         "$ROOT/k8s/overlays/dev" \
         "$ROOT/k8s/overlays/prod" \
         "$ROOT/k8s/infra/postgres" \
         "$ROOT/k8s/odoo" \
         "$ROOT/scripts"

# =====================================================================================
# API: Dockerfile & requirements
# =====================================================================================
say "Scaffolding API base..."
cat > "$ROOT/api/Dockerfile" <<'DOCKER'
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt
COPY app /app/app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
DOCKER

cat > "$ROOT/api/requirements.txt" <<'REQ'
fastapi
uvicorn[standard]
pydantic
SQLAlchemy
psycopg2-binary
python-dotenv
requests
REQ

# =====================================================================================
# API: app skeleton
# =====================================================================================
cat > "$ROOT/api/app/__init__.py" <<'PY'
# app package
PY

cat > "$ROOT/api/app/main.py" <<'PY'
from fastapi import FastAPI
from .routers import extract, translate, writeback, package, chroma, status

app = FastAPI(title="Dev Portal API")

app.include_router(extract.router,    prefix="/extract",   tags=["extract"])
app.include_router(translate.router,  prefix="/translate", tags=["translate"])
app.include_router(writeback.router,  prefix="/writeback", tags=["writeback"])
app.include_router(package.router,    prefix="/chroma",    tags=["chroma-package"])
app.include_router(chroma.router,     prefix="/chroma",    tags=["chroma"])
app.include_router(status.router,     prefix="/status",    tags=["status"])

@app.get("/healthz")
def healthz(): return {"ok": True}

@app.get("/livez")
def livez(): return {"ok": True}

@app.get("/startupz")
def startupz(): return {"ok": True}
PY

cat > "$ROOT/api/app/config.py" <<'PY'
from pydantic import BaseSettings

class Settings(BaseSettings):
    # Overridden by K8s ConfigMap/Secret in production
    DATABASE_URL: str = "postgresql+psycopg2://portal:portal@localhost:5432/portal"
    ODOO_DATABASE_URL: str = "postgresql+psycopg2://odoo:odoo@localhost:5432/odoo"
    CHROMA_HOST: str = "localhost"
    CHROMA_PORT: int = 8000

settings = Settings()
PY

cat > "$ROOT/api/app/db.py" <<'PY'
# TODO: SQLAlchemy engine/session
PY

cat > "$ROOT/api/app/routers/__init__.py" <<'PY'
from . import extract, translate, writeback, package, chroma, status
PY

cat > "$ROOT/api/app/routers/extract.py" <<'PY'
from fastapi import APIRouter
router = APIRouter()
# POST /extract/view_common, POST /extract/field
PY

cat > "$ROOT/api/app/routers/translate.py" <<'PY'
from fastapi import APIRouter
router = APIRouter()
# POST /translate/run, GET /translate
PY

cat > "$ROOT/api/app/routers/writeback.py" <<'PY'
from fastapi import APIRouter
router = APIRouter()
# POST /writeback/view_common, POST /writeback/field
PY

cat > "$ROOT/api/app/routers/package.py" <<'PY'
from fastapi import APIRouter
router = APIRouter()
# POST /chroma/package, GET /chroma/docs
PY

cat > "$ROOT/api/app/routers/chroma.py" <<'PY'
from fastapi import APIRouter
router = APIRouter()
# POST /chroma/upsert
PY

cat > "$ROOT/api/app/routers/status.py" <<'PY'
from fastapi import APIRouter
router = APIRouter()
# GET /status/summary, GET /samples/trace
PY

# Schemas
cat > "$ROOT/api/app/schemas/common.py" <<'PY'
from pydantic import BaseModel
from typing import Literal

Lang = Literal["ja", "en"]
Entity = Literal["field", "view_common"]

class NaturalKey(BaseModel):
    entity: Entity
    key: str

class Summary(BaseModel):
    pending: int
    translated: int
    queued: int
    upserted: int
PY

cat > "$ROOT/api/app/schemas/extract_view_common.py" <<'PY'
from pydantic import BaseModel
from typing import List, Literal

class ExtractViewCommonIn(BaseModel):
    action_xmlids: List[str]
    targets: List[Literal["ai_purpose","help"]] = ["ai_purpose","help"]
    mode: Literal["upsert_if_changed","force_overwrite"] = "upsert_if_changed"

class ExtractViewCommonOut(BaseModel):
    queued: int
    skipped: int
PY

cat > "$ROOT/api/app/schemas/extract_field.py" <<'PY'
from pydantic import BaseModel
from typing import List

class ExtractFieldIn(BaseModel):
    models: List[str] = []
    fields: List[str] = []
    mode: str = "upsert_if_changed"

class ExtractFieldOut(BaseModel):
    queued: int
    skipped: int
PY

cat > "$ROOT/api/app/schemas/translate_run.py" <<'PY'
from pydantic import BaseModel
from typing import List
from .common import Entity

class TranslateRunIn(BaseModel):
    limit: int = 200
    source_lang: str = "ja_JP"
    target_lang: str = "en_US"
    entities: List[Entity] = ["field","view_common"]

class TranslateRunOut(BaseModel):
    processed: int
    failed: int
PY

cat > "$ROOT/api/app/schemas/writeback_view_common.py" <<'PY'
from pydantic import BaseModel
class WritebackViewCommonIn(BaseModel):
    mode: str = "skip_if_exists"
    overwrite: bool = False
PY

cat > "$ROOT/api/app/schemas/writeback_field.py" <<'PY'
from pydantic import BaseModel
class WritebackFieldIn(BaseModel):
    mode: str = "skip_if_exists"
    overwrite: bool = False
PY

cat > "$ROOT/api/app/schemas/chroma_package.py" <<'PY'
from pydantic import BaseModel
from typing import Dict, List
from .common import Entity

class ChromaPackageIn(BaseModel):
    entities: List[Entity] = ["field","view_common"]
    lang: str = "ja"
    collections: Dict[str,str] = {"field":"portal_field_ja","view_common":"portal_view_common_ja"}
    limit: int = 500

class ChromaPackageOut(BaseModel):
    queued: int
    skipped: int
PY

cat > "$ROOT/api/app/schemas/chroma_upsert.py" <<'PY'
from pydantic import BaseModel
from typing import List

class ChromaUpsertIn(BaseModel):
    collections: List[str] = ["portal_field_ja","portal_view_common_ja"]
    limit: int = 1000
    dry_run: bool = False

class ChromaUpsertOut(BaseModel):
    upserted: int
    failed: int
PY

cat > "$ROOT/api/app/schemas/status.py" <<'PY'
from pydantic import BaseModel
from .common import Summary

class StatusSummary(BaseModel):
    summary: Summary
PY

# Services/repos/utils placeholders
cat > "$ROOT/api/app/services/extract.py" <<'PY'
# Orchestration for extract
PY
cat > "$ROOT/api/app/services/translate.py" <<'PY'
# Translation worker (pending -> translated)
PY
cat > "$ROOT/api/app/services/writeback.py" <<'PY'
# Optional writeback
PY
cat > "$ROOT/api/app/services/package.py" <<'PY'
# Make docs for Chroma export
PY
cat > "$ROOT/api/app/services/chroma_client.py" <<'PY'
# Chroma upsert/query
PY
cat > "$ROOT/api/app/services/natural_text.py" <<'PY'
# Document text generation templates
PY

for f in portal_translate_repo portal_chroma_doc_repo portal_view_common_repo portal_field_repo portal_model_repo; do
  cat > "$ROOT/api/app/repos/${f}.py" <<PY
# repo placeholder: ${f}
PY
done

cat > "$ROOT/api/app/utils/natural_key.py" <<'PY'
# natural_key build/validate
PY
cat > "$ROOT/api/app/utils/lang_detect.py" <<'PY'
# JA text detection
PY
cat > "$ROOT/api/app/utils/html_strip.py" <<'PY'
# strip HTML
PY
cat > "$ROOT/api/app/utils/text_hash.py" <<'PY'
# text hashing for change detection
PY
cat > "$ROOT/api/app/utils/time.py" <<'PY'
# time utils
PY

cat > "$ROOT/api/app/openapi/openapi.yaml" <<'YAML'
openapi: 3.1.0
info: { title: Dev Portal API, version: 0.0.1 }
paths: {}
YAML

# SQL placeholders
for f in 000_extensions.sql 010_portal_core.sql 020_portal_translate.sql 030_portal_chroma_doc.sql; do
  echo "-- $f (TBD)" > "$ROOT/api/sql/$f"
done

# =====================================================================================
# K8s: BASE (no namespace/secret/config in base)
# =====================================================================================
say "Scaffolding Kubernetes (base)..."

# base/kustomization.yaml
cat > "$ROOT/k8s/base/kustomization.yaml" <<'YAML'
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - postgres/statefulset.yaml
  - postgres/service.yaml
  - postgres/init-configmap.yaml
  - odoo/deployment.yaml
  - odoo/service.yaml
  - odoo/ingress.yaml
  - odoo/pvc.yaml
  - chroma/statefulset.yaml
  - chroma/service.yaml
  - portal-api/serviceaccount.yaml
  - portal-api/deployment.yaml
  - portal-api/service.yaml
  - portal-api/ingress.yaml
  - portal-api/hpa.yaml
  - cronjobs/ir-src-rebuild.yaml
  - cronjobs/cj-extract-view.yaml
  - cronjobs/cj-extract-field.yaml
  - cronjobs/cj-translate-run.yaml
  - cronjobs/cj-chroma-package.yaml
  - cronjobs/cj-chroma-upsert.yaml
YAML

# Postgres (expects Secret via overlay)
cat > "$ROOT/k8s/base/postgres/init-configmap.yaml" <<'YAML'
apiVersion: v1
kind: ConfigMap
metadata: { name: postgres-init }
data:
  init-multi-db.sh: |
    #!/usr/bin/env bash
    set -euo pipefail
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-SQL
      DO $$
      BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname=current_setting('odoo.user', true)) THEN
          EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L', current_setting('odoo.user', true), current_setting('odoo.pass', true));
        END IF;
        IF NOT EXISTS (SELECT FROM pg_database WHERE datname='odoo') THEN
          EXECUTE format('CREATE DATABASE %I OWNER %I', 'odoo', current_setting('odoo.user', true));
        END IF;
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname=current_setting('portal.user', true)) THEN
          EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L', current_setting('portal.user', true), current_setting('portal.pass', true));
        END IF;
        IF NOT EXISTS (SELECT FROM pg_database WHERE datname='portal') THEN
          EXECUTE format('CREATE DATABASE %I OWNER %I', 'portal', current_setting('portal.user', true));
        END IF;
      END
      $$;
SQL
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" -d portal <<-SQL
      CREATE EXTENSION IF NOT EXISTS pgcrypto;
      CREATE EXTENSION IF NOT EXISTS postgres_fdw;
SQL
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" -d odoo <<-SQL
      CREATE EXTENSION IF NOT EXISTS pgcrypto;
SQL
YAML

cat > "$ROOT/k8s/base/postgres/statefulset.yaml" <<'YAML'
apiVersion: apps/v1
kind: StatefulSet
metadata: { name: postgres }
spec:
  serviceName: postgres
  replicas: 1
  selector: { matchLabels: { app: postgres } }
  template:
    metadata: { labels: { app: postgres } }
    spec:
      securityContext: { fsGroup: 999 }
      containers:
        - name: db
          image: postgres:16
          ports: [{ containerPort: 5432, name: pg }]
          env:
            - { name: POSTGRES_USER, value: postgres }
            - { name: POSTGRES_PASSWORD, valueFrom: { secretKeyRef: { name: postgres-auth, key: POSTGRES_PASSWORD } } }
            - { name: odoo.user, valueFrom: { secretKeyRef: { name: postgres-auth, key: ODOO_DB_USER } } }
            - { name: odoo.pass, valueFrom: { secretKeyRef: { name: postgres-auth, key: ODOO_DB_PASSWORD } } }
            - { name: portal.user, valueFrom: { secretKeyRef: { name: postgres-auth, key: PORTAL_DB_USER } } }
            - { name: portal.pass, valueFrom: { secretKeyRef: { name: postgres-auth, key: PORTAL_DB_PASSWORD } } }
          volumeMounts:
            - { name: data, mountPath: /var/lib/postgresql/data }
            - { name: init, mountPath: /docker-entrypoint-initdb.d }
      volumes:
        - name: init
          configMap: { name: postgres-init, defaultMode: 0755 }
  volumeClaimTemplates:
    - metadata: { name: data }
      spec:
        accessModes: ["ReadWriteOnce"]
        resources: { requests: { storage: 20Gi } }
YAML

cat > "$ROOT/k8s/base/postgres/service.yaml" <<'YAML'
apiVersion: v1
kind: Service
metadata: { name: postgres }
spec:
  selector: { app: postgres }
  ports: [{ name: pg, port: 5432, targetPort: 5432 }]
YAML

# Odoo
cat > "$ROOT/k8s/base/odoo/deployment.yaml" <<'YAML'
apiVersion: apps/v1
kind: Deployment
metadata: { name: odoo }
spec:
  replicas: 1
  selector: { matchLabels: { app: odoo } }
  template:
    metadata: { labels: { app: odoo } }
    spec:
      containers:
        - name: odoo
          image: odoo:18
          ports: [{ containerPort: 8069, name: http }]
          env:
            - { name: HOST, value: "0.0.0.0" }
            - { name: ODOO_DB_HOST, value: postgres }
            - { name: ODOO_DB_PORT, value: "5432" }
            - { name: ODOO_DB_USER, valueFrom: { secretKeyRef: { name: postgres-auth, key: ODOO_DB_USER } } }
            - { name: ODOO_DB_PASSWORD, valueFrom: { secretKeyRef: { name: postgres-auth, key: ODOO_DB_PASSWORD } } }
            - { name: ODOO_DB_NAME, value: "odoo" }
            - { name: ODOO_PROXY_MODE, value: "true" }
          volumeMounts:
            - { name: filestore, mountPath: /var/lib/odoo }
          readinessProbe: { httpGet: { path: /web, port: http }, initialDelaySeconds: 20, periodSeconds: 5 }
          livenessProbe:  { httpGet: { path: /web, port: http }, initialDelaySeconds: 60, periodSeconds: 10 }
      volumes:
        - name: filestore
          persistentVolumeClaim: { claimName: odoo-filestore }
YAML

cat > "$ROOT/k8s/base/odoo/service.yaml" <<'YAML'
apiVersion: v1
kind: Service
metadata: { name: odoo }
spec:
  selector: { app: odoo }
  ports: [{ name: http, port: 80, targetPort: 8069 }]
YAML

cat > "$ROOT/k8s/base/odoo/ingress.yaml" <<'YAML'
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: odoo
  annotations: {}
spec:
  rules:
    - host: odoo.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend: { service: { name: odoo, port: { number: 80 } } }
YAML

cat > "$ROOT/k8s/base/odoo/pvc.yaml" <<'YAML'
apiVersion: v1
kind: PersistentVolumeClaim
metadata: { name: odoo-filestore }
spec:
  accessModes: ["ReadWriteOnce"]
  resources: { requests: { storage: 20Gi } }
YAML

# Chroma
cat > "$ROOT/k8s/base/chroma/statefulset.yaml" <<'YAML'
apiVersion: apps/v1
kind: StatefulSet
metadata: { name: chroma }
spec:
  serviceName: chroma
  replicas: 1
  selector: { matchLabels: { app: chroma } }
  template:
    metadata: { labels: { app: chroma } }
    spec:
      containers:
        - name: chroma
          image: ghcr.io/chroma-core/chroma:0.4.24
          ports: [{ containerPort: 8000, name: http }]
          env:
            - { name: CHROMA_PORT, value: "8000" }
            - { name: PERSIST_DIRECTORY, value: /chroma }
          volumeMounts:
            - { name: data, mountPath: /chroma }
  volumeClaimTemplates:
    - metadata: { name: data }
      spec:
        accessModes: ["ReadWriteOnce"]
        resources: { requests: { storage: 20Gi } }
YAML

cat > "$ROOT/k8s/base/chroma/service.yaml" <<'YAML'
apiVersion: v1
kind: Service
metadata: { name: chroma }
spec:
  selector: { app: chroma }
  ports: [{ name: http, port: 8000, targetPort: 8000 }]
YAML

# Portal API (ServiceAccount for optional IRSA)
cat > "$ROOT/k8s/base/portal-api/serviceaccount.yaml" <<'YAML'
apiVersion: v1
kind: ServiceAccount
metadata: { name: portal-api }
YAML

cat > "$ROOT/k8s/base/portal-api/deployment.yaml" <<'YAML'
apiVersion: apps/v1
kind: Deployment
metadata: { name: portal-api }
spec:
  selector: { matchLabels: { app: portal-api } }
  template:
    metadata: { labels: { app: portal-api } }
    spec:
      serviceAccountName: portal-api
      containers:
        - name: api
          image: dev-portal-api:latest
          ports: [{ containerPort: 8000, name: http }]
          env:
            - { name: APP_ENV, valueFrom: { configMapKeyRef: { name: api-config, key: APP_ENV } } }
            - { name: LOG_LEVEL, valueFrom: { configMapKeyRef: { name: api-config, key: LOG_LEVEL } } }
            - { name: API_PORT, valueFrom: { configMapKeyRef: { name: api-config, key: API_PORT } } }
            - { name: DB_HOST, valueFrom: { configMapKeyRef: { name: api-config, key: DB_HOST } } }
            - { name: DB_PORT, valueFrom: { configMapKeyRef: { name: api-config, key: DB_PORT } } }
            - { name: DB_NAME, valueFrom: { configMapKeyRef: { name: api-config, key: DB_NAME } } }
            - { name: CHROMA_HOST, valueFrom: { configMapKeyRef: { name: api-config, key: CHROMA_HOST } } }
            - { name: CHROMA_PORT, valueFrom: { configMapKeyRef: { name: api-config, key: CHROMA_PORT } } }
            - { name: CHROMA_COLLECTION_FIELD_JA, valueFrom: { configMapKeyRef: { name: api-config, key: CHROMA_COLLECTION_FIELD_JA } } }
            - { name: CHROMA_COLLECTION_VIEW_JA,  valueFrom: { configMapKeyRef: { name: api-config, key: CHROMA_COLLECTION_VIEW_JA } } }
            - { name: DB_USER, valueFrom: { secretKeyRef: { name: api-auth, key: DB_USER } } }
            - { name: DB_PASSWORD, valueFrom: { secretKeyRef: { name: api-auth, key: DB_PASSWORD } } }
            - { name: API_BEARER_TOKEN, valueFrom: { secretKeyRef: { name: api-auth, key: API_BEARER_TOKEN } } }
          readinessProbe: { httpGet: { path: /healthz, port: http }, initialDelaySeconds: 5, periodSeconds: 5 }
          livenessProbe:  { httpGet: { path: /livez,   port: http }, initialDelaySeconds: 10, periodSeconds: 10 }
          startupProbe:   { httpGet: { path: /startupz,port: http }, failureThreshold: 30, periodSeconds: 2 }
YAML

cat > "$ROOT/k8s/base/portal-api/service.yaml" <<'YAML'
apiVersion: v1
kind: Service
metadata: { name: portal-api }
spec:
  selector: { app: portal-api }
  ports: [{ name: http, port: 80, targetPort: 8000 }]
YAML

cat > "$ROOT/k8s/base/portal-api/ingress.yaml" <<'YAML'
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: portal-api
  annotations: {}
spec:
  rules:
    - host: api.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend: { service: { name: portal-api, port: { number: 80 } } }
YAML

cat > "$ROOT/k8s/base/portal-api/hpa.yaml" <<'YAML'
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata: { name: portal-api }
spec:
  scaleTargetRef: { apiVersion: apps/v1, kind: Deployment, name: portal-api }
  minReplicas: 2
  maxReplicas: 8
  metrics:
    - type: Resource
      resource: { name: cpu, target: { type: Utilization, averageUtilization: 60 } }
YAML

# CronJobs (use /bin/sh so $TOKEN expands)
cat > "$ROOT/k8s/base/cronjobs/ir-src-rebuild.yaml" <<'YAML'
apiVersion: batch/v1
kind: CronJob
metadata: { name: ir-src-rebuild }
spec:
  schedule: "0 * * * *"
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: psql
              image: postgres:16
              env:
                - { name: DB_HOST, value: postgres }
                - { name: DB_NAME, value: portal }
                - { name: DB_USER, valueFrom: { secretKeyRef: { name: api-auth, key: DB_USER } } }
                - { name: DB_PASSWORD, valueFrom: { secretKeyRef: { name: api-auth, key: DB_PASSWORD } } }
                - { name: ODOO_DB_PASSWORD, valueFrom: { secretKeyRef: { name: postgres-auth, key: ODOO_DB_PASSWORD } } }
              command: ["sh","-lc"]
              args:
                - |
                  export PGPASSWORD="$DB_PASSWORD";
                  psql "host=$DB_HOST dbname=$DB_NAME user=$DB_USER" -v ON_ERROR_STOP=1 <<'SQL'
                  CREATE EXTENSION IF NOT EXISTS postgres_fdw;
                  -- TODO: ir_*_src rebuild SQL
SQL
YAML

cat > "$ROOT/k8s/base/cronjobs/cj-extract-view.yaml" <<'YAML'
apiVersion: batch/v1
kind: CronJob
metadata: { name: cj-extract-view }
spec:
  schedule: "*/30 * * * *"
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: curl
              image: curlimages/curl:8.8.0
              env:
                - name: TOKEN
                  valueFrom: { secretKeyRef: { name: api-auth, key: API_BEARER_TOKEN } }
              command: ["sh","-lc"]
              args:
                - >
                  curl -sS -X POST
                  -H "Authorization: Bearer $TOKEN"
                  -H "Content-Type: application/json"
                  --data '{"action_xmlids":[],"targets":["ai_purpose","help"],"mode":"upsert_if_changed"}'
                  http://portal-api.$(cat /var/run/secrets/kubernetes.io/serviceaccount/namespace).svc.cluster.local/extract/view_common
YAML

cat > "$ROOT/k8s/base/cronjobs/cj-extract-field.yaml" <<'YAML'
apiVersion: batch/v1
kind: CronJob
metadata: { name: cj-extract-field }
spec:
  schedule: "15 * * * *"
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: curl
              image: curlimages/curl:8.8.0
              env:
                - name: TOKEN
                  valueFrom: { secretKeyRef: { name: api-auth, key: API_BEARER_TOKEN } }
              command: ["sh","-lc"]
              args:
                - >
                  curl -sS -X POST
                  -H "Authorization: Bearer $TOKEN"
                  -H "Content-Type: application/json"
                  --data '{"models":[],"fields":[],"mode":"upsert_if_changed"}'
                  http://portal-api.$(cat /var/run/secrets/kubernetes.io/serviceaccount/namespace).svc.cluster.local/extract/field
YAML

cat > "$ROOT/k8s/base/cronjobs/cj-translate-run.yaml" <<'YAML'
apiVersion: batch/v1
kind: CronJob
metadata: { name: cj-translate-run }
spec:
  schedule: "*/20 * * * *"
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: curl
              image: curlimages/curl:8.8.0
              env:
                - name: TOKEN
                  valueFrom: { secretKeyRef: { name: api-auth, key: API_BEARER_TOKEN } }
              command: ["sh","-lc"]
              args:
                - >
                  curl -sS -X POST
                  -H "Authorization: Bearer $TOKEN"
                  -H "Content-Type: application/json"
                  --data '{"limit":200,"source_lang":"ja_JP","target_lang":"en_US","entities":["field","view_common"]}'
                  http://portal-api.$(cat /var/run/secrets/kubernetes.io/serviceaccount/namespace).svc.cluster.local/translate/run
YAML

cat > "$ROOT/k8s/base/cronjobs/cj-chroma-package.yaml" <<'YAML'
apiVersion: batch/v1
kind: CronJob
metadata: { name: cj-chroma-package }
spec:
  schedule: "*/30 * * * *"
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: curl
              image: curlimages/curl:8.8.0
              env:
                - name: TOKEN
                  valueFrom: { secretKeyRef: { name: api-auth, key: API_BEARER_TOKEN } }
              command: ["sh","-lc"]
              args:
                - >
                  curl -sS -X POST
                  -H "Authorization: Bearer $TOKEN"
                  -H "Content-Type: application/json"
                  --data '{"entities":["field","view_common"],"lang":"ja","collections":{"field":"portal_field_ja","view_common":"portal_view_common_ja"},"limit":500}'
                  http://portal-api.$(cat /var/run/secrets/kubernetes.io/serviceaccount/namespace).svc.cluster.local/chroma/package
YAML

cat > "$ROOT/k8s/base/cronjobs/cj-chroma-upsert.yaml" <<'YAML'
apiVersion: batch/v1
kind: CronJob
metadata: { name: cj-chroma-upsert }
spec:
  schedule: "*/15 * * * *"
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: curl
              image: curlimages/curl:8.8.0
              env:
                - name: TOKEN
                  valueFrom: { secretKeyRef: { name: api-auth, key: API_BEARER_TOKEN } }
              command: ["sh","-lc"]
              args:
                - >
                  curl -sS -X POST
                  -H "Authorization: Bearer $TOKEN"
                  -H "Content-Type: application/json"
                  --data '{"collections":["portal_field_ja","portal_view_common_ja"],"limit":1000,"dry_run":false}'
                  http://portal-api.$(cat /var/run/secrets/kubernetes.io/serviceaccount/namespace).svc.cluster.local/chroma/upsert
YAML

# =====================================================================================
# K8s: OVERLAYS (dev)
# =====================================================================================
say "Scaffolding overlays/dev..."

cat > "$ROOT/k8s/overlays/dev/namespace.yaml" <<'YAML'
apiVersion: v1
kind: Namespace
metadata: { name: portal-dev }
YAML

cat > "$ROOT/k8s/overlays/dev/kustomization.yaml" <<'YAML'
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: portal-dev

resources:
  - ../../base
  - namespace.yaml

generatorOptions:
  disableNameSuffixHash: true

# Replace config/secret from base expectations
configMapGenerator:
  - name: api-config
    behavior: replace
    literals:
      - APP_ENV=dev
      - LOG_LEVEL=info
      - API_PORT=8000
      - DB_HOST=postgres
      - DB_PORT=5432
      - DB_NAME=portal
      - CHROMA_HOST=chroma
      - CHROMA_PORT=8000
      - CHROMA_COLLECTION_FIELD_JA=portal_field_ja
      - CHROMA_COLLECTION_VIEW_JA=portal_view_common_ja

secretGenerator:
  - name: api-auth
    behavior: replace
    literals:
      - DB_USER=portal
      - DB_PASSWORD=change-portal-pass
      - API_BEARER_TOKEN=dev-token
  - name: postgres-auth
    behavior: replace
    literals:
      - POSTGRES_PASSWORD=change-postgres-pass
      - ODOO_DB_USER=odoo
      - ODOO_DB_PASSWORD=change-odoo-pass
      - PORTAL_DB_USER=portal
      - PORTAL_DB_PASSWORD=change-portal-pass

patchesStrategicMerge:
  - patch-ingress-hosts.yaml
  - patch-api-image.yaml
YAML

cat > "$ROOT/k8s/overlays/dev/patch-ingress-hosts.yaml" <<'YAML'
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata: { name: odoo }
spec:
  rules:
    - host: odoo.dev.example.com
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata: { name: portal-api }
spec:
  rules:
    - host: api.dev.example.com
YAML

cat > "$ROOT/k8s/overlays/dev/patch-api-image.yaml" <<'YAML'
apiVersion: apps/v1
kind: Deployment
metadata: { name: portal-api }
spec:
  template:
    spec:
      containers:
        - name: api
          image: your-registry/portal-api:dev
YAML

# =====================================================================================
# K8s: OVERLAYS (prod)
# =====================================================================================
say "Scaffolding overlays/prod..."

cat > "$ROOT/k8s/overlays/prod/namespace.yaml" <<'YAML'
apiVersion: v1
kind: Namespace
metadata: { name: portal-prod }
YAML

cat > "$ROOT/k8s/overlays/prod/kustomization.yaml" <<'YAML'
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: portal-prod

resources:
  - ../../base
  - namespace.yaml

generatorOptions:
  disableNameSuffixHash: true

configMapGenerator:
  - name: api-config
    behavior: replace
    literals:
      - APP_ENV=prod
      - LOG_LEVEL=info
      - API_PORT=8000
      - DB_HOST=postgres
      - DB_PORT=5432
      - DB_NAME=portal
      - CHROMA_HOST=chroma
      - CHROMA_PORT=8000
      - CHROMA_COLLECTION_FIELD_JA=portal_field_ja
      - CHROMA_COLLECTION_VIEW_JA=portal_view_common_ja

secretGenerator:
  - name: api-auth
    behavior: replace
    literals:
      - DB_USER=portal
      - DB_PASSWORD=***REDACTED***
      - API_BEARER_TOKEN=***REDACTED***
  - name: postgres-auth
    behavior: replace
    literals:
      - POSTGRES_PASSWORD=***REDACTED***
      - ODOO_DB_USER=odoo
      - ODOO_DB_PASSWORD=***REDACTED***
      - PORTAL_DB_USER=portal
      - PORTAL_DB_PASSWORD=***REDACTED***

patchesStrategicMerge:
  - patch-ingress-aws.yaml
  - patch-hpa.yaml
  - patch-storageclass.yaml
  - patch-irsa.yaml
  - patch-api-image.yaml
YAML

cat > "$ROOT/k8s/overlays/prod/patch-ingress-aws.yaml" <<'YAML'
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: portal-api
  annotations:
    kubernetes.io/ingress.class: alb
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/target-type: ip
    alb.ingress.kubernetes.io/certificate-arn: arn:aws:acm:REGION:ACCOUNT:certificate/XXXX
spec:
  rules:
    - host: api.example.com
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: odoo
  annotations:
    kubernetes.io/ingress.class: alb
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/target-type: ip
    alb.ingress.kubernetes.io/certificate-arn: arn:aws:acm:REGION:ACCOUNT:certificate/YYYY
spec:
  rules:
    - host: odoo.example.com
YAML

cat > "$ROOT/k8s/overlays/prod/patch-hpa.yaml" <<'YAML'
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata: { name: portal-api }
spec:
  minReplicas: 4
  maxReplicas: 10
YAML

cat > "$ROOT/k8s/overlays/prod/patch-storageclass.yaml" <<'YAML'
apiVersion: apps/v1
kind: StatefulSet
metadata: { name: postgres }
spec:
  volumeClaimTemplates:
    - metadata: { name: data }
      spec:
        storageClassName: gp3
        resources: { requests: { storage: 100Gi } }
---
apiVersion: apps/v1
kind: StatefulSet
metadata: { name: chroma }
spec:
  volumeClaimTemplates:
    - metadata: { name: data }
      spec:
        storageClassName: gp3
        resources: { requests: { storage: 50Gi } }
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata: { name: odoo-filestore }
spec:
  storageClassName: gp3
  resources: { requests: { storage: 100Gi } }
YAML

cat > "$ROOT/k8s/overlays/prod/patch-irsa.yaml" <<'YAML'
apiVersion: v1
kind: ServiceAccount
metadata:
  name: portal-api
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::123456789012:role/portal-api-irsa
YAML

cat > "$ROOT/k8s/overlays/prod/patch-api-image.yaml" <<'YAML'
apiVersion: apps/v1
kind: Deployment
metadata: { name: portal-api }
spec:
  template:
    spec:
      containers:
        - name: api
          image: your-registry/portal-api:1.0.0
YAML

# =====================================================================================
# (追加) あなたの初期情報を反映した「定義だけ」のファイル出力
#  - infra/postgres: dev ユーザーで DB=devportal、パスワード change-postgres-pass
#  - odoo/odoo-config: db_password=change-odoo-pass, admin_passwd=change-admin-pass
# =====================================================================================
say "Writing k8s/infra/postgres/statefulset.yaml"
cat > "$ROOT/k8s/infra/postgres/statefulset.yaml" <<'YAML'
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
  namespace: infra
spec:
  serviceName: postgres
  replicas: 1
  selector: { matchLabels: { app: postgres } }
  template:
    metadata: { labels: { app: postgres } }
    spec:
      containers:
      - name: db
        image: postgres:16
        ports: [{ name: pg, containerPort: 5432 }]
        env:
        - { name: POSTGRES_DB, value: devportal }
        - { name: POSTGRES_USER, value: dev }
        - { name: POSTGRES_PASSWORD, value: change-postgres-pass }
        volumeMounts:
        - { name: data, mountPath: /var/lib/postgresql/data }
  volumeClaimTemplates:
  - metadata: { name: data }
    spec:
      accessModes: ["ReadWriteOnce"]
      resources: { requests: { storage: 5Gi } }
YAML

say "Writing k8s/infra/postgres/service.yaml"
cat > "$ROOT/k8s/infra/postgres/service.yaml" <<'YAML'
apiVersion: v1
kind: Service
metadata:
  name: postgres
  namespace: infra
spec:
  selector: { app: postgres }
  ports:
    - { name: pg, port: 5432, targetPort: 5432 }
YAML

say "Writing k8s/odoo/odoo-configmap.yaml"
cat > "$ROOT/k8s/odoo/odoo-configmap.yaml" <<'YAML'
apiVersion: v1
kind: ConfigMap
metadata:
  name: odoo-config
  namespace: odoo
data:
  odoo.conf: |
    [options]
    ; --- DB 接続（infra の Postgres を利用）---
    db_host = postgres.infra.svc.cluster.local
    db_port = 5432
    db_user = odoo
    db_password = change-odoo-pass
    db_name = odoo

    ; --- Ingress 経由での動作に必要 ---
    proxy_mode = True

    ; --- DEV向け(単一プロセス) ---
    workers = 0

    ; --- 任意（DB管理画面で必要。開発だけで使う想定）---
    admin_passwd = change-admin-pass
YAML

# =====================================================================================
# Helper scripts (applyはしない想定の雛形だけ残す)
# =====================================================================================
cat > "$ROOT/scripts/apply_dev.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
kubectl apply -k k8s/overlays/dev
SH
chmod +x "$ROOT/scripts/apply_dev.sh"

cat > "$ROOT/scripts/apply_prod.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
kubectl apply -k k8s/overlays/prod
SH
chmod +x "$ROOT/scripts/apply_prod.sh"

say "Bootstrap complete (files & folders only)."
