"""Exercise registered services over real local gRPC with injected engines."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import grpc
import hotel_ad_v2_pb2 as pb
import hotel_ad_v2_pb2_grpc as rpc
import pytest
from google.protobuf import empty_pb2
from grpc_status import rpc_status

from v2.errors import ModelFailure


class PlanningProbe:
    def healthy(self) -> bool:
        return True

    def process(self, request: pb.ProcessTurnRequest) -> pb.ProcessTurnResponse:
        raise ModelFailure("BRIEF_READ_ONLY", grpc.StatusCode.FAILED_PRECONDITION)


class DraftProbe:
    def healthy(self) -> bool:
        return False

    def generate(self, request: pb.GenerateDraftRequest) -> pb.GenerateDraftResponse:
        raise ModelFailure("SERVER_BUSY", grpc.StatusCode.RESOURCE_EXHAUSTED, True)


@contextmanager
def connected() -> Iterator[grpc.Channel]:
    from v2.services import register_services

    with ThreadPoolExecutor(max_workers=4) as pool:
        server = grpc.server(pool)
        register_services(server, PlanningProbe(), DraftProbe())
        port = server.add_insecure_port("127.0.0.1:0")
        server.start()
        try:
            with grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
                yield channel
        finally:
            server.stop(0).wait()


def test_health_reports_each_engine_readiness() -> None:
    with connected() as channel:
        planning = rpc.PlanningAgentServiceStub(channel)
        draft = rpc.DraftImageServiceStub(channel)
        assert planning.HealthCheck(empty_pb2.Empty(), timeout=3).healthy
        assert not draft.HealthCheck(empty_pb2.Empty(), timeout=3).healthy


def test_planning_error_has_contract_trailer() -> None:
    with connected() as channel, pytest.raises(grpc.RpcError) as caught:
        rpc.PlanningAgentServiceStub(channel).ProcessTurn(
            pb.ProcessTurnRequest(request_id="readonly-1"),
            timeout=3,
        )
    assert caught.value.code() == grpc.StatusCode.FAILED_PRECONDITION
    status = rpc_status.from_call(caught.value)
    assert status is not None
    detail = pb.ModelErrorDetail()
    assert status.details[0].Unpack(detail)
    assert detail.request_id == "readonly-1"
    assert detail.reason == "BRIEF_READ_ONLY"
    assert not detail.retryable


def test_draft_error_preserves_retryable_and_request_id() -> None:
    with connected() as channel, pytest.raises(grpc.RpcError) as caught:
        rpc.DraftImageServiceStub(channel).GenerateDraft(
            pb.GenerateDraftRequest(request_id="busy-1"),
            timeout=3,
        )
    status = rpc_status.from_call(caught.value)
    assert status is not None
    detail = pb.ModelErrorDetail()
    assert status.details[0].Unpack(detail)
    assert detail.reason == "SERVER_BUSY"
    assert detail.request_id == "busy-1"
    assert detail.retryable
