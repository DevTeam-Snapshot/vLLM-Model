# V2 구현 검증 기록

작성일: 2026-09-21

## 계획 결과

1. 완료: 다른 PC의 V2 문서·proto·예제·의존성·계약 테스트·GPU 스크립트·기존 전달 ZIP 이관.
2. 완료: 무상태 채팅 엔진, vLLM 어댑터, 이미지 API 어댑터·한글 합성, V2 서비스 등록 구현.
3. 완료: 기본 단독 Compose 및 백엔드 네트워크 Compose, 환경변수, 실행/검증 도구와 안내 문서 작성.
4. 완료: 로컬 계약·회귀·HTTP 경계 테스트, 실제 Python gRPC 서버 smoke, 타입 및 린트 검사. Docker 컨테이너 실행은 Linux 엔진 연결 불가로 미검증.
5. 완료: GCP에서 사용자가 실행할 첫 진단 단계와 실제 모델 검증 범위를 v2-runtime-handoff.md에 정리.

## 관찰한 검증 결과

- `scripts/check_local.py`: 52 tests + 43 subtests 통과. 이 중 이관된 계약 테스트 7개는 fixture/가짜 gRPC 서버를 이용한 전송 규격 검사다.
- `scripts/smoke_local.py`: 별도 실제 서버 프로세스를 0.0.0.0의 임시 포트에서 실행. V1/V2 HealthCheck, V1 이미지 요청, 2턴 기획서 완료, A/B/C 2회차 총 6개 이미지, 읽기 전용 구조화 오류, 32MiB 초과 전송 거부 확인.
- 6개 이미지가 서로 다른 PNG이며 모두 1024×1024. 파일 디코딩 검증 및 대표 이미지의 한글 표시 육안 확인. 배경은 테스트 도형이며 실제 AI 생성 품질 검증이 아니다.
- vLLM 및 OpenAI SDK는 로컬 HTTP 테스트 서버로 요청 포맷·구조화 응답·토큰 한도·오류 매핑을 검증했다. 실제 provider/GPU에 요청하지 않았다.
- `basedpyright`: 새 V2 코드와 지정 실행 도구에 오류 0, 경고 0.
- `ruff check`: 새 V2 코드와 지정 실행 도구 통과.
- 기본 및 백엔드 연결용 `docker compose config --quiet` 통과.
- live 환경에서 fake 전용 smoke 명령이 네트워크 요청 전에 중단됨을 확인.
- 전달 원본과 현재 `proto/hotel_ad_v2.proto` SHA-256 일치: `21a6411d76ce447d6658d436757f7f46f5829e2bf3df408c496f60439c4b3e92`.

## 보존 및 제한

V1 proto·grpc_server.py·image_service.py는 기존 동작을 유지한다. 사용자가 이미 변경했던 Dockerfile.grpc는 덮어쓰지 않았다. Git commit/push, 원격 VM 접속, 유료 API 호출은 수행하지 않았다.

현재 Docker Linux 엔진에 연결할 수 없어 컨테이너 빌드/기동 결과를 주장하지 않는다. 실제 GCP 모델 로딩·한국어 품질·속도·실제 OpenAI 이미지 및 비용·백엔드 통합은 다음 검증 단계다.

## 최종 검토

별도 읽기 전용 코드 검토에서 기능을 막는 CRITICAL/HIGH 항목은 없었습니다. vLLM HTTP 요청 본문 검증 누락 지적은 `/tokenize`, `/v1/chat/completions`, model, JSON Schema, non-thinking 옵션과 상태 payload를 검사하는 테스트를 추가해 보완했습니다. 이미지 medium 품질 검사는 예산 관련 명시 동작이므로 유지했습니다. 실제 vLLM 버전 호환성은 여전히 GCP 검증 대상입니다.
