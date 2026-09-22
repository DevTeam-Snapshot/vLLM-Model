"""V2 async client example. Requires a V2 server; V1 does not implement these RPCs.

Run with generated/ and examples/ on PYTHONPATH (see handoff guide).
Image mode may trigger paid generation when pointed at a real model server.
"""
import argparse
import asyncio
import json
from pathlib import Path
from uuid import uuid4

import grpc
from google.protobuf import empty_pb2
from grpc_status import rpc_status

import hotel_ad_v2_pb2 as pb
import hotel_ad_v2_pb2_grpc as rpc
from v2_contract_codec import turn_from_domain, turn_response_to_domain

CHANNEL_OPTIONS = (
    ("grpc.max_send_message_length", 32 * 1024 * 1024),
    ("grpc.max_receive_message_length", 32 * 1024 * 1024),
)


def explain_error(error):
    result = {"grpc_code": error.code().name, "reason": "TRANSPORT_ERROR", "retryable": False}
    try:
        status = rpc_status.from_call(error)
        if status:
            for packed in status.details:
                detail = pb.ModelErrorDetail()
                if packed.Unpack(detail):
                    result.update(request_id=detail.request_id, reason=detail.reason, retryable=detail.retryable)
                    break
    except (ValueError, TypeError):
        result["reason"] = "MALFORMED_ERROR_DETAIL"
    return result


def sample_chat_request(session_id):
    return turn_from_domain({
        "request_id": str(uuid4()), "session_id": session_id, "state_revision": 0,
        "event_type": "user_message", "user_message": "호텔이에요.",
        "current_step": "lodging_type", "brief": {
            "lodging_type": None, "lodging_type_detail": None, "lodging_name": None,
            "location": None, "selling_points": [], "target_audience": None,
            "mood": None, "color_preference": None, "ad_copy": None,
        }, "original_image_uploaded": False, "fields_to_reconfirm": [],
        "resume_step": None, "ad_copy_candidates": [], "conversation_history": [],
    })


def sample_draft_request(session_id, draft_id, direction, generation_round, image, mime):
    # This sample is a final snapshot. Real FastAPI must load its saved snapshot
    # and matching normalized image, rather than trusting frontend form values.
    return pb.GenerateDraftRequest(
        request_id=str(uuid4()), session_id=session_id, draft_id=draft_id,
        generation_round=generation_round, is_regeneration=(generation_round == 2),
        direction=pb.DraftDirection.Value("DRAFT_DIRECTION_" + direction.upper()),
        brief=pb.AdvertisementBrief(
            lodging_type=pb.LODGING_TYPE_HOTEL, lodging_name="바다호텔", location="강릉",
            selling_points=["오션뷰 객실"], target_audience="커플 여행객", mood="따뜻한",
            color_preference="베이지", ad_copy="바다와 함께하는 둘만의 하루",
        ), original_image_bytes=image, image_mime_type=mime,
    )


async def run(args):
    # Internal network or SSH tunnel only. Public deployments require transport security.
    async with grpc.aio.insecure_channel(args.target, options=CHANNEL_OPTIONS) as channel:
        if args.mode == "health":
            for name, stub in [("planning", rpc.PlanningAgentServiceStub(channel)),
                               ("draft", rpc.DraftImageServiceStub(channel))]:
                response = await stub.HealthCheck(empty_pb2.Empty(), timeout=5)
                print(name, response.healthy)
        elif args.mode == "chat":
            request = sample_chat_request(args.session_id)
            response = await rpc.PlanningAgentServiceStub(channel).ProcessTurn(request, timeout=30)
            if (response.request_id != request.request_id or response.session_id != request.session_id
                    or not response.HasField("state_revision") or response.state_revision != request.state_revision):
                raise ValueError("Mismatched chat response")
            print(json.dumps(turn_response_to_domain(response), ensure_ascii=False, indent=2))
        else:
            if not args.image or not args.output or not args.draft_id:
                raise ValueError("image mode requires --image, --output, --draft-id")
            path = Path(args.image)
            mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(path.suffix.lower())
            if not mime or not 0 < path.stat().st_size <= 25 * 1024 * 1024:
                raise ValueError("Expected normalized JPEG/PNG/static WebP, 1..25MiB")
            # Size/format/pixels/EXIF validation remains mandatory on the server.
            output = Path(args.output)
            if output.exists():
                raise ValueError("Output already exists; choose a new path")
            request = sample_draft_request(args.session_id, args.draft_id, args.direction,
                                           args.generation_round, path.read_bytes(), mime)
            response = await rpc.DraftImageServiceStub(channel).GenerateDraft(request, timeout=180)
            for key in ("request_id", "session_id", "draft_id", "generation_round", "direction"):
                if getattr(response, key) != getattr(request, key):
                    raise ValueError("Mismatched draft response: " + key)
            if response.image_mime_type != "image/png" or not response.image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("Expected PNG response")
            if len(response.image_bytes) > 25 * 1024 * 1024:
                raise ValueError("Oversized PNG response")
            with output.open("xb") as stream:
                stream.write(response.image_bytes)
            print("Saved:", output.resolve())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["health", "chat", "image"])
    parser.add_argument("--target", default="127.0.0.1:15051")
    parser.add_argument("--session-id", default="session-example")
    parser.add_argument("--draft-id")
    parser.add_argument("--direction", choices=["room", "emotion", "benefit"], default="room")
    parser.add_argument("--generation-round", type=int, choices=[1, 2], default=1)
    parser.add_argument("--image", help="Already normalized model input image")
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except grpc.RpcError as error:
        print(json.dumps(explain_error(error), ensure_ascii=False, indent=2))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
