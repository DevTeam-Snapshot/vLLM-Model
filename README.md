# vLLM Model Server

부트캠프 팀 프로젝트의 AI 모델 추론 서버입니다. Model 파트는 GCP GPU VM에서 vLLM을 운영하고, Backend는 OpenAI 호환 API로 모델을 호출합니다. Frontend는 Backend API만 호출하며 모델 서버에 직접 접속하지 않습니다.

기본 모델은 `Qwen/Qwen3-0.6B`이고, Backend에 노출되는 모델 이름은 `hotel-copy-llm`입니다.

## 실행 모드

| 모드 | 목적 | 접속 주소 | 사용 시점 |
| --- | --- | --- | --- |
| 개인 VM 검증 | Model 담당자가 GCP VM에서 모델을 빌드·테스트 | `http://localhost:18000` | 모델 변경 및 연동 전 점검 |
| 팀 Compose 통합 | Backend와 모델 서버가 같은 Docker Compose 네트워크에서 통신 | `http://llm-service:8000/v1` | 팀 통합 테스트 및 배포 |

`18000`은 VM의 loopback(`127.0.0.1`)에만 바인딩됩니다. 외부 IP에서 `VM_IP:18000`으로 접근할 수 없으며, 이것이 의도된 보안 설정입니다.

```text
개인 검증:  curl → VM localhost:18000 → vLLM 컨테이너:8000

팀 통합:    Frontend → Backend → llm-service:8000 → vLLM 컨테이너
                           └→ DB
```

## 서비스 사양

| 항목 | 값 |
| --- | --- |
| Hugging Face 모델 | `Qwen/Qwen3-0.6B` |
| Backend용 모델 이름 | `hotel-copy-llm` |
| 컨테이너 포트 | `8000` |
| 개인 VM 테스트 포트 | `127.0.0.1:18000` |
| 최대 컨텍스트 길이 | 2,048 토큰 |
| GPU 메모리 사용 한도 | 80% |

## 공통 사전 준비

GCP VM에는 NVIDIA GPU, NVIDIA 드라이버, Docker Engine, Docker Compose v2, NVIDIA Container Toolkit이 필요합니다. Docker에서 GPU 접근이 가능한지 먼저 확인합니다.

```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.9.0-base-ubuntu22.04 nvidia-smi
```

두 명령 모두 GPU 정보를 출력해야 합니다. vLLM의 Docker 실행 방식은 GPU와 host IPC 공유를 요구합니다. [vLLM Docker 안내](https://docs.vllm.ai/en/latest/getting_started/installation/gpu/)

### Docker 권한 설정

GCP VM의 일반 SSH 사용자는 Docker 소켓 권한이 없을 수 있습니다. `permission denied while trying to connect to the docker API at unix:///var/run/docker.sock` 오류가 나면 다음을 한 번 실행합니다.

```bash
sudo usermod -aG docker $USER
exit
```

SSH를 다시 접속한 후 권한을 확인합니다.

```bash
docker info
```

`docker` 그룹은 호스트의 root 수준 권한을 가질 수 있으므로, 승인된 팀원만 추가합니다. `chmod 666 /var/run/docker.sock`으로 권한을 전역으로 열지 않습니다.

## 1. 개인 GCP VM 검증

이 절은 Model 담당자가 모델 이미지를 만들고, VM 내부에서 API가 정상 응답하는지 확인하는 절차입니다.

### 1-1. 저장소와 환경 변수 준비

```bash
cd ~/vLLM-Model
cp .env.example .env
```

기본 모델은 공개 모델입니다. 접근 제한 모델을 사용하거나 Hugging Face 인증이 필요할 때만 `.env`에 토큰을 입력합니다.

```env
HF_TOKEN=hf_your_token_here
```

`.env`는 Git에서 제외되므로 토큰을 커밋하지 않습니다.

수동 `docker run` 명령은 `.env`를 자동으로 읽지 않으므로, 실행 전에 값을 현재 셸로 불러옵니다.

```bash
set -a
source .env
set +a
```

### 1-2. 이미지 빌드

```bash
docker build -t hotel-vllm:test .
```

### 1-3. 컨테이너 실행

```bash
docker run -d \
  --name hotel-vllm-test \
  --gpus all \
  --ipc=host \
  -p 127.0.0.1:18000:8000 \
  --env HF_TOKEN="${HF_TOKEN:-}" \
  -v "$HOME/.cache/huggingface:/root/.cache/huggingface" \
  hotel-vllm:test
```

첫 실행에서는 이미지와 모델 가중치를 내려받으므로 시간이 걸릴 수 있습니다. Hugging Face 캐시를 VM 홈 디렉터리에 마운트하므로 이후 실행 시 다시 내려받지 않습니다.

### 1-4. 모델 준비 확인

```bash
docker logs -f hotel-vllm-test
```

로그가 모델 로딩 완료를 보여주면 `Ctrl+C`로 로그 보기만 종료합니다. 컨테이너는 계속 실행됩니다. 최종 준비 상태는 로그 문구가 아니라 health check로 판단합니다.

```bash
curl -i http://localhost:18000/health
```

`HTTP/1.1 200 OK`가 나오면 준비 완료입니다.

### 1-5. 광고 문구 생성 API 확인

```bash
curl http://localhost:18000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "hotel-copy-llm",
    "messages": [
      {
        "role": "user",
        "content": "오션뷰와 수영장이 있는 호텔의 30퍼센트 할인 광고 문구를 한국어로 작성해줘."
      }
    ],
    "max_tokens": 200
  }'
```

성공 응답의 생성 결과는 `choices[0].message.content`에 있습니다.

### 1-6. Compose로 같은 개인 검증 실행하기

`docker-compose.yml`도 위 개인 검증과 동일하게 `hotel-vllm:test` 이미지와 `127.0.0.1:18000` 포트를 사용합니다.

```bash
docker compose up --build -d
docker compose logs -f llm-service
curl -i http://localhost:18000/health
```

수동 `docker run`과 Compose 방식은 동시에 실행하지 않습니다. 둘 다 같은 컨테이너 이름 또는 호스트 포트를 사용하기 때문입니다.

### 1-7. 로컬 PC에서 임시로 확인하기

VM 포트를 외부에 공개하지 않고 SSH 터널로 확인합니다.

```bash
gcloud compute ssh <VM_NAME> --zone <ZONE> -- -L 18000:localhost:18000
```

터널이 연결된 동안 로컬 PC에서 `http://localhost:18000/health` 또는 Chat Completions API를 호출합니다.

### 1-8. 종료와 정리

수동 실행 컨테이너를 종료·삭제합니다.

```bash
docker stop hotel-vllm-test
docker rm hotel-vllm-test
```

Compose 실행은 다음 명령으로 정리합니다. 모델 캐시는 유지됩니다.

```bash
docker compose down
```

`docker compose down -v`는 Compose가 만든 캐시 볼륨도 삭제하므로, 모델을 다시 내려받아야 할 때만 사용합니다.

## 2. 팀 Compose 통합

이 절은 팀장 또는 인프라 담당자가 **팀의 단일 Compose 파일**에 모델 서버를 포함할 때 사용합니다.

### 2-1. Docker Hub 이미지 발행

개인 VM에서 검증한 이미지를 고정 버전 태그로 Docker Hub에 발행합니다.

```bash
docker tag hotel-vllm:test <DOCKERHUB_ID>/hotel-vllm:<VERSION>
docker push <DOCKERHUB_ID>/hotel-vllm:<VERSION>
```

`latest` 대신 예를 들어 `0.1.0`처럼 고정 버전을 사용합니다. 이 명령을 실행하기 전에 `docker login`으로 Docker Hub에 로그인해야 합니다.

### 2-2. 팀 Compose 파일에 서비스 추가

팀의 Compose 파일에 아래 서비스를 추가합니다. `build:`와 host `ports:`는 넣지 않습니다. Backend와 모델 서버가 동일 Compose 네트워크에서 서비스 이름으로 통신하기 때문입니다.

```yaml
services:
  llm-service:
    image: <DOCKERHUB_ID>/hotel-vllm:<VERSION>
    gpus: all
    ipc: host
    environment:
      HF_TOKEN: ${HF_TOKEN:-}
    volumes:
      - hf-cache:/root/.cache/huggingface

  backend:
    # 기존 Backend 설정

volumes:
  hf-cache:
```

팀 Compose 파일에서는 `llm-service`와 `backend`가 같은 Compose 프로젝트 안에 있어야 합니다. 서로 다른 Compose 프로젝트라면 `llm-service`라는 이름은 해석되지 않으므로, 하나의 Compose 파일로 합치거나 명시적으로 공유 external network를 구성해야 합니다.

### 2-3. Backend 환경 변수

Backend는 다음 값을 사용합니다.

```env
MODEL_API_BASE_URL=http://llm-service:8000/v1
MODEL_API_MODEL=hotel-copy-llm
```

호출 주소는 다음과 같습니다.

```text
POST http://llm-service:8000/v1/chat/completions
```

Frontend는 이 주소와 Hugging Face 토큰을 사용하지 않습니다. Frontend는 Backend가 제공하는 API만 호출합니다. DB 저장 정책과 스키마는 Backend/DB 파트의 책임입니다.

## API 계약

Backend는 OpenAI 호환 Chat Completions API를 호출합니다.

```json
{
  "model": "hotel-copy-llm",
  "messages": [
    {"role": "user", "content": "서울 호텔을 추천해 주세요."}
  ],
  "temperature": 0.7,
  "max_tokens": 200
}
```

응답 생성 텍스트는 `choices[0].message.content`에서 읽습니다. 모델 서버 오류나 시간 초과는 Backend의 표준 오류 응답으로 변환합니다.

## 문제 해결

| 증상 | 확인 방법 |
| --- | --- |
| Docker 소켓 권한 오류 | `sudo usermod -aG docker $USER` 실행 후 SSH를 다시 접속하고 `docker info`를 확인합니다. |
| 컨테이너에서 GPU를 찾지 못함 | `docker run --rm --gpus all nvidia/cuda:12.9.0-base-ubuntu22.04 nvidia-smi`로 NVIDIA Container Toolkit 설정을 확인합니다. |
| `18000` 포트가 이미 사용 중 | 기존 `hotel-vllm-test` 컨테이너 또는 Compose 서비스를 중지한 후 하나의 방식만 실행합니다. |
| Backend에서 `llm-service`를 찾지 못함 | Backend와 모델 서비스가 같은 Compose 프로젝트/네트워크인지 확인합니다. |
| 모델 다운로드 실패 | VM 인터넷 연결, 디스크 여유 공간, 필요 시 `HF_TOKEN`과 모델 접근 권한을 확인합니다. |
| GPU 메모리 부족 | [Dockerfile](Dockerfile)의 `--gpu-memory-utilization` 또는 `--max-model-len` 값을 낮춘 뒤 이미지를 다시 빌드합니다. |

## 프로젝트 구조

```text
.
├── Dockerfile           # vLLM 이미지와 서버 시작 옵션
├── docker-compose.yml   # 개인 VM 검증용 Compose 설정
├── .env.example         # Hugging Face 토큰 예시
└── README.md            # 개인 검증 및 팀 통합 안내
```
