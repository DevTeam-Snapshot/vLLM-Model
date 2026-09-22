# V2 모델 서버 연동 규격 — 백엔드 회신 반영본

> 2026-09-16: 백엔드 회신의 확정 사항을 반영했습니다. 요청·응답 예시와 상태 전이 검토 후 최종 proto를 작성합니다. 구현 완료를 뜻하지 않습니다.

안녕하세요. 공유해 주신 V2 범위와 연동 제안을 검토했습니다.

모델 측에서는 **상태를 보관하지 않는 채팅 Agent + 초안별 독립 이미지 생성 RPC** 구조로 진행하는 안을 제안합니다. 질문 중 임시 상태는 React, 최종 데이터와 생성 작업 상태는 FastAPI·DB에서 관리하는 역할 분담에 동의합니다.

아래 내용은 구현 전 설계 제안입니다. 현재 V1에 있는 이미지 생성 기능 외에 채팅 Agent, 문구 합성, V2 RPC는 신규 구현 대상이며, 모델 품질·응답 시간·동시 처리량은 연동 전 실측하겠습니다. 필드와 동작을 먼저 합의한 뒤 `.proto`와 실행 예제를 전달하겠습니다.

## 1. 적용 범위와 역할

- 세션당 기획서 하나, 원본 사진 한 장을 사용합니다.
- 지정된 순서로 정보를 수집하며, 완료 전에는 채팅으로 이전 값을 정정할 수 있습니다.
- 완성된 기획서는 읽기 전용이며, 사용자의 최종 확인 후 저장하고 A·B·C를 생성합니다.
- A·B·C는 광고 문구와 이미지가 합쳐진 PNG로 반환합니다.
- 완성 기획서 수정과 초안 직접 편집은 V2에서 제외합니다.
- 다시 생성은 세션당 성공 기준 한 번이며, 횟수·회차·저장·선택·부분 실패 관리는 FastAPI가 담당합니다.
- 모델 서버는 DB를 직접 쓰거나 이미지 URL을 발급하지 않습니다. 원본은 FastAPI가 검증한 파일 bytes로 받습니다.

## 2. 모델과 실행 방식

**업데이트:** 팀은 채팅 Agent의 vLLM 도입을 희망합니다. FastAPI와 모델 서비스의 gRPC 계약은 유지하고 내부 추론 제공자를 교체하는 방향입니다. GPU·VRAM·OS 확인 후 모델과 배포 구성을 결정합니다. 아래 외부 API 방식은 최초 제안 이력과 비교 기준이며 자동 유료 fallback을 뜻하지 않습니다.

채팅 Agent의 초기 검증 후보는 **OpenAI API의 `gpt-4.1-mini-2025-04-14`**로 제안합니다. 한국어 슬롯 추출과 정정 처리에 대한 테스트를 통과한 뒤 채택하며, 최종 모델명은 환경변수로 분리하겠습니다. 최신 모델 또는 최저 비용 모델이라는 의미의 선정은 아닙니다.

해당 모델은 Structured Outputs를 지원합니다. JSON Schema에 맞춘 추출 결과를 받은 뒤 Python에서 값, 변경 허용 필드, 단계 전이 조건을 다시 검증하겠습니다. 스키마 일치가 사실 정확성이나 업무 규칙 준수를 보장하지는 않으므로 두 검증을 분리합니다. [모델 공식 문서](https://developers.openai.com/api/docs/models/gpt-4.1-mini), [구조화된 출력 공식 문서](https://developers.openai.com/api/docs/guides/structured-outputs)

이미지 모델은 V1의 **`gpt-image-2` 이미지 편집 방식**을 우선 유지합니다. 공식 문서에도 이미지 편집 엔드포인트가 안내되어 있습니다. 모델 교체는 V2 필수 범위에 넣지 않고, 실제 사진 보존과 결과 품질을 확인하겠습니다. [이미지 모델 공식 문서](https://developers.openai.com/api/docs/models/gpt-image-2)

실행은 Python gRPC 서버가 외부 API를 호출하는 방식으로 제안합니다. 초기안에는 GPU·자체 vLLM 서빙·별도 Agent 프레임워크가 필요하지 않습니다. API 계정의 모델 접근 권한과 호출 한도는 실제 배포 계정에서 확인해야 합니다.

## 3. 기획서 필드와 완료 기준

숙소 유형 enum은 확정되었으며 나머지 세부 길이 제한은 합의용 제안입니다. 문자열 길이는 Unicode 문자 수로 계산합니다.

| 필드 | 자료형·제안 제한 | 완료 기준 |
| --- | --- | --- |
| `lodging_type` | enum: `hotel`, `motel`, `pension`, `resort`, `other` | 사용자가 유형을 명시. 미분류 유형은 원래 명칭도 보존 |
| `lodging_type_detail` | string 또는 null, 최대 50자 | `other`인 경우 실제 유형 필수 |
| `lodging_name` | string 또는 null, 최대 100자 | 비어 있지 않은 실제 숙소명 |
| `location` | string 또는 null, 최대 200자 | 광고에 사용할 지역이 명확함. 상세 도로명 주소까지 요구하지 않음 |
| `selling_points` | string 배열, 1~5개, 항목당 최대 100자 | 실제 장점이 최소 하나 있고 재확인 대상이 아님 |
| `target_audience` | string 또는 null, 최대 100자 | 광고 대상이 명확함 |
| `mood` | string 또는 null, 최대 100자 | 사용자 지정 또는 명시적인 추천 위임에 따른 기본값 |
| `color_preference` | string 또는 null, 최대 100자 | 지정 색상 또는 명시적인 무선호 값 `auto` |
| `ad_copy` | string 또는 null, 최대 60자 | 사용자 직접 입력 또는 AI 제안 문구를 사용자가 채택 |

추가 조건은 다음과 같습니다.

- `null`은 미입력입니다. 색상 무선호와 미입력을 구분합니다.
- “알아서 해주세요”는 디자인 선택 위임으로 처리할 수 있지만 숙소명, 장점, 타깃 같은 사실을 임의로 채우지 않습니다.
- 원본 사진은 별도 자산으로 관리하고, FastAPI가 확인한 `original_image_uploaded=true`가 있어야 사진 단계가 완료됩니다. 모델은 사진의 존재나 소유권을 URL 문자열로 판단하지 않습니다.
- `completed_fields`와 `missing_fields`에는 사진 상태를 나타내는 가상 필드 `original_image`도 포함합니다. 이 필드는 `brief_updates`로 수정할 수 없습니다.
- 필수값이 모두 유효하고, 미해결 정정·재확인·문구 선택이 없어야 `is_complete=true`입니다.
- 외부 API에 전달할 수 없는 내용, 과도한 길이 등은 별도 입력 검증으로 처리합니다.

**확정:** 광고 문구 직접 입력과 AI 후보 최대 3개 중 사용자 선택을 모두 지원합니다. 게스트하우스 등은 `other`와 `lodging_type_detail`로 표현합니다.

광고 문구를 AI가 제안하는 경우 `ad_copy_candidates`에 최대 3개를 반환하고 선택 전에는 `ad_copy`를 채우지 않는 방식을 제안합니다. 다음 요청에도 후보 목록을 전달하면 “2번으로 할게요” 같은 답변을 해석할 수 있습니다. 모든 A·B·C에는 동일하게 확정한 `ad_copy`를 사용합니다.

## 4. 질문 순서와 상태 전이

단계 enum은 다음 순서로 고정할 것을 제안합니다.

`lodging_type → lodging_information → selling_points → target_audience → mood → ad_copy → complete`

- `lodging_information`은 숙소명 다음 지역, `selling_points`는 장점 다음 원본 사진, `mood`는 분위기 다음 색상을 같은 단계 안에서 하나씩 확인합니다.
- 한 번의 질문과 답변에서는 현재 질문에 해당하는 정보 하나만 반영합니다. 같은 단계에 다음 세부 항목이 남아 있으면 `next_step`은 유지하고 질문 문구만 다음 항목으로 바뀝니다.
- 현재 단계 답변이 모호하거나 무관하면 다음 수집 단계로 넘어가지 않습니다. 단, 명확한 다른 필드가 함께 입력되었다면 그 필드만 반영할 수 있습니다.
- 이전 답변 정정만 있는 경우 값을 수정한 뒤 현재 질문을 계속합니다.
- 정정과 현재 질문 답변이 함께 있으면 두 내용을 처리하되, 필요한 재확인을 우선합니다.
- 재확인이 발생하면 `resume_step`에 복귀 지점을 보관하고, `fields_to_reconfirm`을 고정 순서로 처리합니다. 완료 후 복귀 지점부터 유효한 미완료 항목을 찾습니다.
- 숙소 유형 변경만으로 장점 전체를 자동 무효화하지 않습니다. 실제 충돌이 있거나 기존 문구가 정정 전 사실을 사용하는 경우에 재확인합니다.
- `complete`는 읽기 전용 전환 상태입니다. 마지막 질문 안내에 “완료 후에는 수정할 수 있다”는 오해가 없도록 표시하고, 완료 이후 채팅 정정 RPC는 거부합니다. 최종 확인 버튼은 저장·생성을 시작하며 기획서를 수정하지 않습니다.

## 5. Agent 요청에 추가할 상태

기존 요청 필드에 다음 항목을 제안합니다.

| 필드 | 목적 |
| --- | --- |
| `request_id` | 호출 추적 |
| `state_revision` | 요청이 기준으로 삼은 React 임시 상태 버전 |
| `fields_to_reconfirm` | 이전 응답에서 남은 재확인 목록 |
| `resume_step` | 재확인 후 돌아갈 단계. 없으면 null |
| `ad_copy_candidates` | 직전에 제안한 문구 목록 |
| `original_image_uploaded` | FastAPI가 세션의 실제 저장 자산을 확인해 설정 |

`completed_fields`는 brief와 사진 상태 및 재확인 목록으로 모델 서버에서 재계산할 수 있어 요청의 필수 항목에서는 제외하는 안입니다. 전달하더라도 그대로 신뢰하지 않고 재검증합니다.

React는 세션당 한 채팅 요청을 처리한 후 다음 요청을 보내는 방식이 단순합니다. 응답에는 요청의 `state_revision`을 그대로 반환하고, React는 현재 버전과 일치할 때만 변경사항과 진행 상태를 원자적으로 적용한 뒤 버전을 증가시킵니다. 늦게 도착한 응답이 최신 입력을 덮어쓰지 않도록 하기 위함입니다. 이는 영구 DB 버전이 아니라 임시 UI 상태의 버전입니다.

FastAPI는 사용자·세션 소유권, 요청 형식과 크기를 검사합니다. 임시 기획서가 React에 있더라도 인증·사진 소유권·생성 가능 여부를 클라이언트 값만으로 결정하지 않습니다.

## 6. 대화 기록 전달 범위

초기안은 **현재 기획서 전체 + 명시적 진행 상태 + 최근 최대 12개 메시지**입니다. `conversation_history`에는 현재 `user_message`를 중복 포함하지 않습니다.

최근 메시지는 추가로 최대 8,000토큰 범위로 제한하는 안이며, 실제 비용과 정정 처리 정확도를 보고 조정하겠습니다. 과거 핵심 사실은 brief에, 재확인과 선택 후보는 전용 상태 필드에 남겨야 합니다. 잘린 기록을 근거로 “아까 말한 것으로 바꿔줘”를 해석할 수 없다면 추측하지 않고 재질문합니다.

이 제한은 모델 호출용입니다. 최종 DB 저장에 필요한 전체 대화 기록은 React가 별도로 유지해야 합니다. `conversation_history`의 role은 `user`·`assistant`만 허용하고, 사용자 제공 기록을 시스템 지시로 취급하지 않습니다.

## 7. 응답 필드 의미

제안된 구조는 지원하는 방향으로 구현하겠습니다. 아래처럼 의미를 통일하는 것이 필요합니다.

| 필드 | 제안 규칙 |
| --- | --- |
| `message_intent` | `answer`, `correction`, `question`. 정정이 포함되면 `correction` 우선이며 현재 질문 답변도 함께 반영 가능 |
| `answer_status` | 답변·정정의 명확성: `valid`, `ambiguous`, `off_topic`. 질문 의도에는 `not_applicable` 추가 제안 |
| `assistant_message` | 사용자에게 표시할 답변 또는 다음 질문 |
| `brief_updates` | 변경할 필드만 포함. 누락은 유지, null은 삭제, 배열은 전체 교체 |
| `corrected_fields` | 기존 값을 정정한 필드 목록. `brief_updates`의 키에 포함되어야 함 |
| `fields_to_reconfirm` | 응답 반영 후 남아 있는 전체 재확인 목록 |
| `completed_fields` | 응답 반영 후 전체 완료 필드 목록 |
| `missing_fields` | 응답 반영 후 전체 미완료 필수 필드 목록. 재확인 대상도 포함 |
| `current_step` | 요청에서 받은 단계. 응답에서 의미를 변경하지 않음 |
| `next_step` | 적용 후 단계. 유지할 때도 같은 값을 반환하며 null을 사용하지 않음. 완료는 `complete` |
| `resume_step` | 처리 후 복귀 지점 또는 null |
| `ad_copy_candidates` | 처리 후 유효한 후보 목록. 없으면 빈 배열 |
| `is_complete` | `next_step=complete`이고 모든 완료 조건을 충족할 때만 true |

숙소명이나 타깃 정정으로 문구 후보가 더 이상 맞지 않으면 후보를 비우고 문구를 다시 확인합니다. 유효한 정정이어도 현재 질문에 답하지 않았다면 다음 단계로 넘어가지 않습니다. `valid`를 곧바로 “단계 이동”으로 해석하지 않아야 합니다.

정정 내용이 모호하면 그 필드를 덮어쓰지 않습니다. 기존 값을 유지하되 해당 필드를 `fields_to_reconfirm`에 남겨 완료를 막습니다. 오류·출력 파싱 실패는 이 정상 응답을 흉내 내지 않고 RPC 오류로 반환합니다.

## 8. 채팅 요청·응답 예시

다음은 분위기 단계에서 숙소 유형만 정정하는 예시입니다. 예시 ID는 설명용입니다.

```json
{
  "request_id": "chat-007",
  "session_id": "session-001",
  "state_revision": 6,
  "user_message": "숙소 유형은 호텔이 아니라 모텔이야.",
  "current_step": "mood",
  "brief": {
    "lodging_type": "hotel",
    "lodging_type_detail": null,
    "lodging_name": "서울숙소",
    "location": "서울 중구",
    "selling_points": ["남산뷰 객실"],
    "target_audience": "커플 여행객",
    "mood": null,
    "color_preference": null,
    "ad_copy": null
  },
  "original_image_uploaded": true,
  "fields_to_reconfirm": [],
  "resume_step": null,
  "ad_copy_candidates": [],
  "conversation_history": [
    {"role": "assistant", "content": "어떤 분위기와 색상의 광고를 원하시나요?"}
  ]
}
```

```json
{
  "request_id": "chat-007",
  "session_id": "session-001",
  "state_revision": 6,
  "message_intent": "correction",
  "answer_status": "valid",
  "assistant_message": "숙소 유형을 모텔로 수정했어요. 이어서 원하는 광고 분위기와 색상을 알려주세요.",
  "brief_updates": {"lodging_type": "motel"},
  "corrected_fields": ["lodging_type"],
  "fields_to_reconfirm": [],
  "completed_fields": ["lodging_type", "lodging_name", "location", "selling_points", "original_image", "target_audience"],
  "missing_fields": ["mood", "color_preference", "ad_copy"],
  "current_step": "mood",
  "next_step": "mood",
  "resume_step": null,
  "ad_copy_candidates": [],
  "is_complete": false
}
```

같은 요청 상태에서 입력만 바꾸는 연동 테스트의 기대 결과는 아래와 같습니다. 실제 `assistant_message`의 문장 일치보다 상태와 추출값을 검증합니다.

| 입력 | 주요 기대 결과 |
| --- | --- |
| “따뜻한 분위기, 베이지색으로 해주세요” | `answer/valid`, mood·color 갱신, 다음 단계 `ad_copy` |
| “그냥 괜찮게요” | `answer/ambiguous`, 변경 없음, `mood` 유지 및 구체화 질문 |
| “오늘 점심은 김치찌개 먹었어요” | `answer/off_topic`, 변경 없음, `mood` 유지 |
| “광고 분위기는 무슨 뜻인가요?” | `question/not_applicable`, 간단한 설명, `mood` 유지 |
| “가족 말고 커플로 바꾸고 따뜻한 베이지로 해주세요” | 기존 타깃이 가족인 별도 사례에서 정정과 현재 답변 동시 처리 |
| “아까 타깃 바꿀게요” | 기존 타깃 유지, 타깃 재확인, 완료 불가 |

마지막 두 사례를 포함한 전체 JSON fixture는 계약 확정 후 제공하겠습니다.

## 9. A·B·C 호출과 방향

`GenerateDraft`를 초안별로 한 번씩 호출하고, 한 RPC는 PNG 한 장을 반환하는 방식에 동의합니다. 세 호출을 FastAPI가 병렬로 요청할 수 있도록 설계하되, 모델 서버의 이미지 동시 실행 수는 초기 3개로 제한하고 계정 한도와 메모리를 확인하겠습니다. 이는 모든 세션에서 세 장의 동시 실행 시간을 보장한다는 의미는 아닙니다.

| direction | 이미지·합성 설계 |
| --- | --- |
| `room` | 원본 객실·시설을 크게 보여주는 구도, 실제 장점이 보이는 사진 영역 우선 |
| `emotion` | 따뜻함·차분함 등 확정 분위기를 색감·조명·여백에 반영, 숙박 경험 강조 |
| `benefit` | 확정 광고 문구의 크기·대비·배치를 강조, 제공된 실제 장점만 활용 |

모든 방향에서 건물·객실·시설의 정체성을 보존하도록 지시합니다. 사진에 없는 시설을 새로 만들어 보여주거나 입력되지 않은 가격·할인·등급·무료 혜택을 추가하지 않습니다. 현재 brief에는 프로모션 필드가 없으므로 `benefit`은 할인 광고가 아니라 **확인된 장점과 메시지 중심**으로 정의하는 안입니다.

## 10. 한글 문구와 출력 규격

기본안은 **원본 기반 배경 편집 → 모델 서버에서 한글 문구 합성 → 최종 PNG 반환**입니다. 외부에는 레이어를 전달하지 않습니다.

- 배경 프롬프트에는 새 광고 문구를 그리지 않고 합성할 공간을 확보하도록 지시합니다.
- 확정된 숙소명과 `ad_copy`를 번들 한글 폰트와 이미지 처리 코드로 그립니다.
- 글꼴 배포 조건을 확인하고, Docker에 폰트를 포함합니다.
- 줄바꿈과 글자 크기는 자동 조정하되 문구를 임의로 축약·변경하지 않습니다. 허용 길이 안에서도 배치가 불가능하면 성공으로 반환하지 않습니다.
- 원본의 간판 등 기존 텍스트와 광고 문구가 겹치지 않는지, 배경 모델이 불필요한 문구를 추가하는지 샘플 검수합니다.
- **확정:** 출력은 1024×1024, PNG, 1:1입니다. 다른 크기·비율 선택은 V3 범위입니다.
- 출력 PNG는 애플리케이션 수준에서 최대 25MiB로 제한하여 32MiB gRPC 메시지 안에 여유를 둡니다.

이 방식은 합성하는 문구의 철자를 고정할 수 있지만 가독성과 호텔 사진 보존 품질은 별도 검증 대상입니다.

## 11. 입력 검증과 통신 제한

- **확정:** 원본 1장, JPEG·PNG·정적 WebP, 업로드 최대 25MiB(26,214,400 bytes).
- FastAPI는 업로드의 절대 상한을 60MP로 제한합니다. 60MP 초과, 손상, 형식 불일치, 애니메이션 WebP는 거부합니다.
- 20MP 이하는 크기 축소 없이 사용하고, 20MP 초과 60MP 이하는 원본 비율을 유지해 20MP 이하로 축소합니다. EXIF 방향 반영과 모델 입력용 색상 모드 정규화는 FastAPI가 담당합니다.
- 원본 파일은 그대로 보관하며 모델 입력용 최적화 파일을 별도로 생성합니다. 전달 MIME 타입은 최적화 파일의 실제 인코딩과 일치해야 합니다.
- 모델 서버는 전달받은 이미지의 실제 포맷·손상·정적 이미지 여부와 최대 20MP를 방어적으로 재검증합니다. 백엔드에서 이미 반영한 EXIF 방향을 중복 적용하지 않도록 방향 메타데이터 처리 규칙을 맞춥니다.
- **추가 확인:** 정규화 재인코딩 후 bytes도 25MiB 이하인지 FastAPI에서 확인하는 규칙을 제안합니다. 픽셀 수가 줄어도 파일 크기는 증가할 수 있습니다. 초과 시 재최적화 또는 명확한 오류 반환이 필요합니다.
- gRPC 송수신 한도는 양쪽 모두 32MiB(33,554,432 bytes)입니다. 전체 메시지에도 한도가 적용됩니다.
- MP는 width × height 기준 1,000,000픽셀로 정의하고 경계값 테스트를 제공하는 안입니다.

## 12. RPC와 배포 구성

V1 RPC는 유지하고 V2 패키지를 별도로 추가하는 안입니다. 이름은 합의 전 가안입니다.

| 서비스 | RPC | 역할 |
| --- | --- | --- |
| `hotel.adimage.v2.PlanningAgentService` | `ProcessTurn` | 구조화된 대화 응답과 기획서 변경사항 반환 |
| `hotel.adimage.v2.DraftImageService` | `GenerateDraft` | 방향별 PNG 한 장 반환 |
| 각 서비스 | `HealthCheck` | 서비스 준비 상태 확인 |

초기에는 두 서비스를 같은 `llm-service:50051`에 등록하고 unary gRPC로 제공합니다. 이미지 요청이 채팅 처리를 모두 점유하지 않도록 실행 제한을 분리합니다. 부하 측정 결과에 따라 프로세스나 컨테이너를 분리할 수 있도록 구현합니다.

기존 `OPENAI_API_KEY`, `BACKEND_DOCKER_NETWORK`, `PORT=50051`을 유지하고 아래 환경변수를 추가하는 안입니다. 아래 항목은 아직 구현되지 않았습니다.

| 변수 | 초기 제안 |
| --- | --- |
| `CHAT_MODEL` | `gpt-4.1-mini-2025-04-14` |
| `IMAGE_MODEL` | `gpt-image-2` |
| `CHAT_RPC_TIMEOUT_SECONDS` | 30 |
| `IMAGE_RPC_TIMEOUT_SECONDS` | 180 |
| `IMAGE_MAX_CONCURRENCY` | 3 |
| `AD_FONT_PATH` | 컨테이너 내부 번들 폰트 경로 |

키는 모델 서버 환경에만 주입합니다. HealthCheck는 유료 생성 요청을 실행하지 않으며 외부 API의 실시간 성공 가능성을 보장하지 않습니다.

## 13. 타임아웃과 오류 처리

채팅 RPC 30초, 초안별 이미지 RPC 180초를 **초기 설정값**으로 제안합니다. 성능 보장값이 아니며 실제 지연 분포와 프록시 제한을 확인한 뒤 조정합니다. 내부 API 호출 예산은 RPC deadline보다 짧게 두고, SDK 자동 재시도를 명시적으로 제어하여 백엔드 재시도와 중첩되지 않도록 합니다.

이미지 생성은 FastAPI가 작업을 등록한 뒤 상태 조회 방식으로 React에 제공하는 흐름을 권합니다. 이미지 RPC의 대기 시간과 사용자 HTTP 요청 시간을 분리합니다.

| gRPC 코드 | 대표 원인 | 처리 방향 |
| --- | --- | --- |
| `INVALID_ARGUMENT` | 잘못된 필드·direction·이미지 형식, 손상 파일 | 입력 수정 후 호출 |
| `FAILED_PRECONDITION` | 미완성 기획서 생성 요청, 완료 상태 정정 요청, 생성 정책상 거부 | 원인 해결 필요, 자동 재시도 안 함 |
| `RESOURCE_EXHAUSTED` | 입력 크기 초과, 동시 처리 한도, 외부 API rate limit | 원인별 구분. 크기 초과는 수정, 일시적 한도는 대기 후 재시도 |
| `DEADLINE_EXCEEDED` | 처리 시간 초과 | 결과 불확실 상태로 취급, 중복 호출 확인 후 재시도 |
| `UNAVAILABLE` | 외부 API 일시 장애·연결 실패 | 제한된 지수 백오프 재시도 |
| `CANCELLED` | 클라이언트 취소 | 자동 재시도 안 함 |
| `INTERNAL` | 검증할 수 없는 모델 출력, 합성 실패, 서버 설정·처리 오류 | 로그 확인, 사용자에게 내부 오류를 그대로 노출하지 않음 |

오류에는 안정적인 `reason`(예: `INPUT_TOO_LARGE`, `UPSTREAM_RATE_LIMIT`, `MODEL_OUTPUT_INVALID`), `retryable`, `request_id`를 구조화된 상세 정보로 전달하는 안입니다. 크기 초과처럼 전송 계층에서 발생한 오류는 상세 정보가 없을 수 있어 백엔드 기본 처리도 필요합니다. API 키·내부 경로·원본 사용자 데이터를 오류 문자열에 노출하지 않습니다.

자동 재시도는 FastAPI를 주체로 하고 일시 장애에 한해 초안별 최대 2회 추가 시도를 초기안으로 제안합니다. 사용자 재시도에도 별도 요청 빈도·비용 한도가 필요합니다. 성공 기준 1회라는 정책이 무제한 유료 호출을 의미하지 않도록 합니다.

## 14. 이미지 요청·응답과 다시 생성

`generation_round`와 `is_regeneration`은 지원하는 방향으로 구현하겠습니다. 두 값의 불일치는 거부하고, V2에서는 round 1은 false, round 2는 true로 제한하는 안입니다.

아래는 설명용 JSON입니다. 실제 gRPC의 이미지 필드는 base64 문자열이 아닌 `bytes`이며, 예시의 꺾쇠 문자열은 자리 표시자입니다.

```json
{
  "request_id": "image-attempt-001",
  "session_id": "session-001",
  "draft_id": "draft-round1-a",
  "generation_round": 1,
  "is_regeneration": false,
  "direction": "room",
  "brief": {
    "lodging_type": "motel",
    "lodging_type_detail": null,
    "lodging_name": "서울숙소",
    "location": "서울 중구",
    "selling_points": ["남산뷰 객실"],
    "target_audience": "커플 여행객",
    "mood": "세련되고 따뜻한",
    "color_preference": "따뜻한 베이지",
    "ad_copy": "도심 위, 둘만의 특별한 하루"
  },
  "original_image_bytes": "<binary bytes>",
  "image_mime_type": "image/png"
}
```

```json
{
  "request_id": "image-attempt-001",
  "session_id": "session-001",
  "draft_id": "draft-round1-a",
  "generation_round": 1,
  "direction": "room",
  "image_bytes": "<PNG binary bytes>",
  "image_mime_type": "image/png"
}
```

다시 생성 시에는 최초와 다른 레이아웃을 선택합니다.

- round 1과 round 2에서 사진 영역·문구 배치·여백의 템플릿을 변경합니다.
- 동일한 확정 brief·원본 사진·광고 문구를 사용하고 숙소의 사실이나 A/B/C 방향은 변경하지 않습니다.
- 이전 이미지를 모델 입력에 추가하지 않는 구조에서는 의미상 완전히 다른 이미지가 나온다고 보장할 수 없습니다. 템플릿 차이와 실제 샘플 비교로 차별화를 검증합니다.

실패 재시도는 같은 `draft_id`·회차·내용을 유지하고 호출 시도마다 새로운 `request_id`를 사용합니다. 사용자의 다시 생성은 round 2의 새 draft ID를 발급합니다. 실패한 round 2를 재시도하더라도 round 3을 만들지는 않습니다.

모델 서버의 무상태 구조만으로 외부 유료 API 호출의 exactly-once 실행을 보장할 수는 없습니다. FastAPI에서 초안별 실행 잠금·시도 기록·완료 결과 재사용을 관리해야 합니다. 타임아웃 뒤에도 외부 호출이 처리되었을 가능성이 있어 즉시 중복 실행하지 않도록 주의가 필요합니다.

부분 성공은 FastAPI가 내부적으로 보관하여 같은 회차의 실패 초안만 재시도할 수 있습니다. 단, 동일한 확정 입력과 생성 규격의 결과만 재사용하고, 세 장 모두 생성·파일 저장·DB 저장에 성공하기 전에는 새 회차를 활성화하지 않습니다. 기존 round 1 유지와 regeneration_count 변경은 백엔드 책임입니다.

## 15. 검증 및 제공 산출물

계약 확정 후 모델 측에서 다음을 제공하겠습니다.

1. V2 `.proto`, stub 생성 명령, Docker 실행 안내와 환경변수 예시.
2. 정상 답변·모호한 답변·무관한 답변·질문·정정·재확인 복귀·복합 입력 JSON fixture.
3. 사진 미업로드, 모호한 정정, 미선택 문구가 있는 상태에서 완료되지 않는 테스트.
4. A/B/C 호출·회차별 생성·부분 실패·타임아웃·크기 경계 테스트 예제.
5. 한글 문구 누락·오탈자·잘림과 실제 호텔 특징 보존, 방향별 차이를 확인한 샘플.
6. 한국어 대화 30~50개 사례의 필드 추출·단계 이동 결과, 실측 응답 시간과 호출 비용 기록.

최초 품질 기준은 제공한 회귀 사례에서 잘못된 완료 전이와 명확한 정정 누락이 없어야 하고, 합성된 문구는 확정 문구와 일치해야 한다는 것입니다. 이미지 품질과 처리 시간의 구체적인 합격 기준은 샘플을 함께 확인한 뒤 확정하겠습니다.

## 16. 백엔드 회신으로 확정된 사항과 남은 계약 검토

다음 사항은 백엔드가 동의했습니다.

- 무상태 Agent, 고정 질문 순서와 유효 완료 단계 건너뛰기.
- 광고 문구 직접 입력 및 최대 3개 후보 중 사용자 선택.
- 숙소 유형 5개 enum 및 other 상세 유형.
- state_revision, resume_step, fields_to_reconfirm, answer_status의 not_applicable.
- 최근 최대 12개 메시지·최대 8,000토큰, 완료 기획서 읽기 전용.
- A/B/C 독립 GenerateDraft, 서버 한글 합성, 정사각형 PNG 출력.
- 채팅 30초·이미지 180초의 초기 timeout, 구조화된 오류 상세 정보.
- 시스템 재시도와 사용자 다시 생성 횟수 분리, 성공한 다시 생성 1회만 차감.
- 부분 결과 재사용, 세 장 모두 저장 완료 전에는 새 회차 비활성화.
- generation_round와 is_regeneration 사용.

최종 proto 전에 요청·응답 예시로 다음을 검토합니다.

1. current_step은 요청 기준, next_step은 처리 후 단계로 정의하고 유지 시에도 같은 값을 반환하는 규칙.
2. completed_fields·missing_fields·fields_to_reconfirm은 응답 반영 후 전체 상태인지 확인.
3. brief_updates의 누락=유지, null=삭제, 배열=전체 교체와 proto에서의 필드 존재 여부 표현.
4. 여러 번 발생하는 정정·재확인과 resume_step 복귀, 모호한 정정의 완료 차단.
5. 문구 후보의 다음 요청 전달, 번호 선택·직접 입력 우선순위와 후보 무효화.
6. 사진 상태의 백엔드 검증 및 사진만 업로드했을 때 ProcessTurn을 호출할 이벤트 규칙.
7. 8,000토큰은 최근 대화에 대한 한도로 해석하며, 실제 채팅 모델 토크나이저 기준 측정 주체와 전체 문맥 예산을 정합니다. vLLM의 최대 문맥 길이가 8,192이면 시스템 지시·Form·출력 공간을 위해 대화 기록을 더 줄여야 합니다.
8. 정규화 후 이미지 bytes 제한, EXIF 중복 적용 방지, MP 경계값.
9. 오류 상세 정보의 전송 형식, 초안 식별·시도별 ID와 중복 실행 방지.

vLLM 실행 환경 결정은 내부 추론 구현 과제이며 위 업무용 계약 검토와 병행할 수 있습니다. 외부 API 모델을 기본으로 한 HTML 선정 보고서는 이전 후보 비교 자료이며 vLLM 채택 완료를 나타내지 않습니다.
