"""Container readiness probe: never calls image generation."""

import os

import grpc
import hotel_ad_v2_pb2_grpc as rpc
from google.protobuf import empty_pb2


def main() -> int:
    target = f"127.0.0.1:{os.getenv('PORT', '50051')}"
    try:
        with grpc.insecure_channel(target) as channel:
            planning = rpc.PlanningAgentServiceStub(channel).HealthCheck(
                empty_pb2.Empty(), timeout=5
            )
            draft = rpc.DraftImageServiceStub(channel).HealthCheck(
                empty_pb2.Empty(), timeout=5
            )
            return 0 if planning.healthy and draft.healthy else 1
    except grpc.RpcError:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
