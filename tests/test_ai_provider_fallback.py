import importlib.util
import json
import pathlib
import unittest


MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "ai_digest.py"


def load_module():
    spec = importlib.util.spec_from_file_location("market_ai_digest", str(MODULE_PATH))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self.payload


class ProviderFallbackTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.module.DEEPSEEK_API_KEY = "deepseek-test-key"
        self.module.ARK_API_KEY = "doubao-test-key"

    def test_deepseek_is_primary_when_available(self):
        calls = []

        def fake_request(provider, prompt):
            calls.append(provider)
            return {"topics": []}, {"usage": {}}, provider + "-model"

        self.module.provider_json_with_retry = fake_request
        result = self.module.routed_ai_request("test")
        self.assertEqual("deepseek", result[2])
        self.assertFalse(result[4])
        self.assertEqual(["deepseek"], calls)

    def test_doubao_is_used_when_deepseek_fails(self):
        calls = []

        def fake_request(provider, prompt):
            calls.append(provider)
            if provider == "deepseek":
                raise RuntimeError("quota exhausted")
            return {"topics": []}, {"usage": {"input_tokens": 8}}, "doubao-model"

        self.module.provider_json_with_retry = fake_request
        result = self.module.routed_ai_request("test")
        self.assertEqual("doubao", result[2])
        self.assertTrue(result[4])
        self.assertIn("DeepSeek", result[5])
        self.assertEqual(["deepseek", "doubao"], calls)

    def test_doubao_responses_payload_and_output_are_supported(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse({"output_text": '{"topics": []}', "usage": {"input_tokens": 4}})

        self.module.urlopen = fake_urlopen
        result, data, model = self.module.provider_request("doubao", "hello")
        self.assertEqual({"topics": []}, result)
        self.assertEqual(self.module.ARK_TEXT_MODEL, model)
        self.assertEqual(self.module.ARK_RESPONSES_API_URL, captured["url"])
        self.assertEqual("input_text", captured["payload"]["input"][0]["content"][0]["type"])
        self.assertEqual("hello", captured["payload"]["input"][0]["content"][0]["text"])
        self.assertEqual(4, data["usage"]["input_tokens"])


if __name__ == "__main__":
    unittest.main()
