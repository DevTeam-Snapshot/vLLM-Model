"""Wire/adapter tests against local fake services; no model/API/GPU calls."""
import asyncio
import contextlib
import io
import json
from concurrent import futures
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
import zlib

import grpc
from google.protobuf import any_pb2, empty_pb2
from google.rpc import status_pb2
from grpc_status import rpc_status

import hotel_ad_v2_pb2 as pb
import hotel_ad_v2_pb2_grpc as rpc
from v2_contract_codec import (apply_turn_response, brief_from_domain, enum_number,
                               patch_from_domain, patch_to_domain, turn_from_domain,
                               turn_response_to_domain)
from v2_client import CHANNEL_OPTIONS, explain_error, run

FIXTURES = json.loads((Path(__file__).resolve().parents[1] / "docs/examples/v2-contract-cases.json").read_text())


def png_fixture():
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1024, 1024, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress((b"\x00" + b"\xff\xff\xff" * 1024) * 1024)) + chunk(b"IEND", b""))


PNG = png_fixture()


class FakePlanning(rpc.PlanningAgentServiceServicer):
    def __init__(self):
        self.cases = {case["request"]["request_id"]: case for case in FIXTURES["chat_cases"]}
        self.errors = {case["details"]["request_id"]: case for case in FIXTURES["error_examples"]}

    def ProcessTurn(self, request, context):
        if request.request_id in self.errors:
            case = self.errors[request.request_id]
            detail = pb.ModelErrorDetail(**case["details"])
            packed = any_pb2.Any()
            packed.Pack(detail)
            code = getattr(grpc.StatusCode, case["grpc_code"])
            context.abort_with_status(rpc_status.to_status(status_pb2.Status(
                code=code.value[0], message="Sample failure", details=[packed])))
        if request.request_id in self.cases:
            case = self.cases[request.request_id]
            if request != turn_from_domain(case["request"]):
                context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Fixture request mismatch")
            return turn_from_domain(case["response"], response=True)
        # Standalone example smoke response. No inference performed.
        return pb.ProcessTurnResponse(
            request_id=request.request_id, session_id=request.session_id,
            state_revision=request.state_revision, message_intent=pb.MESSAGE_INTENT_ANSWER,
            answer_status=pb.ANSWER_STATUS_VALID, assistant_message="테스트 응답",
            current_step=request.current_step, next_step=pb.PLANNING_STEP_SELLING_POINTS)

    def HealthCheck(self, request, context):
        return pb.HealthCheckResponse(healthy=True)


class FakeDraft(rpc.DraftImageServiceServicer):
    def GenerateDraft(self, request, context):
        if request.original_image_bytes != PNG:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Expected fixture PNG")
        if not request.HasField("is_regeneration") or request.is_regeneration != (request.generation_round == 2):
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Round flag mismatch")
        return pb.GenerateDraftResponse(
            request_id=request.request_id, session_id=request.session_id,
            draft_id=request.draft_id, generation_round=request.generation_round,
            direction=request.direction, image_bytes=PNG, image_mime_type="image/png")

    def HealthCheck(self, request, context):
        return pb.HealthCheckResponse(healthy=True)


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = grpc.server(futures.ThreadPoolExecutor(max_workers=4), options=CHANNEL_OPTIONS)
        rpc.add_PlanningAgentServiceServicer_to_server(FakePlanning(), cls.server)
        rpc.add_DraftImageServiceServicer_to_server(FakeDraft(), cls.server)
        port = cls.server.add_insecure_port("127.0.0.1:0")
        if not port:
            raise RuntimeError("Could not bind local test server")
        cls.target = "127.0.0.1:" + str(port)
        cls.server.start()
        cls.channel = grpc.insecure_channel(cls.target, options=CHANNEL_OPTIONS)
        grpc.channel_ready_future(cls.channel).result(timeout=5)

    @classmethod
    def tearDownClass(cls):
        cls.channel.close()
        cls.server.stop(0).wait()

    def test_presence_and_patch_semantics(self):
        for original in [{}, {"ad_copy": None}, {"ad_copy": "새 문구"},
                         {"selling_points": []}, {"selling_points": ["조식"]},
                         {"lodging_type": None}, {"lodging_type": "other"}]:
            with self.subTest(original=original):
                wire = pb.BriefPatch.FromString(patch_from_domain(original).SerializeToString())
                self.assertEqual(patch_to_domain(wire), original)
        request = pb.ProcessTurnRequest(state_revision=0, original_image_uploaded=False)
        wire = pb.ProcessTurnRequest.FromString(request.SerializeToString())
        self.assertTrue(wire.HasField("state_revision"))
        self.assertTrue(wire.HasField("original_image_uploaded"))
        self.assertFalse(pb.ProcessTurnRequest().HasField("state_revision"))
        self.assertFalse(brief_from_domain({"lodging_name": None}).HasField("lodging_name"))
        with self.assertRaises(ValueError):
            patch_to_domain(pb.BriefPatch(ad_copy=pb.StringChange()))
        with self.assertRaises(ValueError):
            patch_from_domain({"selling_points": None})

    def test_lodging_types(self):
        self.assertEqual(pb.LodgingType.keys(), ["LODGING_TYPE_UNSPECIFIED", "LODGING_TYPE_HOTEL",
                         "LODGING_TYPE_MOTEL", "LODGING_TYPE_RESORT", "LODGING_TYPE_PENSION", "LODGING_TYPE_OTHER"])
        with self.assertRaises(ValueError):
            brief_from_domain({"lodging_type": "guesthouse"})

    def test_all_chat_fixtures_over_grpc(self):
        stub = rpc.PlanningAgentServiceStub(self.channel)
        for case in FIXTURES["chat_cases"]:
            with self.subTest(case=case["id"]):
                request = turn_from_domain(case["request"])
                response = stub.ProcessTurn(request, timeout=5)
                self.assertEqual(turn_response_to_domain(response), case["response"])
                state = apply_turn_response(case["request"], request, response)
                self.assertEqual(state["state_revision"], case["request"]["state_revision"] + 1)
                self.assertEqual(state["current_step"], case["response"]["next_step"])
                self.assertEqual(response.is_complete, response.next_step == pb.PLANNING_STEP_COMPLETE)
                self.assertFalse(set(response.completed_fields) & set(response.missing_fields))
                self.assertTrue(set(response.fields_to_reconfirm) <= set(response.missing_fields))

    def test_stale_response_rejected(self):
        case = FIXTURES["chat_cases"][0]
        request = turn_from_domain(case["request"])
        response = turn_from_domain(case["response"], response=True)
        stale = dict(case["request"], state_revision=case["request"]["state_revision"] + 1)
        with self.assertRaises(ValueError):
            apply_turn_response(stale, request, response)
        response.request_id = "another-request"
        with self.assertRaises(ValueError):
            apply_turn_response(case["request"], request, response)

    def test_all_image_fixtures_over_grpc(self):
        stub = rpc.DraftImageServiceStub(self.channel)
        for case in FIXTURES["image_cases"]:
            with self.subTest(case=case["id"]):
                data = dict(case["request"])
                data["brief"] = brief_from_domain(data["brief"])
                data["direction"] = enum_number("direction", data["direction"])
                data["original_image_bytes"] = PNG
                response = stub.GenerateDraft(pb.GenerateDraftRequest(**data), timeout=5)
                for key in ("request_id", "session_id", "draft_id", "generation_round", "direction"):
                    self.assertEqual(getattr(response, key), data[key])
                self.assertEqual(response.image_bytes, PNG)
                self.assertEqual(response.image_mime_type, "image/png")

    def test_all_rich_errors_over_grpc(self):
        stub = rpc.PlanningAgentServiceStub(self.channel)
        for case in FIXTURES["error_examples"]:
            with self.subTest(case=case["id"]):
                with self.assertRaises(grpc.RpcError) as failure:
                    stub.ProcessTurn(pb.ProcessTurnRequest(request_id=case["details"]["request_id"]), timeout=5)
                parsed = explain_error(failure.exception)
                self.assertEqual(parsed, dict(case["details"], grpc_code=case["grpc_code"]))

    def test_async_example_modes(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.png"
            output = Path(directory) / "result.png"
            source.write_bytes(PNG)
            args = SimpleNamespace(target=self.target, session_id="test-session", draft_id="test-draft",
                image=str(source), output=str(output), direction="room", generation_round=1)
            with contextlib.redirect_stdout(io.StringIO()):
                for mode in ("health", "chat", "image"):
                    args.mode = mode
                    asyncio.run(run(args))
            self.assertEqual(output.read_bytes(), PNG)


if __name__ == "__main__":
    unittest.main()
