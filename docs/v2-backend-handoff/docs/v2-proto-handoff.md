# V2 최종 proto 및 백엔드 연동 안내

기준일: 2026-09-16. 백엔드의 계약 동의 및 최종 proto 작성 요청을 반영했습니다.

**현재 제공 범위는 최종 통신 규격, Stub 생성 방법, 호출·변환 예제입니다. 현재 `grpc_server.py`는 V1만 구현하고 있으므로 V2 호출 시 UNIMPLEMENTED가 정상입니다.** V2 모델 서버 구현·배포 및 GPU 연결은 다음 단계입니다. 여기서 검증한 서버는 유료 API를 사용하지 않는 로컬 가짜 서버입니다.

## 1. 전달 파일

| 파일 | 역할 |
| --- | --- |
| `proto/hotel_ad_v2.proto` | 최종 V2 계약. 외부 proto 의존은 protoc 기본 포함 `google/protobuf/empty.proto`뿐 |
| `requirements-v2-contract.txt` | 생성기·런타임·구조화 오류 패키지 버전 고정 |
| `examples/v2_client.py` | 비동기 HealthCheck·ProcessTurn·GenerateDraft 호출 예제 |
| `examples/v2_contract_codec.py` | 합의한 소문자 JSON과 protobuf 사이 변환, patch 및 revision 예제 |
| `docs/v2-api-contract-examples.md` | 상태 전이·업무 규칙 |
| `docs/examples/v2-contract-cases.json` | 의미 검토용 JSON fixture; protobuf JSON과 다름 |
| `tests/test_v2_contract.py` | 가짜 gRPC 서버로 전송과 예제 검증 |

V1 `hotel_ad_image.proto`는 변경하지 않았습니다. V2의 `hotel.adimage.v2` 패키지는 V1 및 엔진용 `vllm_engine.proto`와 독립입니다. 생성된 Stub 파일은 배포 환경에서 아래 명령으로 만드세요. 생성기와 실행 환경의 의존성 버전은 함께 맞춰야 합니다.

## 2. Stub 생성 명령

다음 명령은 저장소 루트 또는 전달 ZIP을 압축 해제한 루트에서 실행합니다. Python 3.12를 권장하며 고정 도구 조합은 로컬 Python 3.9에서도 검증했습니다.

```bash
python3 -m venv .venv-v2
source .venv-v2/bin/activate
python -m pip install -r requirements-v2-contract.txt
mkdir -p generated
python -m grpc_tools.protoc \
  -I proto \
  --python_out=generated \
  --pyi_out=generated \
  --grpc_python_out=generated \
  proto/hotel_ad_v2.proto
```

결과물은 `generated/hotel_ad_v2_pb2.py`, `generated/hotel_ad_v2_pb2.pyi`, `generated/hotel_ad_v2_pb2_grpc.py`입니다. 현재 예제는 generated 디렉터리를 PYTHONPATH에 추가하는 방식을 사용합니다. `from generated import ...`로만 변경하면 생성된 모듈 내부의 절대 import가 실패할 수 있으므로 패키징 방식을 임의로 섞지 마세요.

Python Stub 생성 방식의 공식 설명: [gRPC Python Basics](https://grpc.io/docs/languages/python/basics/).

## 3. RPC 주소와 제한

| 항목 | 값 |
| --- | --- |
| Docker 내부 주소 (V2 서버 등록 후) | `llm-service:50051` |
| 기존 호스트 포트 매핑 기준 | `127.0.0.1:15051` |
| 채팅 RPC | `/hotel.adimage.v2.PlanningAgentService/ProcessTurn` |
| 이미지 RPC | `/hotel.adimage.v2.DraftImageService/GenerateDraft` |
| 각 서비스 상태 확인 | `HealthCheck(google.protobuf.Empty)` |
| 채팅 / 이미지 초기 deadline | 30초 / 180초 |
| 송신·수신 한도 | 각 33,554,432 bytes (32MiB), 전체 메시지 기준 |
| 원본 업로드 한도 | FastAPI에서 25MiB, 60MP |
| 모델 전달 입력 | FastAPI 정규화 후 25MiB 이하, 20MP 이하, JPEG/PNG/정적 WebP |
| 출력 | 합성 완료된 1024×1024 PNG, 25MiB 이하 |

20MP 초과 원본 축소·EXIF 방향·색상 처리는 FastAPI에서 수행합니다. 모델 서버는 전달 파일을 다시 검증합니다. 포트는 내부망 또는 SSH 터널로 접근하는 기준입니다. 이 문서는 포트를 외부에 공개하거나 컨테이너를 실행하지 않습니다.

## 4. 기본 호출 예제

채팅은 코드에 포함된 초기 Form과 한 사용자 답변을 보내는 단일 턴 예제입니다. 실제 백엔드는 React에서 받은 최신 임시 상태와 FastAPI가 확인한 사진 상태로 요청을 구성합니다.

```bash
PYTHONPATH=generated:examples python examples/v2_client.py health \
  --target 127.0.0.1:15051

PYTHONPATH=generated:examples python examples/v2_client.py chat \
  --target 127.0.0.1:15051 --session-id session-example
```

모델 입력용으로 이미 정규화한 PNG 파일을 준비한 경우:

```bash
PYTHONPATH=generated:examples python examples/v2_client.py image \
  --target 127.0.0.1:15051 \
  --session-id session-example --draft-id draft-r1-a \
  --direction room --generation-round 1 \
  --image /absolute/path/normalized.png --output /absolute/path/draft-a.png
```

`/absolute/path/...`는 실제 파일 경로로 바꿉니다. 이 예제는 저장된 기획서를 조회하지 않고 샘플 brief를 사용합니다. 실제 서버에 이미지 호출을 보내면 생성 API 비용이 발생할 수 있습니다. 같은 결과 파일은 덮어쓰지 않습니다. 서버가 V2를 제공하기 전에는 위 호출이 성공하지 않습니다.

FastAPI의 호출 핵심은 다음과 같습니다.

```python
import grpc
import hotel_ad_v2_pb2_grpc as rpc
from v2_contract_codec import turn_from_domain, turn_response_to_domain

async def process_turn(domain_request):
    options = [
        ("grpc.max_send_message_length", 32 * 1024 * 1024),
        ("grpc.max_receive_message_length", 32 * 1024 * 1024),
    ]
    async with grpc.aio.insecure_channel("llm-service:50051", options=options) as channel:
        request = turn_from_domain(domain_request)
        response = await rpc.PlanningAgentServiceStub(channel).ProcessTurn(request, timeout=30)
        return turn_response_to_domain(response)
```

애플리케이션에서는 채널을 FastAPI lifespan에서 생성·재사용할 수 있습니다. 반환 전 요청 ID·세션 ID·revision 일치를 검사하고, React는 최신 revision과 일치하는 응답만 원자적으로 반영합니다. `apply_turn_response` 예제가 해당 검사를 보여줍니다. 무상태 모델 서버가 최신 revision을 기억한다고 가정하지 않습니다.

A·B·C를 병렬 호출할 때는 한 초안 실패가 다른 초안 성공 결과를 버리지 않도록 합니다.

```python
import asyncio

results = await asyncio.gather(
    *(draft_stub.GenerateDraft(request, timeout=180) for request in requests_abc),
    return_exceptions=True,
)
# requests_abc는 같은 확정 brief와 사진, 서로 다른 draft_id/direction을 가집니다.
# 각 결과를 요청과 대응시켜 따로 저장·상태 처리합니다.
# round 2는 세 장의 파일·DB 저장 성공 후에만 활성화하고 횟수를 차감합니다.
```

## 5. JSON과 protobuf 표현의 차이

숙소 유형은 **hotel, motel, resort, pension, other** 다섯 가지입니다. protobuf에는 미설정 센티널 `LODGING_TYPE_UNSPECIFIED=0`이 추가되지만 사용자 선택 항목이 아니며 유효한 답변으로 인정하지 않습니다. 게스트하우스 등은 `OTHER` + `lodging_type_detail`로 표현합니다.

| 의미 검토 JSON | protobuf / Python |
| --- | --- |
| `lodging_type: "hotel"` | `pb.LODGING_TYPE_HOTEL` |
| `current_step: "mood"` | `pb.PLANNING_STEP_MOOD` |
| `brief.ad_copy: null` | optional 필드 미설정, `HasField("ad_copy")==False` |
| `resume_step: null` | optional resume_step 미설정 |
| patch에 키 없음 | 해당 변경 메시지 없음: 값 유지 |
| patch `ad_copy: "문구"` | `ad_copy.set_value = "문구"` |
| patch `ad_copy: null` | `ad_copy.clear.SetInParent()` |
| patch `selling_points: []` | `selling_points.SetInParent()`, values는 비어 있음 |
| bytes 자리 표시자 | 실제 파일 bytes. ProtoJSON에서는 base64 |

아래는 **protobuf JSON 표기**의 patch 예시입니다. 기존 fixture의 JSON과 직접 혼용하지 않습니다.

```json
{
  "briefUpdates": {
    "lodgingType": {"setValue": "LODGING_TYPE_OTHER"},
    "lodgingTypeDetail": {"setValue": "게스트하우스"},
    "adCopy": {"clear": {}},
    "sellingPoints": {"values": []}
  }
}
```

표준 ProtoJSON은 camelCase 필드명, enum 이름, uint64의 문자열 표기를 사용합니다. 업무 JSON의 소문자 enum과 patch의 null을 그대로 ParseDict에 넣지 마세요. 제공된 codec을 통해 변환할 수 있습니다. codec은 업무 검증기 전체가 아니며 최종 필수값·길이·이미지·정정 규칙은 서버에서 검증해야 합니다.

특히 `state_revision=0`, `original_image_uploaded=false`, `is_regeneration=false`는 유효한 명시 값입니다. 이 필드는 optional로 정의해 누락과 구분했습니다. 수신 측은 필수 presence를 검사해야 합니다.

## 6. 서버에서 검증해야 하는 불변조건

- 모든 ID는 비어 있지 않아야 하며 enum 미설정·알 수 없는 값은 거부합니다.
- ProcessTurn의 brief, state_revision, original_image_uploaded는 반드시 전달합니다.
- 현재 단계 COMPLETE에서 ProcessTurn은 BRIEF_READ_ONLY를 반환합니다.
- user_message 이벤트는 비어 있지 않은 메시지, image_uploaded 이벤트는 빈 메시지와 업로드 true가 필요합니다.
- 사진 상태는 FastAPI가 소유권·파일 존재를 확인한 결과여야 합니다.
- 현재 요청 revision/current_step을 응답에 그대로 반환합니다. next_step에는 처리 후 단계를 반환합니다.
- 목록은 처리 후 전체 상태입니다. 완료와 미완료는 겹치지 않고 재확인은 미완료에 포함됩니다.
- `is_complete`는 next_step COMPLETE와 동치이며 모든 필수값이 유효하고 재확인이 없어야 합니다.
- 변경 메시지가 있으면 StringChange/LodgingTypeChange의 operation이 반드시 선택돼 있어야 합니다.
- ad_copy_candidates는 최대 3개이며 사용자의 선택 전에 ad_copy로 확정하지 않습니다.
- GenerateDraft는 확정 brief와 실제 사진을 받고, round 1/false 또는 round 2/true만 허용합니다.
- 모델은 횟수를 저장하지 않습니다. FastAPI가 실행 잠금·회차·최종 저장 성공·다시 생성 횟수를 관리합니다.

proto3 메시지 생성 성공은 위 조건 통과를 의미하지 않습니다. 필수값과 의미는 애플리케이션이 검증합니다. 세부 필드 길이 제한은 기존 설계 문서의 기준을 사용합니다.

## 7. 구조화 오류

`ModelErrorDetail(request_id, reason, retryable)`를 `Any`로 감싼 뒤 `google.rpc.Status.details`에 넣습니다. 실제 gRPC 코드는 `Status.code`와 일치해야 합니다. 전송은 `grpc-status-details-bin` trailer를 사용하며 grpcio-status가 인코딩·디코딩합니다.

```python
# 동기 gRPC 서버에서 오류 반환 예시
import grpc
from google.protobuf import any_pb2
from google.rpc import status_pb2
from grpc_status import rpc_status
import hotel_ad_v2_pb2 as pb

detail = pb.ModelErrorDetail(
    request_id=request.request_id, reason="BRIEF_INCOMPLETE", retryable=False
)
packed = any_pb2.Any()
packed.Pack(detail)
context.abort_with_status(rpc_status.to_status(status_pb2.Status(
    code=grpc.StatusCode.FAILED_PRECONDITION.value[0],
    message="Advertisement brief is incomplete", details=[packed]
)))
```

비동기 서버의 context에서는 abort_with_status를 await합니다. 클라이언트의 오류 복원은 `examples/v2_client.py`의 `explain_error`를 참고합니다. 전송 계층 실패는 trailer가 없을 수 있으며, 이 경우 기본적으로 자동 재시도하지 않고 실행 여부를 확인합니다.

| gRPC 코드 | reason | retryable |
| --- | --- | --- |
| INVALID_ARGUMENT | INVALID_EVENT, INVALID_GENERATION_ROUND, CONTEXT_TOO_LARGE, INVALID_ARGUMENT, INVALID_IMAGE | false |
| FAILED_PRECONDITION | BRIEF_READ_ONLY, BRIEF_INCOMPLETE, GENERATION_REJECTED | false |
| RESOURCE_EXHAUSTED | INPUT_TOO_LARGE | false |
| RESOURCE_EXHAUSTED | UPSTREAM_RATE_LIMIT, SERVER_BUSY | true |
| UNAVAILABLE | UPSTREAM_UNAVAILABLE (실행 전 실패 확인 시) | true |
| DEADLINE_EXCEEDED | RESULT_UNKNOWN | false |
| INTERNAL | MODEL_OUTPUT_INVALID, COMPOSITION_FAILED, OUTPUT_TOO_LARGE, INTERNAL_ERROR | false |
| CANCELLED | REQUEST_CANCELLED | false |

reason은 향후 오류 확장을 위해 string으로 두었습니다. 알려지지 않은 reason은 자동 재시도하지 않는 기본 처리를 권장합니다. 위 상세 분류는 합의된 오류 코드의 구현용 이름이며, 민감한 원본 provider 오류를 전달하지 않습니다. 명확히 재시도 가능한 시스템 오류에만 제한된 재시도를 적용하며 timeout을 성공하지 않은 것으로 단정하지 않습니다.

## 8. 검증 명령 및 결과

Stub 생성 후 다음을 실행합니다.

```bash
PYTHONPATH=generated:examples python -m unittest discover \
  -s tests -p test_v2_contract.py -v
```

로컬 loopback 임시 포트를 사용하는 가짜 서버이며 GPU나 OpenAI 키가 필요하지 않습니다. 가짜 이미지는 테스트 코드에서 만드는 1024×1024 PNG입니다.

검증 결과: 테스트 7개 통과. 내부적으로 채팅 22개, 이미지 6개, 구조화 오류 8개를 실제 로컬 gRPC로 왕복 검증했고 async 클라이언트의 health/chat/image 모드도 확인했습니다. patch 유지·설정·삭제·빈 배열, revision=0·false presence 보존, 오래된 응답 거부와 숙소 enum도 확인했습니다. V1/V2 proto 동시 컴파일도 통과했습니다.

검증하지 않은 항목: 실제 vLLM 추론, 모델의 상태 전이 판단 정확도, 실제 이미지 API·문구 합성, GCP 배포 연결, 프로덕션 처리량. 현재 계약 fixture 테스트는 이들을 대신하지 않습니다.
