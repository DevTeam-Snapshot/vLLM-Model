# Git push → SSH 배포 → live 테스트

V2 live에서 Qwen/vLLM은 기획 대화를 처리합니다. OpenAI는 사진의 자르기 중심, 문구 위치, 그라데이션 농도와 세 번째 후보의 비율을 추천합니다. Pillow는 제한적인 사진 보정과 확정 문구 합성을 수행합니다. OpenAI에 사진을 다시 그리게 하지 않습니다. 1번은 원본 비율, 2번은 정사각형, 3번은 AI 추천입니다.

## 1. 로컬 VS Code PowerShell

프로젝트 폴더에서 실행합니다. `.env`와 사진·출력물은 올리지 않습니다.

```powershell
git status --short
git add README.md .env.example docker-compose.yml requirements-v2-server.txt proto/hotel_ad_v2.proto v2 docs tests/test_v2_photo_layout.py tests/test_v2_draft_provider.py tests/test_v2_photo_rpc.py tests/test_v2_vision.py tests/test_v2_vision_composition.py tests/test_v2_live_check.py
git --no-pager diff --cached --stat
git commit -m "Add OpenAI Vision advertisement layout planning"
git push origin main
```

`--no-pager`는 로그 보기 화면에 들어가지 않게 합니다. 일반 로그 화면에서는 `q`로 나옵니다. 다른 브랜치에서 작업 중이면 실제 배포 브랜치에 맞춰 push/pull 대상을 변경하세요.

## 2. SSH 접속과 코드 갱신

아래 사용자명·서버주소·프로젝트 경로는 실제 값으로 바꿉니다. 이미 VS Code Remote SSH로 접속했다면 SSH 명령은 생략합니다.

```bash
ssh 사용자명@서버주소
cd /실제/프로젝트/경로/vLLM-Model
git status --short
git pull --ff-only origin main
```

추적 파일에 서버 측 수정이 있거나 pull이 거절되면 해당 변경부터 정리합니다. 강제 초기화하지 마세요.

## 3. 서버의 .env 설정

기존 `.env`는 유지하면서 다음 값을 수정하거나 추가합니다. 파일이 없다면 `.env.example`을 복사해 만듭니다.

```bash
test -f .env || cp .env.example .env
nano .env
```

```dotenv
MODEL_MODE=live
OPENAI_API_KEY=학원에서_발급받은_실제_API_키
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_VISION_MODEL=gpt-4.1-mini
OPENAI_VISION_TIMEOUT_SECONDS=60
BACKEND_DOCKER_NETWORK=fastapi-backend_default
```

`nano` 저장은 Ctrl+O, Enter, 종료는 Ctrl+X입니다. 키는 서버 `.env`에만 입력하고 Git에 올리지 않습니다. 학원에서 별도 프록시 주소나 허용 모델을 지정했다면 그 설정을 사용해야 합니다. `docker network ls`로 실제 백엔드 네트워크 이름을 확인해 일치시키세요. 기존 vLLM 설정은 유지합니다.

## 4. 빌드와 실행

```bash
docker compose -f docker-compose.grpc.yml config --quiet
MODEL_MODE=live docker compose -f docker-compose.grpc.yml up --build -d
docker compose -f docker-compose.grpc.yml ps
docker compose -f docker-compose.grpc.yml logs -f vllm
```

vLLM이 준비되면 Ctrl+C로 로그 보기만 종료합니다. 컨테이너는 계속 실행됩니다.

```bash
docker compose -f docker-compose.grpc.yml exec llm-service python -m v2.healthcheck
```

HealthCheck 성공만으로 OpenAI 키의 실제 인증·모델 접근이 확인되지는 않습니다. 다음 단계가 실제 호출 검사입니다.

## 5. fake 없이 실제 사진 테스트

서버에 있는 호텔 사진 경로를 아래 `/실제/사진/경로/hotel.jpg` 대신 입력합니다. 원본은 변경하지 않습니다. 검사 도구가 방향을 정규화하고 최대 2048px로 맞춰 RPC에 전달합니다.

```bash
docker compose -f docker-compose.grpc.yml cp /실제/사진/경로/hotel.jpg llm-service:/tmp/hotel.jpg
docker compose -f docker-compose.grpc.yml exec llm-service python -m v2.live_check /tmp/hotel.jpg /app/artifacts/live-check
mkdir -p artifacts/live-check
docker compose -f docker-compose.grpc.yml cp llm-service:/app/artifacts/live-check/. ./artifacts/live-check/
docker compose -f docker-compose.grpc.yml logs --tail=100 llm-service
```

이 도구는 live 설정과 키를 요구하며 Qwen 기획 요청 1회, OpenAI 분석을 포함한 이미지 요청 3회를 수행합니다. 결과의 `layout_provider=openai` 메타데이터도 검사해 구버전이나 fake 결과를 성공으로 취급하지 않습니다. API 사용량이 발생합니다.

`PASS` 메시지들과 결과 폴더가 출력됩니다. `artifacts/live-check/<실행별 ID>/candidate-1.png`, `candidate-2.png`, `candidate-3.png`를 VS Code에서 열어 확인하세요. 1번은 원본 비율, 2번은 1024×1024, 3번은 둘 중 하나이며 문구는 사진 안에 겹칩니다. 서버 로그에는 `openai_layout_applied`가 남습니다.

401/403이면 키·프로젝트·모델 권한을 확인하고, 429이면 해당 키의 한도·사용량을 확인합니다. 오류 시 fake로 바꾸지 않습니다. 이 검사는 모델 서버 직접 호출이므로 이후 React → Backend 전체 흐름에서도 세 후보를 확인해야 합니다. 백엔드의 고정 정사각형 검증은 제거하고 실제 이미지 크기를 보존해야 합니다.

## 검증 범위와 근거

로컬 자동 검사는 실제 gRPC 서버 프로세스와 SDK를 실행하지만 외부 OpenAI/vLLM 대신 로컬 HTTP 응답을 사용합니다. 실제 학원 키·GPU·사진에 대한 검증은 위 서버 명령으로 수행합니다.

- [OpenAI 이미지 분석 입력](https://developers.openai.com/api/docs/guides/images-vision)
- [구조화 출력](https://developers.openai.com/api/docs/guides/structured-outputs)
- [기본 분석 모델 GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini)
