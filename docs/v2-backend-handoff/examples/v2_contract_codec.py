"""Translate agreed domain JSON to/from protobuf (not protobuf JSON format).

This is a reference adapter, not a business validator. Validate untrusted REST
input, permissions, required fields, limits and state transitions separately.
"""
from copy import deepcopy

import hotel_ad_v2_pb2 as pb


ENUM_FIELDS = {
    "lodging_type": (pb.LodgingType, "LODGING_TYPE_"),
    "current_step": (pb.PlanningStep, "PLANNING_STEP_"),
    "next_step": (pb.PlanningStep, "PLANNING_STEP_"),
    "resume_step": (pb.PlanningStep, "PLANNING_STEP_"),
    "event_type": (pb.TurnEventType, "TURN_EVENT_TYPE_"),
    "message_intent": (pb.MessageIntent, "MESSAGE_INTENT_"),
    "answer_status": (pb.AnswerStatus, "ANSWER_STATUS_"),
    "role": (pb.ConversationRole, "CONVERSATION_ROLE_"),
    "direction": (pb.DraftDirection, "DRAFT_DIRECTION_"),
}
FIELD_LISTS = {"corrected_fields", "fields_to_reconfirm", "completed_fields", "missing_fields"}


def enum_number(key, value):
    enum, prefix = ENUM_FIELDS[key]
    return enum.Value(prefix + value.upper())


def enum_text(key, value):
    enum, prefix = ENUM_FIELDS[key]
    return enum.Name(value).removeprefix(prefix).lower()


def brief_from_domain(data):
    result = pb.AdvertisementBrief()
    for key, value in data.items():
        if key not in result.DESCRIPTOR.fields_by_name:
            raise ValueError("Unknown brief field: " + key)
        if key == "selling_points":
            if not isinstance(value, list):
                raise ValueError("selling_points must be a list")
            result.selling_points.extend(value)
        elif value is not None:
            setattr(result, key, enum_number(key, value) if key == "lodging_type" else value)
    return result


def patch_from_domain(data):
    result = pb.BriefPatch()
    for key, value in data.items():
        if key not in result.DESCRIPTOR.fields_by_name:
            raise ValueError("Unknown patch field: " + key)
        change = getattr(result, key)
        if key == "selling_points":
            if not isinstance(value, list):
                raise ValueError("selling_points patch must be a replacement list")
            change.SetInParent()  # Preserve [] as an explicit replacement.
            change.values.extend(value)
        elif value is None:
            change.clear.SetInParent()
        else:
            change.set_value = enum_number(key, value) if key == "lodging_type" else value
    return result


def patch_to_domain(patch):
    result = {}
    for descriptor, change in patch.ListFields():
        key = descriptor.name
        if key == "selling_points":
            result[key] = list(change.values)
        elif change.WhichOneof("operation") == "clear":
            result[key] = None
        elif change.WhichOneof("operation") == "set_value":
            result[key] = enum_text(key, change.set_value) if key == "lodging_type" else change.set_value
        else:
            raise ValueError("Patch operation not selected: " + key)
    return result


def turn_from_domain(data, response=False):
    result = pb.ProcessTurnResponse() if response else pb.ProcessTurnRequest()
    for key, value in data.items():
        if key not in result.DESCRIPTOR.fields_by_name:
            raise ValueError("Unknown turn field: " + key)
        if key == "brief":
            result.brief.CopyFrom(brief_from_domain(value))
        elif key == "brief_updates":
            result.brief_updates.CopyFrom(patch_from_domain(value))
        elif key == "conversation_history":
            for item in value:
                result.conversation_history.add(role=enum_number("role", item["role"]), content=item["content"])
        elif key in FIELD_LISTS:
            getattr(result, key).extend(pb.BriefField.Value("BRIEF_FIELD_" + name.upper()) for name in value)
        elif key == "ad_copy_candidates":
            result.ad_copy_candidates.extend(value)
        elif key in ENUM_FIELDS:
            if value is not None:
                setattr(result, key, enum_number(key, value))
        else:
            setattr(result, key, value)
    return result


def turn_response_to_domain(response):
    result = {
        "request_id": response.request_id, "session_id": response.session_id,
        "state_revision": response.state_revision,
        "assistant_message": response.assistant_message,
        "brief_updates": patch_to_domain(response.brief_updates),
        "ad_copy_candidates": list(response.ad_copy_candidates),
        "is_complete": response.is_complete,
    }
    for key in ("message_intent", "answer_status", "current_step", "next_step"):
        result[key] = enum_text(key, getattr(response, key))
    result["resume_step"] = enum_text("resume_step", response.resume_step) if response.HasField("resume_step") else None
    for key in FIELD_LISTS:
        result[key] = [pb.BriefField.Name(item).removeprefix("BRIEF_FIELD_").lower() for item in getattr(response, key)]
    return result


def apply_turn_response(snapshot, request, response):
    """Return updated UI snapshot; reject stale/mismatched response before patching.

    Caller must apply the returned snapshot atomically. request is the in-flight
    protobuf request, snapshot is the current domain state (including revision).
    """
    if (not response.HasField("state_revision") or not request.HasField("state_revision")
            or response.request_id != request.request_id
            or response.session_id != request.session_id
            or response.session_id != snapshot["session_id"]
            or response.state_revision != request.state_revision
            or response.state_revision != snapshot["state_revision"]
            or response.current_step != request.current_step):
        raise ValueError("Stale or mismatched response; do not apply")
    data = turn_response_to_domain(response)
    updated = deepcopy(snapshot)
    updated["brief"].update(data["brief_updates"])
    updated["current_step"] = data["next_step"]
    for key in ("fields_to_reconfirm", "completed_fields", "missing_fields",
                "resume_step", "ad_copy_candidates", "is_complete"):
        updated[key] = data[key]
    updated["state_revision"] += 1
    # Chat history append/render is the caller's responsibility.
    return updated
