"""Run live Qwen and OpenAI-backed gRPC checks with a supplied hotel photo.

Usage: python -m v2.live_check PHOTO [OUTPUT_DIRECTORY]
Requires MODEL_MODE=live; submits three OpenAI Vision requests via the server.
"""

import os
import sys
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import grpc
import hotel_ad_v2_pb2 as pb
import hotel_ad_v2_pb2_grpc as rpc
from google.protobuf import empty_pb2
from PIL import Image, ImageOps, UnidentifiedImageError

from v2.config import Settings
from v2.image_validation import MAX_BYTES, MAX_PIXELS
from v2.server import CHANNEL_OPTIONS


def prepare_photo(path: Path) -> bytes:
    if not 0 < path.stat().st_size <= MAX_BYTES:
        raise SystemExit("Photo must be 1..25 MiB.")
    with Image.open(path) as source:
        if source.format not in ("JPEG", "PNG", "WEBP"):
            raise SystemExit("Use JPEG, PNG or static WebP.")
        if (
            source.width * source.height > MAX_PIXELS
            or getattr(source, "n_frames", 1) != 1
        ):
            raise SystemExit("Use a static photo of at most 20 million pixels.")
        normalized = ImageOps.exif_transpose(source).convert("RGB")
        normalized.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
        with BytesIO() as stream:
            normalized.save(stream, "PNG")
            return stream.getvalue()


def check_live(photo_path: Path, output_root: Path) -> Path:
    settings = Settings()
    if settings.model_mode != "live":
        raise SystemExit("Set MODEL_MODE=live. This check never runs in fake mode.")
    if not settings.openai_api_key.get_secret_value().strip():
        raise SystemExit("Set OPENAI_API_KEY in the server environment.")
    image_bytes = prepare_photo(photo_path)
    target = os.environ.get("LIVE_CHECK_TARGET", f"127.0.0.1:{settings.port}")
    session_id = f"live-check-{uuid4().hex}"
    output = output_root / session_id
    with grpc.insecure_channel(target, options=CHANNEL_OPTIONS) as channel:
        planning = rpc.PlanningAgentServiceStub(channel)
        drafts = rpc.DraftImageServiceStub(channel)
        if not planning.HealthCheck(empty_pb2.Empty(), timeout=10).healthy:
            raise SystemExit("Qwen is not ready. Check the vllm container logs.")
        if not drafts.HealthCheck(empty_pb2.Empty(), timeout=10).healthy:
            raise SystemExit(
                "Draft service is not ready. Check the key and Korean font."
            )
        turn = pb.ProcessTurnRequest(
            request_id=uuid4().hex,
            session_id=session_id,
            state_revision=0,
            event_type=pb.TURN_EVENT_TYPE_USER_MESSAGE,
            user_message="숙소 유형은 호텔입니다.",
            current_step=pb.PLANNING_STEP_LODGING_TYPE,
            original_image_uploaded=False,
            brief=pb.AdvertisementBrief(),
        )
        response = planning.ProcessTurn(turn, timeout=30)
        if (
            response.request_id != turn.request_id
            or response.session_id != session_id
            or not response.HasField("state_revision")
            or response.state_revision != 0
            or response.brief_updates.lodging_type.set_value != pb.LODGING_TYPE_HOTEL
        ):
            raise SystemExit("Qwen chat returned an unexpected planning result.")
        print("PASS: live Qwen planning turn")
        brief = pb.AdvertisementBrief(
            lodging_type=pb.LODGING_TYPE_HOTEL,
            lodging_name="호텔 광고 테스트",
            location="테스트 지역",
            selling_points=["제공된 숙소 사진"],
            target_audience="여행객",
            mood="차분한",
            color_preference="auto",
            ad_copy="머무는 순간을 특별하게",
        )
        output.mkdir(parents=True, exist_ok=False)
        for direction in (
            pb.DRAFT_DIRECTION_ROOM,
            pb.DRAFT_DIRECTION_EMOTION,
            pb.DRAFT_DIRECTION_BENEFIT,
        ):
            request = pb.GenerateDraftRequest(
                request_id=uuid4().hex,
                session_id=session_id,
                draft_id=f"candidate-{direction}",
                direction=direction,
                generation_round=1,
                is_regeneration=False,
                brief=brief,
                original_image_bytes=image_bytes,
                image_mime_type="image/png",
            )
            result = drafts.GenerateDraft(request, timeout=180)
            if (
                result.request_id != request.request_id
                or result.session_id != session_id
                or result.draft_id != request.draft_id
                or result.direction != direction
                or result.generation_round != 1
                or result.image_mime_type != "image/png"
                or len(result.image_bytes) > MAX_BYTES
            ):
                raise SystemExit("Unexpected draft response identity or format.")
            with Image.open(BytesIO(result.image_bytes)) as rendered:
                if (
                    rendered.format != "PNG"
                    or rendered.info.get("layout_provider") != "openai"
                ):
                    raise SystemExit(
                        "The server did not use OpenAI. Check its version and MODEL_MODE."
                    )
                size = rendered.size
                if size != (1080, 1350):
                    raise SystemExit("Every candidate must be 1080x1350 (4:5).")
                rendered.verify()
            with (output / f"candidate-{direction}.png").open("xb") as stream:
                stream.write(result.image_bytes)
            print(
                f"PASS: candidate={direction} size={size[0]}x{size[1]} layout_provider=openai"
            )
    print(f"Saved: {output.resolve()}")
    return output


def main() -> int:
    args = sys.argv[1:]
    if args == ["--help"]:
        print(__doc__)
        return 0
    if len(args) not in (1, 2):
        print(__doc__)
        return 2
    try:
        check_live(
            Path(args[0]),
            Path(args[1]) if len(args) == 2 else Path("artifacts/live-check"),
        )
        return 0
    except grpc.RpcError as error:
        print(
            f"LIVE CHECK FAILED: {error.code().name}: {error.details()}",
            file=sys.stderr,
        )
        return 1
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as error:
        print(f"PHOTO/OUTPUT ERROR: {type(error).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
