# V2 요청·응답 예시와 상태 전이 규칙

2026-09-29 변경: [사진 보정·후보별 비율 계약](v2-photo-rendering.md)을 우선 적용합니다. wire 필드는 유지하지만 출력은 정사각형 고정이 아닙니다.

작성일: 2026-09-16. **백엔드 승인 완료된 의미 계약입니다. 최종 wire 규격과 호출 방법은 [proto 전달 안내](v2-proto-handoff.md)를 따릅니다. 서버 구현 완료를 뜻하지 않습니다.** 기존 [설계 회신](v2-model-design-reply.md)을 구체화합니다. 외부 AI 호출 없이 작성했으며 실제 모델의 정확도·응답 시간을 검증한 결과는 아닙니다.

## 1. 확정 사항과 이번 추가 제안

백엔드가 동의한 내용은 무상태 Agent, 고정 질문 순서와 완료 단계 건너뛰기, 기획서 완성 후 읽기 전용, 숙소 유형 5개와 other 상세, 문구 후보 최대 3개와 직접 입력, state_revision·resume_step·fields_to_reconfirm, 최근 12개 메시지·8,000토큰 상한, A/B/C 독립 생성, 서버 한글 합성, 후보별 비율 PNG(원본 비율 긴 변 1024 또는 1024×1024), 초기 timeout 30초/180초, 구조화 오류, 성공 기준 다시 생성 1회입니다.

**아래 추가 제안을 포함한 규격에 대해 백엔드가 동의했습니다.** 본문의 제안 표현은 논의 이력이며 최종 protobuf 표현은 `proto/hotel_ad_v2.proto`로 확정했습니다.

1. event_type과 system_event 의도 추가, 사진 이벤트 payload 규칙.
2. current_step/next_step 및 누적 완료·미완료 목록의 의미.
3. 누락·null·배열 교체를 구분하는 patch와 proto 표현 방식.
4. 재확인 복귀 규칙, 문구 선택 충돌·후보 무효화, 읽기 전용 경계.
5. revision 적용 방식, 오류 전송 방식, 정규화 bytes 상한.

## 2. 상태와 완료 판정

| 단계 | 소속 필수 필드 | 완료 조건 |
| --- | --- | --- |
| lodging_type | lodging_type; other이면 lodging_type_detail | 5개 enum 중 하나, other 상세 필수 |
| lodging_information | lodging_name, location | 명확하고 비어 있지 않음 |
| selling_points | selling_points, original_image | 장점 최소 1개와 FastAPI가 확인한 사진 |
| target_audience | target_audience | 명확한 고객층 |
| mood | mood, color_preference | 지정 값 또는 명시적 디자인 위임; 무선호 색은 auto |
| ad_copy | ad_copy | 직접 입력 또는 후보 채택 |
| complete | 위 조건 전부 | 재확인 없음, 문구 확정, 읽기 전용 |

lodging_type_detail은 other일 때만 필수 목록에 포함합니다. 다른 유형으로 변경하면 null로 정리합니다. original_image는 가상 필드이며 brief_updates로 수정할 수 없습니다. completed_fields와 missing_fields는 **이번 변경분이 아니라 처리 후 전체 필수 필드의 서로 겹치지 않는 분할**입니다. 재확인 대상은 기존 값이 남아 있어도 missing_fields에 속합니다.

단계 순서는 고정이며 각 단계 내 필드 순서도 위 표 순서입니다. 정상 처리 후 미완료 필드 중 가장 앞 단계로 이동합니다. 마지막 필수 입력이 유효해지면 즉시 complete입니다. 최종 확인 버튼은 저장·생성을 요청하며 기획서 수정 기회가 아닙니다. 마지막 필수 입력을 요청할 때 읽기 전용 전환을 미리 안내합니다. complete 이후 ProcessTurn은 입력 변경 없이 BRIEF_READ_ONLY로 거부합니다. 신규 기획은 새 세션입니다.

## 3. ProcessTurn 요청·응답

전체 JSON은 [연동 fixture](examples/v2-contract-cases.json)에 있습니다. JSON은 의미 검토용이며 실제 protobuf JSON 매핑은 최종 proto에서 정합니다.

요청은 request_id, session_id, state_revision, event_type, user_message, current_step, brief, original_image_uploaded, fields_to_reconfirm, resume_step, ad_copy_candidates, conversation_history를 포함합니다. brief는 전체 값이며 누락 입력은 null, 장점 미입력은 빈 배열입니다. 이 필드들은 호출마다 전달하며 모델 서버가 이전 호출을 기억한다고 가정하지 않습니다.

응답은 요청 식별자와 revision, message_intent, answer_status, assistant_message, brief_updates, corrected_fields, fields_to_reconfirm, completed_fields, missing_fields, current_step, next_step, resume_step, ad_copy_candidates, is_complete를 반환합니다.

| 필드 | 이번 제안 규칙 |
| --- | --- |
| current_step | 요청 당시 단계 그대로 반환 |
| next_step | 적용 후 단계; 유지 시 같은 값; null 금지 |
| message_intent | answer / correction / question / 제안값 system_event |
| answer_status | valid / ambiguous / off_topic / not_applicable |
| corrected_fields | 기존 값의 변경·삭제 필드; patch 키의 부분집합. 미입력 값 최초 설정은 제외 |
| brief_updates | 없는 키는 유지, null은 삭제, 배열은 전체 교체 |
| fields_to_reconfirm | 처리 후 남은 전체 목록, 고정 순서·중복 없음 |
| resume_step | 재확인 중 복귀 지점; 재확인 종료 시 null |
| ad_copy_candidates | 처리 후 유효 목록 전체; 선택·직접 확정 후 빈 배열 |
| is_complete | next_step=complete 및 모든 필수 조건 충족일 때만 true |

Patch의 null은 **삭제 동작**이고 삭제 후 해당 필드는 미입력 상태입니다. 빈 문자열은 유효 값으로 받아들이지 않습니다. selling_points는 빈 배열로 삭제하며 null은 허용하지 않습니다. 문자열 삭제와 배열 전체 교체를 proto3 기본값만으로 표현하지 말고, 필드별 변경 메시지의 oneof(set_value, clear) 같은 존재 구분 구조를 사용하도록 제안합니다. 실제 .proto 문법은 다음 단계에서 확정합니다.

### 사진 이벤트

추가 제안 event_type은 user_message / image_uploaded입니다. user_message 이벤트는 비어 있지 않은 문자열, image_uploaded는 빈 문자열과 original_image_uploaded=true를 요구합니다. 사진 업로드·세션 귀속 검증을 마친 FastAPI만 이벤트를 만들어 모델 서버에 전달합니다. 모델은 원본 이미지 bytes를 채팅 RPC에서 받지 않습니다. 사진 이벤트의 message_intent는 새 값 system_event, answer_status는 not_applicable입니다. 기존 세 가지 의도에 사진을 answer로 억지 분류하지 않기 위한 제안입니다.

사진 이벤트도 일반 완료 판정을 실행하므로 다음 단계 이동 또는 전체 완료가 가능합니다. 텍스트와 사진을 함께 제출하면 FastAPI가 사진 검증 완료 후 user_message 이벤트 한 번에 검증된 사진 상태를 넣을 수 있습니다. 사진 업로드 실패 시 성공 이벤트를 보내지 않습니다. 처음 질문은 프런트의 고정 문구로 표시하며 초기 단계는 lodging_type, revision=0입니다. 사진 삭제·교체 UI를 V2에 넣는다면 별도 이벤트·자산 버전 계약이 추가로 필요합니다.

### 문구

번호 선택은 요청에 함께 온 직전 후보 목록을 기준으로 해석합니다. 범위 밖 번호, 후보 없는 번호 선택은 ambiguous로 재질문합니다. 직접 문구를 명확히 제공하면 해당 문자열을 사용합니다. 번호와 직접 문구가 서로 다른 의미로 충돌하면 임의 우선순위를 적용하지 않고 재질문합니다. “2번 대신 이 문구로”처럼 대체 의도가 명확한 경우 직접 문구를 채택합니다.

문구 후보 요청 자체는 answer/valid이지만 후보만으로 ad_copy를 채우지 않습니다. 숙소명·지역·장점·타깃 등 문구의 근거가 바뀌면 보수적으로 기존 후보를 모두 비웁니다. 이미 채택한 문구가 변경 사실과 충돌하면 ad_copy를 재확인 목록에 넣고 완료를 막습니다. 재확인 중 새 후보를 제안해도 사용자가 채택할 때까지 재확인을 해제하지 않습니다.

## 4. 상태 전이표

| 사건 | 값 처리 | 진행 처리 |
| --- | --- | --- |
| 명확한 현재 답변 | 유효 필드 반영 | 가장 앞 미완료 단계로 이동 |
| 여러 항목 동시 답변 | 유효 항목 전부 반영 | 이미 완료된 단계를 건너뜀 |
| 모호한 현재 답변 | 모호한 필드 유지 | 해당 필드 재질문; 명확한 다른 값은 반영 가능 |
| 무관한 발언 | 변경 없음 | 현재 질문 유지 |
| 설명 질문 | 변경 없음, 짧은 설명 | 현재 질문 유지 |
| 명확한 이전 값 정정 | 정정 반영, 의존 정보 검증 | 현재 질문이 미완료이면 유지 |
| 정정+현재 답변 | 둘 다 반영 | 필요한 재확인 우선, 없으면 일반 진행 |
| 모호한 정정 | 기존 값 보존 | 대상 필드를 재확인에 추가, 완료 차단 |
| 재확인 답변 | 유효 값 반영 후 대상 해제 | 다음 재확인 우선, 모두 끝나면 복귀 |
| 문구 후보 요청 | 후보 최대 3개, ad_copy 유지 | 선택 전 완료 불가 |
| 문구 선택/직접 입력 | ad_copy 확정, 후보 비움 | 모든 조건 충족하면 complete |
| 사진 이벤트 | FastAPI 확인 상태 사용 | 일반 완료 판정 실행 |
| 필수값 삭제 | null 또는 빈 배열 적용 | 해당 미완료 단계로 돌아감 |
| complete 이후 정정 | 변경 없음 | FAILED_PRECONDITION |
| 파싱·모델·네트워크 오류 | 상태 변경 없음 | gRPC 오류, 정상 답변으로 위장하지 않음 |

재확인 발생 시 resume_step은 **이번 메시지의 유효 변경을 적용한 뒤 재확인이 없다고 가정했을 때 다음 질문할 단계**입니다. 그 단계가 complete라면 첫 재확인 필드의 단계로 대신 저장합니다. 이미 재확인 중이면 원래 resume_step을 유지합니다. 남은 재확인은 고정 필드 순서로 질문합니다. 모두 해결하면 resume_step에서 복귀하되, 값 삭제 등으로 더 앞 단계가 미완료가 됐다면 가장 앞 미완료 단계를 우선합니다. 이렇게 해야 복귀 때문에 필수 항목을 건너뛰지 않습니다. 재확인할 의도는 알지만 필드를 특정하지 못하면 임의 필드를 무효화하지 않고 현재 단계에서 대상부터 질문합니다.

한 메시지의 의도가 겹치면 correction > question > answer 순으로 대표 intent를 선택하되 추출 가능한 유효 정보는 함께 반영합니다. ambiguous와 valid가 섞이면 ambiguous로 표시하고 유효 patch는 유지합니다. off_topic은 적용 가능한 관련 답변이 전혀 없는 경우에 사용합니다.

## 5. revision과 대화 문맥

- state_revision은 요청 기준 임시 상태 버전이며 응답은 같은 값을 돌려줍니다. DB 버전이나 모델 저장 상태가 아닙니다.
- 프런트는 세션당 한 요청만 처리하고, 응답 revision과 현재 revision이 일치할 때 patch·단계·후보·재확인 상태를 원자적으로 적용한 뒤 +1합니다.
- revision 불일치 응답은 전부 폐기합니다. 가령 현재 8에 요청 기준 7 응답이 오면 적용하지 않습니다. 모델 서버는 최신 버전을 저장하지 않으므로 이 검사는 프런트/백엔드 책임입니다.
- 사용자·사진 입력으로 진행 상태를 바꿀 때도 revision을 증가시키고 새 snapshot을 요청합니다. 동일 snapshot의 시스템 재시도는 revision을 유지하고 request_id는 새로 발급합니다.
- 오류가 나면 응답 patch가 없으므로 서버 응답 때문에 revision을 증가시키지 않습니다. UI 입력 변경에 의한 증가는 별개입니다.
- conversation_history는 현재 메시지 제외, user/assistant만 허용, 최근 최대 12개 및 최대 8,000토큰입니다. 명시 상태가 대화 추측보다 우선합니다.
- 8,000은 보장 입력 길이가 아니라 상한입니다. 모델 서비스에서 실제 vLLM 모델 토크나이저 기준으로 `전체 문맥 - 시스템 지시 - schema - 현재 Form/후보/메시지 - 출력 예약 - 여유` 이내가 되도록 오래된 기록부터 제거하는 안입니다. 핵심 상태 자체가 초과하면 CONTEXT_TOO_LARGE 입력 오류를 반환합니다. 정확한 출력 예약량은 모델 실측 후 설정합니다.

## 6. GenerateDraft 계약

fixture에는 round 1과 2 각각 A(room), B(emotion), C(benefit) 6개 요청·응답이 있습니다. 사진 필드의 꺾쇠 문자열은 설명용 자리 표시자이며 실제 호출은 bytes입니다. 모델 서버는 URL 저장·DB 기록·사용자 다시 생성 횟수 차감을 하지 않습니다.

입력은 request_id, session_id, draft_id, generation_round, is_regeneration, direction, 확정 brief, original_image_bytes, image_mime_type입니다. 응답은 식별 정보, direction, PNG bytes와 MIME입니다. FastAPI는 세션의 저장된 확정 스냅샷과 사진 자산으로 입력을 구성하고, 모델 서버도 필수 brief를 재검증합니다. 모델 서버는 전달 brief만으로 실제 세션 확정 이력을 검증할 수 없습니다.

| 항목 | 규칙 |
| --- | --- |
| 최초 생성 | round=1, is_regeneration=false |
| 사용자 다시 생성 | round=2, is_regeneration=true |
| 시스템 재시도 | 같은 round/draft_id/내용, 새로운 request_id |
| 제한 | round 3 및 round/flag 불일치 거부 |
| 입력 사진 | JPEG/PNG/정적 WebP, 최대 20,000,000 pixels, 실제 MIME 일치 |
| 추가 제안 | 정규화 결과 bytes도 최대 26,214,400; EXIF 방향 적용 완료 후 방향 태그 제거 또는 1로 통일 |
| 출력 | 한글 숙소명·확정 문구 합성 완료, 후보별 비율 PNG(원본 비율 긴 변 1024 또는 1024×1024); 최대 25MiB 제안 |
| 전송 | 양쪽 32MiB gRPC 전체 메시지 제한 |

60MP 원본 검사·20MP 초과 축소·EXIF·색상 정규화는 FastAPI 책임입니다. 20MP 이하 원본도 EXIF/색상 정규화가 필요할 수 있으므로 “그대로”는 크기 축소를 하지 않는 의미입니다. 모델은 디코딩 후 크기·정적 여부·형식을 다시 검사합니다.

round 2는 같은 기획서·문구·사진으로 배치 템플릿을 바꿉니다. 사실이나 혜택을 새로 만들지 않습니다. 이미지 결과의 완전한 차이는 보장하지 않습니다. FastAPI는 session+round+draft 단위 실행 잠금과 시도 기록을 보관합니다. round1에서 A/C가 저장 성공하고 B가 실패하면 B만 재시도합니다. round2 세 장의 생성·파일·DB 저장 성공 후 사용자 횟수를 1 차감하고 round2를 활성화합니다. 중간 실패는 차감하지 않고 기존 round1을 유지합니다. DB 저장만 실패했으면 보관된 이미지로 저장을 재시도하며 가능한 한 모델을 재호출하지 않습니다.

## 7. 오류 규격과 재시도

구조화된 reason/retryable/request_id는 합의 사항입니다. 전송 방법은 추가 제안으로 `google.rpc.Status`의 details에 전용 ModelErrorDetail을 싣고 `grpc-status-details-bin` trailer로 전달합니다. 최종 proto에서 메시지를 정의합니다. 아래 JSON은 디코딩 후 의미이며 HTTP 응답 포맷을 규정하지 않습니다.

```json
{"grpc_code":"RESOURCE_EXHAUSTED","details":{"request_id":"image-attempt-3","reason":"UPSTREAM_RATE_LIMIT","retryable":true}}
```

| 코드 | reason 제안 | 자동 재시도 |
| --- | --- | --- |
| INVALID_ARGUMENT | INVALID_EVENT / INVALID_GENERATION_ROUND / CONTEXT_TOO_LARGE | 아니요 |
| FAILED_PRECONDITION | BRIEF_READ_ONLY / BRIEF_INCOMPLETE | 아니요 |
| RESOURCE_EXHAUSTED | INPUT_TOO_LARGE | 아니요 |
| RESOURCE_EXHAUSTED | UPSTREAM_RATE_LIMIT | 제한된 백오프 |
| UNAVAILABLE | UPSTREAM_UNAVAILABLE | 실행 여부가 확인된 연결 전 실패만 |
| DEADLINE_EXCEEDED | RESULT_UNKNOWN | 즉시 반복 금지, 작업 상태 확인 |
| INTERNAL | MODEL_OUTPUT_INVALID / COMPOSITION_FAILED | 기본 아니요, 원인 확인 |

retryable=true는 현재 상태 그대로 제한된 자동 재시도가 가능하다는 뜻이지 실패한 결과가 영구 복구 불가인지를 뜻하지 않습니다. 타임아웃처럼 외부 실행 여부가 불확실하면 false를 반환해 중복 유료 호출을 막고 백엔드에서 결과 확인 후 결정합니다. 재시도 최대 2회 추가 시도는 기존 제안이며 아직 세부 정책 합의 대상입니다. 전송 계층 오류는 상세 정보가 없을 수 있습니다.

## 8. fixture와 검증 결과

[JSON fixture](examples/v2-contract-cases.json)는 독립 snapshot 예제이며 파일 순서대로 이어지는 하나의 대화가 아닙니다. assistant_message는 참고 문장이고 계약 테스트는 구조화 값·전이를 검증합니다. 사진 이벤트의 request.current_step은 이벤트 전 질문 단계이므로 사진 상태와 함께 재계산하면 다음 단계로 넘어갈 수 있습니다.

- 채팅 22건: 정상·모호·무관·설명 질문·정정·복합 정정·재확인 복귀·문구 제안/선택/직접입력/충돌·사진 이벤트/미업로드/완료·삭제/배열 교체·other 전환·후보 무효화·의존 문구 재확인·복수 정보 입력.
- 이미지 6건: 최초/다시 생성 각각 A/B/C.
- 오류 8건: 읽기 전용·미완성·잘못된 이벤트/회차·크기·rate limit·출력 실패·timeout의 상세 표현.
- JSON 파싱, 요청/응답 revision·current_step 일치, corrected_fields의 patch 포함, 재확인 목록의 미완료 포함, 완료/미완료 집합 분리, 후보 3개 이하, other 상세 정리, 재확인/resume 동시 존재, next_step·is_complete 일관성을 검증했습니다.

fixture는 모델 품질 테스트나 실서버 통합 테스트를 대신하지 않습니다. 이 fixture 작성 당시 서버 구현·배포·유료 호출은 없었습니다. 이후 승인된 최종 proto와 생성·호출 자료를 별도로 추가했습니다.
