"""Translate safe domain failures into the agreed gRPC status trailer."""

from dataclasses import dataclass
from typing import NoReturn

import grpc
import hotel_ad_v2_pb2 as pb
from google.protobuf import any_pb2
from google.rpc import status_pb2
from grpc_status import rpc_status


@dataclass(frozen=True, slots=True)
class ModelFailure(Exception):
    """Only stable reason codes, never provider messages, cross the boundary."""

    reason: str
    code: grpc.StatusCode
    retryable: bool = False

    def __str__(self) -> str:
        return self.reason


def abort(
    context: grpc.ServicerContext, request_id: str, failure: ModelFailure
) -> NoReturn:
    detail = pb.ModelErrorDetail(
        request_id=request_id,
        reason=failure.reason,
        retryable=failure.retryable,
    )
    packed = any_pb2.Any()
    packed.Pack(detail)
    context.abort_with_status(
        rpc_status.to_status(
            status_pb2.Status(
                code=failure.code.value[0],
                message=failure.reason,
                details=[packed],
            )
        )
    )
    raise RuntimeError("gRPC abort unexpectedly returned")
