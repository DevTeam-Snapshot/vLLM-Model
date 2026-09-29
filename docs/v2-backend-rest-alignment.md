# Backend REST 명세 대조 결과

검토 대상은 사용자가 전달한 `Snapshot Backend API 명세` HTML입니다. 실제 `.proto` 원문이나 Backend 구현은 포함되어 있지 않습니다. REST 표현과 모델 서버의 gRPC 계약을 구분해서 대조했습니다.

## 일치한 사항

- lodging_service: 서비스·혜택 문자열 목록, 최대 5개.
- 질문 순서: 유형 → 정보 → 공간 내용 → 혜택 → 분위기 → 색상 → 타겟 → 광고 문구 → 완료.
- 후보 순서: 1=공간 내용, 2=분위기, 3=혜택.
- 1080×1350 PNG, 3개 후보, 성공 기준 1회 재생성.
- 모델은 bytes를 반환하고 Backend가 이미지 파일·URL·DB·선택 상태를 관리합니다.

## 반영한 호환성 수정

1. REST direction인 `room/emotion/benefit`을 기본 enum 이름으로 유지합니다. `SPACE/MOOD/SERVICE`는 같은 숫자의 내부 동의어입니다. 새 이름이 REST 응답에 흘러가 기존 분기를 깨뜨리지 않도록 했습니다.
2. 세션 조회에서 selling_points/lodging_service가 null이면, 전체 brief 변환 시 미입력 빈 목록으로 처리합니다. Patch의 null은 목록 삭제로 해석하지 않으며 삭제에는 []를 씁니다.

`examples/v2_contract_codec.py`는 참조 변환기입니다. Backend가 자체 변환기를 사용한다면 이 저장소 수정만으로 Backend 변환 코드가 바뀌지는 않습니다.

## 실제 proto 및 Backend 코드에서 확인할 항목

REST에 없는 다음 정보는 Backend가 내부 gRPC 요청에 넣어야 합니다. HTML의 생략을 근거로 모델 서버의 필수 검증을 제거하지 않았습니다.

| gRPC 정보 | 모델 서버 요구 |
| --- | --- |
| request_id / session_id | 실제 요청·세션 식별자 |
| state_revision | 명시적 존재 필수, 0도 유효. 실제 snapshot 버전과 일치 |
| event_type | 일반 답변 USER_MESSAGE, 사진 등록 이벤트 IMAGE_UPLOADED |
| original_image_uploaded | 자산·세션 확인 후 명시적 bool. 사진 bytes는 GenerateDraft에 별도 전달 |
| fields_to_reconfirm / resume_step | 재확인이 있으면 다음 요청에도 유지 |
| ad_copy_candidates | 번호 선택을 지원하려면 이전 추천 목록을 다음 요청에 유지 |

REST에 revision·재확인·추천 문구 목록이 노출되지 않아도 Backend가 정확히 관리·전달하면 됩니다. 하지만 실제 저장·전달 구현은 HTML만으로 확인할 수 없습니다. 무상태 모델 서버가 이전 요청의 값을 기억한다고 가정하지 않습니다.

현재 모델 서버의 wire 번호는 다음과 같습니다. Backend가 순서대로 enum을 재번호화하지 않았는지 실제 `.proto`로 확인해야 합니다.

- AdvertisementBrief.lodging_service = 10, BriefPatch.lodging_service = 10.
- BRIEF_FIELD_LODGING_SERVICE = 11.
- PLANNING_STEP_LODGING_SERVICE = 8, COLOR_PREFERENCE = 9.
- 기존 COMPLETE = 7, TARGET_AUDIENCE = 4, MOOD = 5, AD_COPY = 6 유지.
- direction은 ROOM=1, EMOTION=2, BENEFIT=3.

혜택이 없을 때의 `["없음"]` 표현과 항목당 100자 제한은 기존 모델 계약에 있으며 이번 HTML에는 명시되어 있지 않습니다. Backend 검증에서 동일하게 허용해야 합니다. null/[]은 미입력이며 기획 완료가 아닙니다.

명세 예시의 '숙소 이름과 위치를 알려주세요'는 하나의 단계 설명입니다. 모델은 이름 다음 위치를 각각 질문하며 같은 lodging_information이 연속될 수 있습니다. React는 단계가 같더라도 assistant_message를 갱신해야 합니다. missing_fields에는 사진이 없으면 original_image도 포함됩니다.

## 검증 범위

null 목록과 후보 enum의 문자열·숫자 변환 회귀 검사, 기존 전체 회귀 검사 및 로컬 gRPC 연동으로 모델 저장소 범위를 확인합니다. 실제 Backend의 DTO·DB·gRPC 매핑 및 새 proto와의 byte 수준 일치는 원문과 실행 환경이 있어야 확인할 수 있습니다. 이 문서는 Backend 구현 완료나 실제 양쪽 proto 일치를 인증하지 않습니다.
