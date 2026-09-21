# V2 모델 서버 구현 및 실행 인계

작성일: 2026-09-21. 이 문서는 9월 16일의 계약 전달 문서 이후 구현 상태를 설명합니다. 계약 원본은 유지했으며 과거 문서의 “V2 서버 미구현”은 당시 상태입니다.

## 백엔드 요청 10개 항목

| 요청 | 적용 상태 |
| --- | --- |
| PlanningAgentService.ProcessTurn 및 HealthCheck | 구현. 무상태 처리, 코드 기반 필수값·단계·읽기 전용·정정·재확인 검증 |
| DraftImageService.GenerateDraft 및 HealthCheck | 구현. 초안별 독립 호출, A/B/C 및 1·2회차 |
| 동일한 hotel_ad_v2.proto | 전달 원본과 동일. package/service/field 번호 변경 없음 |
| 1024×1024 PNG bytes | 입력 사진 검증 → 배경 → 서버 한글 합성 → PNG bytes |
| 구조화 오류 | google.rpc.Status.details의 ModelErrorDetail, grpc-status-details-bin |
| 0.0.0.0:50051 | V2 실행기 기본값. 호스트 테스트 포트는 Docker에서 15051 |
| llm-service | 기본 및 백엔드 연결용 compose 서비스명 |
| 송수신 32MiB | 서버와 예제 클라이언트 각각 33,554,432 bytes |
| 환경변수·Docker 방법 | 아래 및 README에 제공 |
| 저장소 단독 HealthCheck·실제 요청 | 실제 로컬 gRPC 서버의 fake 모드 성공. 실제 GCP 모델·유료 이미지와 Docker 컨테이너 실행 검증은 남음 |

## 모드 구분

`fake`는 정해진 JSON 필드 입력, 숙소 유형 단답, 문구 추천·번호 선택·`문구:` 입력만 지원합니다. 일반 한국어 입력은 추출된 것처럼 꾸미지 않고 모호 응답을 반환합니다. 생성 이미지는 원본 사진에 문구를 합성하며 FAKE 표시가 있습니다. API 키나 GPU가 필요하지 않습니다.

`live`는 모델 서비스가 vLLM `/v1/models`, `/tokenize`, `/v1/chat/completions`를 호출하고 이미지 서비스는 OpenAI 이미지 편집 API를 호출합니다. 실제 모델이 요청 JSON Schema와 Qwen non-thinking 옵션을 지원해야 합니다. 통신 실패 시 fake로 대체하지 않습니다.

두 모드 모두 gRPC 규격과 상태 처리 코드를 공유합니다. fake 테스트 성공은 한국어 모델 정확도나 이미지 생성 품질의 증거가 아닙니다. 실제 SDK의 HTTP 요청·응답 파싱·오류 매핑은 로컬 HTTP 테스트 서버로 검증했습니다.

## 환경변수

| 이름 | 기본값 | 의미 |
| --- | --- | --- |
| MODEL_MODE | fake | fake 또는 live, 자동 fallback 없음 |
| GRPC_HOST | 0.0.0.0 | Python 서버 bind 주소 |
| PORT | 50051 | 서버 포트. compose 내부 포트는 50051 고정 |
| VLLM_BASE_URL | Python: http://127.0.0.1:8000/v1; Docker: http://host.docker.internal:8000/v1 | 컨테이너에서 실제 접근 가능한 vLLM 주소 |
| VLLM_MODEL | hotel-agent | vLLM --served-model-name과 일치 |
| VLLM_API_KEY | EMPTY | vLLM 인증이 있으면 서버와 같은 값 |
| VLLM_CONTEXT_TOKENS | 12288 | 실제 vLLM max-model-len과 일치시킬 전체 문맥 한도 |
| VLLM_TIMEOUT_SECONDS | 25 | 토큰 계산과 추론 요청에 사용되는 시간 예산, 최대 25 |
| OPENAI_API_KEY | 빈 값 | live 이미지 생성용, 사용자 환경에만 설정 |
| IMAGE_MODEL | gpt-image-2 | 기존 프로젝트 이미지 모델 |
| IMAGE_TIMEOUT_SECONDS | 150 | 이미지 API 요청 timeout, 최대 150 |
| BACKEND_DOCKER_NETWORK | fastapi-backend_default | 백엔드 연결용 compose에서만 사용 |

이미지 품질은 medium, 출력은 1024×1024 PNG로 명시했습니다. provider 자동 재시도는 0회입니다. 타임아웃 등 실행 여부가 불확실한 오류는 retryable=false로 처리합니다. 서버는 요청·회차를 저장하지 않으므로 백엔드의 중복 방지와 결과 재사용이 필요합니다.

채팅 문맥은 실제 vLLM 토크나이저로 측정합니다. 최근 대화 12개 상한과 8,000토큰 상한을 적용하고 전체 문맥에서 출력·템플릿 여유를 남겨 오래된 기록부터 줄입니다. 최대 출력은 1,536토큰, 예약 공간은 2,048토큰입니다. 실제 템플릿·GPU 설정은 GCP에서 검증해야 합니다.

설계 문서의 길이 제한을 현재 검증기에 적용했습니다(숙소명 100, 지역 200, 장점 1개당 100/최대5개, 대상100, 분위기100, 색상100, 문구60 등). 이 제한을 바꾸려면 모델·백엔드 검증 기준을 함께 맞춥니다.

## HealthCheck의 의미

- fake 채팅: 로컬 엔진 준비 상태.
- live 채팅: 유료 생성 없이 vLLM 모델 목록에서 설정한 모델 존재 확인.
- 이미지: 한글 폰트 로딩 가능 여부, live에서는 API 키·모델 설정 존재 여부. **OpenAI 인증·잔액·모델 사용 권한·실제 생성 성공을 보장하지 않음.**
- 이미지 장애가 채팅 상태를 바꾸지 않도록 서비스별 응답을 사용합니다. Docker healthcheck는 두 서비스가 모두 준비됐을 때 성공합니다.

## 검증 명령

```powershell
.venv-v2/Scripts/python.exe scripts/check_local.py
.venv-v2/Scripts/python.exe scripts/smoke_local.py
.venv-v2/Scripts/basedpyright.exe
```

Linux에서는 `.venv-v2/bin/python`, `.venv-v2/bin/basedpyright`를 사용합니다. Stub 생성은 `python scripts/generate_stubs.py`입니다. Windows JSON 파일의 기본 CP949 인코딩 차이 때문에 제공된 실행 도구는 PYTHONUTF8=1을 설정합니다. 이관한 계약 테스트 원본은 수정하지 않았습니다.

직접 compose 연동 검사:

```bash
docker compose config --quiet
docker compose up --build -d
docker compose exec llm-service python -m v2.healthcheck
docker compose exec llm-service python -m v2.smoke
```

`v2.smoke`는 fake 모드에서만 실행합니다. 실제 서버 프로세스에서 V1/V2 HealthCheck, 기획서 입력·문구 확정, 6개 PNG, 읽기 전용 오류를 검사합니다. 사진은 테스트에서 만든 합성 도형이며 실제 호텔/모델 생성물로 제시하지 않습니다. 로컬 결과는 `artifacts/local-smoke`에 저장합니다.

## 현재 확인하지 못한 것

1. 현재 Windows Docker Desktop의 Linux 엔진 파이프에 연결할 수 없어 컨테이너 build/up 검증을 하지 못했습니다. compose 두 구성의 문법 검증 및 Docker 없이 실제 Python gRPC 서버 검증은 수행했습니다.
2. GCP 드라이버·가용 VRAM·RAM·모델 로딩·실제 vLLM 응답·처리량은 원격 실행 전입니다.
3. 실제 OpenAI 생성과 비용, 실제 숙소 보존·이미지 품질은 미검증입니다. 이번 작업은 유료 호출을 하지 않았습니다.
4. 백엔드/프런트 저장·다시 생성 차감·사용자 전체 흐름은 각 저장소와 함께 통합 테스트해야 합니다.

## 사용자가 직접 할 첫 단계

VS Code로 기존 GCP VM에 접속한 뒤 이 프로젝트를 VM에 준비하고 다음을 실행합니다.

```bash
python3 scripts/check_gpu_environment.py
```

결과에서 GPU·가용 VRAM·드라이버·RAM·디스크·실행 도구를 확인한 뒤 실제 vLLM 설치 버전과 실행 옵션을 확정합니다. 접속 주소·비밀번호·개인키·OpenAI 키를 대화에 보낼 필요는 없습니다. 토큰이 없는 진단 결과만 있으면 다음 준비가 가능합니다.

Docker와 vLLM을 같은 VM에서 사용할 경우 컨테이너의 127.0.0.1은 VM 호스트가 아닙니다. 실제 reachable한 내부 주소와 인증을 설정해야 합니다. 포트를 인터넷에 공개할 필요는 없습니다.
