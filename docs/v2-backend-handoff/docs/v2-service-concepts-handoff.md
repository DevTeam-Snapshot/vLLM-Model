# 공간·분위기·혜택 광고와 lodging_service 연동

이 문서는 새 동작의 기준입니다. 기존 필드 번호를 유지하면서 혜택 필드와 색상 단계를 추가했습니다. 모델 서버와 Backend의 protobuf를 함께 갱신하고 React의 단계·후보 라벨을 맞추세요. 기존 `v2-contract-cases.json`은 이전 계약의 wire 변환 회귀 자료이며 새 질문 순서 예제로 사용하지 않습니다.

Backend HTML 명세와의 대조 및 실제 proto 확인이 필요한 항목은 [REST 정합성 검토](v2-backend-rest-alignment.md)를 참조하세요.

## 기획 순서

`lodging_type → lodging_information → selling_points → lodging_service → mood → color_preference → target_audience → ad_copy → complete`

- lodging_information에서는 이름 다음 지역을 각각 질문합니다.
- selling_points는 객실·전망·시설 등 **공간 내용**입니다. 사진이 없으면 이 단계에서 업로드를 요청합니다.
- lodging_service는 실제 제공 **서비스·혜택 및 조건**입니다. selling_points와 섞어서 보내지 않습니다.
- mood와 color_preference는 별도 단계입니다.
- Backend·React는 숫자 크기로 진행 순서를 판단하지 말고 응답 next_step을 따릅니다.

광고 대상은 `current_step=target_audience`에서 사용자가 직접 답한 경우에만 저장합니다. 모델이 반환한 대상이 최신 사용자 답변에 없는 표현이거나 다른 언어로 번역된 값이면 Patch에 넣지 않고 같은 질문을 다시 합니다. 색상·분위기에서 타겟을 추론하거나 추천 요청을 확정 답변으로 처리하지 않습니다. 유효한 답변이 없으면 target_audience를 누락 상태로 유지하고 광고 문구 단계로 넘어가지 않습니다. 명시적인 JSON 답변도 같은 규칙을 적용합니다.

이미 저장된 brief의 target_audience는 사용자 입력인지 과거 모델 추론인지 무상태 서버가 구분할 수 없습니다. 수정 후 테스트는 target_audience가 비어 있는 새 세션에서 진행하고, Backend는 모델의 brief_updates에 없는 타겟을 임의로 채우지 않아야 합니다. 기존 잘못된 타겟은 자동으로 삭제하지 않습니다.

| 단계 | protobuf 값 |
| --- | --- |
| lodging_type | 1 |
| lodging_information | 2 |
| selling_points | 3 |
| lodging_service | **8 (추가)** |
| mood | 5 |
| color_preference | **9 (추가)** |
| target_audience | 4 |
| ad_copy | 6 |
| complete | 7 |

complete=7을 비롯한 기존 숫자는 바꾸지 않았습니다. `current_step`, `next_step`, `resume_step` 모두 새 8·9를 처리해야 합니다. `BRIEF_FIELD_LODGING_SERVICE=11`도 completed_fields/missing_fields/corrected_fields/fields_to_reconfirm에 포함될 수 있습니다. 재확인 우선순위는 위 기획 순서이며 필드 enum 숫자순이 아닙니다.

## 새 필드

```proto
// AdvertisementBrief 안에 추가
repeated string lodging_service = 10;

// BriefPatch 안에 추가
StringListReplacement lodging_service = 10;
```

Domain JSON 예시:

```json
{
  "lodging_type": "hotel",
  "lodging_name": "예시 호텔",
  "location": "서울",
  "selling_points": ["한강 전망 객실", "객실 내 휴식 공간"],
  "lodging_service": ["조식 제공 — 유료, 사전 예약 필요", "무료 주차 — 객실당 1대"],
  "mood": "편안하고 로맨틱한",
  "color_preference": "차분한 블루",
  "target_audience": "커플 여행객",
  "ad_copy": "둘만의 여유를 만나는 하루"
}
```

목록 최대 5개, 항목당 100자이며 공백만 있는 값은 거절합니다. 값은 사용자가 제공하거나 확인한 사실이어야 합니다. 실제 혜택이 없다고 확인되면 **`["없음"]`**으로 전달합니다. `"없음"`과 다른 혜택을 섞지 않습니다.

- `[]` 또는 필드 누락: 아직 미입력, 기획 미완료.
- `["없음"]`: 혜택 없음이 확인된 상태, 기획 진행 가능.
- 전체 brief의 `null`: REST 세션 조회의 미입력 값으로 허용하며 변환기는 빈 protobuf 목록으로 처리합니다. 혜택 없음으로 간주하지 않습니다.
- Patch 목록의 `null`: 허용하지 않습니다. 삭제는 `[]`입니다.
- Patch에서 필드 누락: 기존 목록 유지.
- Patch에서 `{"lodging_service": []}`: 목록 전체 삭제, 다시 미입력 상태.
- protobuf의 빈 목록 교체는 `patch.lodging_service.SetInParent()`로 메시지 존재를 명시해야 합니다.

혜택 변경은 광고 사실 변경으로 처리합니다. 추천 문구 후보를 비우고, 이미 확정된 ad_copy가 있으면 재확인을 요청합니다. 기존 기획서에 혜택이 없으면 사용자가 제공 여부를 확인하도록 받으세요. 마이그레이션에서 임의로 무료 혜택이나 `없음`을 채우지 않습니다. GenerateDraft에서 lodging_service가 누락되면 `BRIEF_INCOMPLETE`입니다.

## 세 후보의 고정 순서

| direction | REST 이름 / 내부 alias | 중심 정보 | 연출 |
| --- | --- | --- | --- |
| 1 | `room` / SPACE | selling_points | 객실·전망·공간 중심, 원래 시간대 유지, 사람 추가 없이 최소 소품 |
| 2 | `emotion` / MOOD | mood | 타겟에 맞는 인물·소품·조명, 필요할 때만 저녁·야간 전환 |
| 3 | `benefit` / SERVICE | lodging_service | 실제 혜택·이용 조건 중심의 문구와 배지, 근거 있는 서비스 연출 |

Backend REST 명세에 맞춰 ROOM=1, EMOTION=2, BENEFIT=3을 기본 이름으로 유지합니다. protobuf JSON과 enum.Name도 이 이름을 반환합니다. SPACE/MOOD/SERVICE는 모델 내부 컨셉 설명용 동의어이며 숫자는 같습니다. React의 direction 값은 room/emotion/benefit을 유지하고 화면 표시만 공간 내용/분위기/혜택으로 사용합니다.

세 요청은 동일한 확정 기획서와 원본 사진을 보내고 direction만 1·2·3으로 바꿉니다. 3개의 독립 요청·선택 구조, 1·2회차, 1080×1350 PNG(4:5)는 유지합니다. 기존 generation_round, is_regeneration, draft_id 규칙도 같습니다.

혜택이 `["없음"]`이면 3번은 허위 혜택을 만들지 않고 숙박 안내 중심의 별도 타이포그래피로 구성합니다. 사용자에게 혜택이 없음을 알리고 이 후보를 실제 혜택 광고로 오해하지 않도록 표시할 수 있습니다.

## 생성형 연출 허용 범위

공통으로 실제 객실 구조·창문·고정 가구·침대 수·창밖 지형·건물·다리·해안선을 유지하도록 요청합니다. 원본과 다른 시설이나 더 넓은 객실·전망을 만들지 않습니다.

분위기에 맞는 소수의 인물, 책·컵·가방·꽃 등 이동 가능한 소품은 허용합니다. 서비스 장면과 음식 표현은 실제 lodging_service에 근거해야 합니다. 소품은 광고 연출이며 호텔의 제공품이나 무료 혜택으로 주장하지 않습니다. 분위기형에서 필요한 경우 시간대·하늘의 밝기·실내 조명·반사를 저녁이나 야간으로 바꿀 수 있습니다. 야간은 강제가 아니며 실제 전망의 형태를 바꾸거나 새로운 명소·시설을 추가하지 않습니다.

숙소명과 확정 광고 문구는 그대로 쓰도록 지시하고 보조 문구만 후보별 핵심 정보에서 만듭니다. 유료/무료, 예약·대상·수량 조건을 유지합니다. 조건 없는 할인·조식·업그레이드를 임의로 만들지 않습니다.

프롬프트는 서로 다른 구성과 장면을 요청하지만, 생성 모델이 세 장의 차이나 사진·한글 정확성을 보장하지는 않습니다. 실제 생성 결과에서 인물·소품의 자연스러움, 시설·전망 보존, 혜택 조건과 오탈자를 검수해야 합니다. fake는 통신 확인용 템플릿이며 인물이나 야간 장면을 생성하지 않습니다.

## Backend 전달 파일과 확인 항목

- `proto/hotel_ad_v2.proto`: 양쪽에서 동일 파일로 stub 재생성.
- `examples/v2_contract_codec.py`: lodging_service 목록·patch 변환 지원.
- `examples/v2_client.py`: 기존 REST 후보 이름과 혜택 필드 예시.
- 위 파일의 사본은 `docs/v2-backend-handoff/`에도 동기화합니다.
- Backend REST DTO·DB 기획서·gRPC 매핑에서 lodging_service가 저장·전달되는지 확인합니다.
- React는 새 혜택 질문, 별도 색상 단계, 새 질문 순서, 후보 라벨을 반영합니다.
- 오래된 초안 캐시는 새 컨셉과 혼용하지 않습니다.

모델 서버는 외부 Backend·React 코드를 수정하지 않습니다. 새 필드를 보내기 전에는 이 버전만 먼저 배포하지 말고 연동 변경과 함께 테스트하세요. OpenAI 설정은 기존 IMAGE_MODEL=gpt-image-2, IMAGE_QUALITY=high, IMAGE_TIMEOUT_SECONDS=150을 유지합니다.
