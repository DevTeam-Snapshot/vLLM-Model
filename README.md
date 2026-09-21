# Hotel Advertisement Model Server V2

숙소 광고 기획용 채팅과 A/B/C 광고 이미지를 처리하는 무상태 gRPC 모델 서버입니다. 백엔드는 인증·기획서 저장·사진 정규화·작업 잠금·결과 저장·다시 생성 횟수를 관리합니다.

## 현재 상태

- 확정된 `proto/hotel_ad_v2.proto` 원본을 그대로 사용합니다.
- `PlanningAgentService.ProcessTurn/HealthCheck`, `DraftImageService.GenerateDraft/HealthCheck`를 구현했습니다.
- 기본 리스너 `0.0.0.0:50051`, Docker 서비스명 `llm-service`, gRPC 송수신 각각 32MiB입니다.
- 기본 `MODEL_MODE=fake`는 유료 호출 없이 연동을 확인합니다. 생성물에 `FAKE / LOCAL TEST` 표시가 있습니다. 자연어 모델의 품질 검증을 대신하지 않습니다.
- `MODEL_MODE=live`는 vLLM 채팅 추론과 OpenAI 이미지 API를 사용합니다. **GCP에서 실제 모델 실행·품질·비용은 아직 검증 전입니다.**
- V2 실행기는 V1 서비스도 함께 등록합니다. 기존 `grpc_server.py`, `Dockerfile.grpc`는 V1 전용 진입점으로 보존했습니다.

## 단독 Docker 실행

```bash
docker compose up --build -d
docker compose exec llm-service python -m v2.healthcheck
docker compose exec llm-service python -m v2.smoke
```

마지막 명령은 **fake 모드 전용** 연동 검사입니다. 컨테이너 안에 샘플 PNG를 저장합니다. 기본 compose는 백엔드 네트워크가 없어도 실행됩니다. 호스트 접근 주소는 `127.0.0.1:15051`입니다.

백엔드의 기존 Docker 네트워크에 연결할 때는 `.env`에 `BACKEND_DOCKER_NETWORK`를 지정하고 아래 구성을 대신 사용합니다.

GCP의 live 구성은 같은 Docker 네트워크에 `vllm` 컨테이너를 함께 실행합니다. `llm-service`는 `http://vllm:18080/v1`로 Qwen에 요청하며, vLLM의 `18080`은 호스트에 게시되지 않습니다. 따라서 호스트의 JupyterHub `8000`과 충돌하지 않습니다. 백엔드가 사용하는 주소는 계속 `llm-service:50051`이고, 호스트 테스트 주소도 `127.0.0.1:15051`로 유지됩니다.

```bash
MODEL_MODE=live docker compose -f docker-compose.grpc.yml up --build -d
```

백엔드는 같은 네트워크에서 `llm-service:50051`을 호출합니다. 네트워크는 백엔드에서 먼저 생성되어 있어야 하며, 실제 이미지 생성에는 `.env`의 `OPENAI_API_KEY`가 필요합니다.

## Docker 없는 로컬 검증

Python 3.12와 uv 기준입니다. Windows PowerShell:

```powershell
uv venv .venv-v2 --python 3.12
uv pip install --python .venv-v2/Scripts/python.exe -r requirements-dev.txt
.venv-v2/Scripts/python.exe scripts/check_local.py
.venv-v2/Scripts/python.exe scripts/smoke_local.py
```

Linux에서는 실행 파일 경로를 `.venv-v2/bin/python`으로 바꿉니다. `check_local.py`가 V1/V2 Stub을 생성하고 전체 테스트를 실행합니다. `smoke_local.py`는 실제 gRPC 서버를 임시 포트에 띄워 요청하고 종료하며 비용이 발생하지 않습니다.

서버를 계속 실행하려면 Stub 생성 후 다음을 사용합니다.

```powershell
.venv-v2/Scripts/python.exe scripts/run_model.py
```

환경변수는 실행 터미널에서 설정합니다. 이 Python 진입점은 `.env`를 자동으로 읽지 않으며 Docker Compose만 `.env`를 읽습니다.

## 문서

- [이번 구현 상태·백엔드 10개 항목·사용자 다음 단계](docs/v2-runtime-handoff.md)
- [원본 proto·Stub 생성·호출 안내](docs/v2-proto-handoff.md)
- [승인된 의미 계약과 상태 전이](docs/v2-api-contract-examples.md)
- [GCP GPU 확인 자료](docs/v2-gpu-environment.md)
- [라이선스를 포함한 한글 폰트](assets/fonts/README.md)

출력은 숙소명·확정 문구가 합성된 1024×1024 PNG bytes입니다. 저장 경로·URL·DB는 모델 서버가 관리하지 않습니다. 실제 이미지 생성은 비용이 발생하며, HealthCheck는 유료 생성을 호출하지 않습니다.
