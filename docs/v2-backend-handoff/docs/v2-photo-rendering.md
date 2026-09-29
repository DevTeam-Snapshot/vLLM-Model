# V2 Image Gen 호텔 광고와 4:5 출력

V2 DraftImageService.GenerateDraft는 모든 후보·회차에서 **1080×1350 PNG, 4:5**를 반환합니다. live는 원본 사진을 OpenAI Image Gen으로 제한적으로 전체 편집하고, 한글 문구와 광고 디자인까지 함께 생성합니다. 기존 Vision 분석 → 서버 고정 템플릿 합성 방식은 live에서 사용하지 않습니다. V1은 별도 레거시 경로입니다.

새 혜택 필드와 기획 순서는 [공간·분위기·혜택 연동 계약](v2-service-concepts-handoff.md)을 우선 적용합니다.

## 처리 흐름

1. 서버가 원본 이미지와 확정 기획서를 검증합니다.
2. 원본 bytes를 보정·크롭 없이 `images.edit`에 전달합니다. 후보별 디자인 지시와 숙소명·확정 문구·장점·분위기·색상 선호를 함께 보냅니다.
3. `gpt-image-2`가 사진 편집과 한글 타이포그래피를 포함한 완성 광고를 생성합니다.
4. 서버는 4:5 PNG인지 확인한 뒤 1080×1350으로 비례 축소합니다. 로컬 문구·카드·버튼을 추가하지 않습니다.

API 요청 크기는 1152×1440입니다. GPT Image 2의 16배수 크기 조건을 만족하는 4:5 출력으로 받고, 최종 크기는 서버에서 정확히 맞춥니다. 다른 비율이나 최종 출력보다 작은 결과는 잘라내거나 늘이지 않고 `MODEL_OUTPUT_INVALID`로 거절합니다.

## 세 후보

| direction (wire 값 유지) | 권장 표시 이름 | 디자인 지시 |
| --- | --- | --- |
| 1 / SPACE | 공간 내용 중심 | selling_points의 객실·전망·시설을 강조, 원래 시간대 유지 |
| 2 / MOOD | 분위기 중심 | mood·타겟·색상에 맞는 인물·소품·조명, 필요한 경우 야간 연출 |
| 3 / SERVICE | 혜택 중심 | lodging_service의 실제 혜택과 이용 조건을 강조 |

모두 사진이 캔버스를 채우며 문구는 사진 안쪽에 겹칩니다. 바깥 단색 여백, 과도한 카드·버튼, 획일적인 큰 제목을 피하도록 요청합니다. 2회차도 이전 결과가 아닌 동일 원본 사진에서 새 배치를 요청합니다. 모델은 무상태이며 후보 간 또는 회차 간 완전한 차이는 보장하지 않습니다.

## 사진과 문구 보존 범위

프롬프트는 객실 구조, 창문, 가구, 침대 수, 전망·해안선·건물의 보존을 요구합니다. 제한적인 노출·화이트밸런스·대비·색감과 미세한 원근 보정, 비율 유지 크롭만 허용하도록 지시합니다. 사람과 이동 가능한 소품은 컨셉에 맞는 연출로 허용합니다. 음식·서비스 장면은 lodging_service에 근거해야 합니다. 분위기형은 필요한 경우 하늘의 밝기·시간대·실내 조명을 저녁이나 야간으로 바꿀 수 있으나 야간을 강제하지 않습니다. 새로운 시설·지형·건물 추가, 객실이나 전망 확대, 생성형 가장자리 채우기는 금지합니다.

숙소명과 확정 광고 문구는 그대로 쓰도록 요청합니다. 보조 문구는 후보별 중심 정보(selling_points/mood/lodging_service)에서 만들고 '유료', '일부' 등 조건을 유지하며, 할인·가격·무료 혜택을 새로 만들지 않도록 합니다. 애매한 사실이나 대화형 요청 문장을 그대로 광고에 쓰지 않도록 지시합니다.

**이 제약은 생성 모델에 대한 지시이며 코드로 보장되는 픽셀·문구 보존이 아닙니다.** 이미지 내부 시설과 전망, 한글 오탈자, 혜택 조건은 사용자가 실제 원본·기획서와 비교해서 검수해야 합니다. 서버는 파일·크기 검증만 하며 시각적 사실성이나 OCR 검증을 자동으로 수행하지 않습니다. 원본 사진 파일 자체는 변경하지 않습니다.

## 설정과 오류

```dotenv
MODEL_MODE=live
OPENAI_API_KEY=실제_키
OPENAI_BASE_URL=https://api.openai.com/v1
IMAGE_MODEL=gpt-image-2
IMAGE_QUALITY=high
IMAGE_TIMEOUT_SECONDS=150
```

`OPENAI_VISION_MODEL`, `OPENAI_VISION_TIMEOUT_SECONDS`는 더 이상 사용하지 않으므로 제거할 수 있습니다. GPT Image 2는 자동으로 높은 입력 충실도를 적용하므로 `input_fidelity` 옵션은 보내지 않습니다. 이 구현의 크기 계약은 GPT Image 2 전용이며 다른 모델명은 설정 검증에서 거절합니다. 품질은 low/medium/high/auto 중 선택합니다. 이미지 API 제한 시간은 최대 150초, Backend gRPC deadline은 180초를 유지합니다.

후보당 이미지 편집 API 1회, 세 후보는 총 3회입니다. 자동 재시도나 로컬 합성 대체는 없습니다. 인증·권한 거절은 GENERATION_REJECTED, 429는 UPSTREAM_RATE_LIMIT, 연결 실패·timeout·불확실한 서버 오류는 RESULT_UNKNOWN입니다. fake는 외부 호출 없이 기존 로컬 템플릿과 FAKE 표시를 사용하며 live 디자인 품질을 재현하지 않습니다.

live HealthCheck는 키 설정만 확인하고 실제 인증·모델 접근을 확인하지 않습니다. fake HealthCheck는 로컬 폰트를 확인합니다.

## Backend·React 연동

- protobuf 필드 번호·enum 값·세 번의 독립 호출 및 최종 선택 흐름은 유지합니다.
- 후보 라벨은 '공간 내용 중심 / 분위기 중심 / 혜택 중심'을 권장합니다. 원본 비율·정사각형 선택은 사용하지 않습니다.
- PNG를 정사각형으로 재크롭하지 않고 4:5 비율 그대로 저장·표시합니다.
- 기존 초안 캐시와 구분하세요. 이 저장소는 Backend DB와 React를 소유하지 않습니다.
- PNG 메타데이터는 `generation_provider=openai_image_edit`, `output_format=portrait_4_5`, `image_model=gpt-image-2`입니다. 메타데이터는 호출 경로 표시이며 품질 인증이 아닙니다.

## 검증

[SSH live 배포와 실제 API 테스트](v2-live-deployment.md)를 따르세요. `v2.live_check`는 Qwen 요청과 세 이미지 요청을 수행하고 새 메타데이터·크기를 검사합니다. `scripts/check_local.py`는 회귀 검사, `scripts/smoke_local.py`는 외부 API 없는 실제 gRPC 프로세스 검사입니다. 로컬 HTTP 응답으로 SDK 경로를 검사해도 실제 광고 품질은 검증되지 않습니다.

지원 옵션 근거: [OpenAI 이미지 생성·편집](https://developers.openai.com/api/docs/guides/image-generation), [GPT Image 2](https://developers.openai.com/api/docs/models/gpt-image-2).
