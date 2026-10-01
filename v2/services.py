"""gRPC boundaries shared by live and explicit offline engines."""

from logging import getLogger
from threading import BoundedSemaphore
from typing import Protocol

import grpc
import hotel_ad_v2_pb2 as pb
import hotel_ad_v2_pb2_grpc as rpc
from google.protobuf import empty_pb2

from v2.errors import ModelFailure, abort

logger = getLogger(__name__)


class Planning(Protocol):
    def process(self, request: pb.ProcessTurnRequest) -> pb.ProcessTurnResponse: ...
    def healthy(self) -> bool: ...


class Draft(Protocol):
    def generate(
        self, request: pb.GenerateDraftRequest
    ) -> pb.GenerateDraftResponse: ...
    def healthy(self) -> bool: ...


class PlanningService(rpc.PlanningAgentServiceServicer):
    def __init__(self, engine: Planning) -> None:
        self.engine = engine
        self.slots = BoundedSemaphore(4)

    def ProcessTurn(
        self, request: pb.ProcessTurnRequest, context: grpc.ServicerContext
    ) -> pb.ProcessTurnResponse:
        if not self.slots.acquire(blocking=False):
            abort(
                context,
                request.request_id,
                ModelFailure("SERVER_BUSY", grpc.StatusCode.RESOURCE_EXHAUSTED, True),
            )
        try:
            if not context.is_active():
                raise ModelFailure("REQUEST_CANCELLED", grpc.StatusCode.CANCELLED)
            return self.engine.process(request)
        except ModelFailure as error:
            abort(context, request.request_id, error)
        except Exception as error:  # noqa: BLE001 — gRPC boundary hides provider/user data.
            logger.error("planning_internal_error type=%s", type(error).__name__)
            abort(
                context,
                request.request_id,
                ModelFailure("INTERNAL_ERROR", grpc.StatusCode.INTERNAL),
            )
        finally:
            self.slots.release()

    def HealthCheck(
        self, request: empty_pb2.Empty, context: grpc.ServicerContext
    ) -> pb.HealthCheckResponse:
        return pb.HealthCheckResponse(healthy=self.engine.healthy())


class DraftService(rpc.DraftImageServiceServicer):
    def __init__(self, engine: Draft) -> None:
        self.engine = engine
        self.slots = BoundedSemaphore(3)

    def GenerateDraft(
        self, request: pb.GenerateDraftRequest, context: grpc.ServicerContext
    ) -> pb.GenerateDraftResponse:
        if not self.slots.acquire(blocking=False):
            abort(
                context,
                request.request_id,
                ModelFailure("SERVER_BUSY", grpc.StatusCode.RESOURCE_EXHAUSTED, True),
            )
        try:
            if not context.is_active():
                raise ModelFailure("REQUEST_CANCELLED", grpc.StatusCode.CANCELLED)
            return self.engine.generate(request)
        except ModelFailure as error:
            abort(context, request.request_id, error)
        except Exception as error:  # noqa: BLE001 — gRPC boundary hides provider/user data.
            logger.error("draft_internal_error type=%s", type(error).__name__)
            abort(
                context,
                request.request_id,
                ModelFailure("INTERNAL_ERROR", grpc.StatusCode.INTERNAL),
            )
        finally:
            self.slots.release()

    def HealthCheck(
        self, request: empty_pb2.Empty, context: grpc.ServicerContext
    ) -> pb.HealthCheckResponse:
        return pb.HealthCheckResponse(healthy=self.engine.healthy())


def register_services(server: grpc.Server, planning: Planning, draft: Draft) -> None:
    rpc.add_PlanningAgentServiceServicer_to_server(PlanningService(planning), server)
    rpc.add_DraftImageServiceServicer_to_server(DraftService(draft), server)
