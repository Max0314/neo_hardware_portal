import os
import unittest
from unittest.mock import patch

from backend.ai.bailian_models import (
    build_tokenplan_extra_body,
    get_api_model,
    get_bailian_model,
    get_default_mention_model_id,
    get_tokenplan_base_url,
    get_tokenplan_secret_provider_id,
    is_tokenplan_model_available,
)


class TokenPlanGatewayTests(unittest.TestCase):
    def test_direct_route_preserves_original_model_and_endpoint(self):
        with patch.dict(os.environ, {"TOKENPLAN_PROVIDER": "direct"}, clear=True):
            self.assertEqual(get_api_model("bailian-qwen37plus"), "qwen3.7-plus")
            self.assertIn("token-plan.cn-beijing.maas.aliyuncs.com", get_tokenplan_base_url())
            self.assertEqual(get_tokenplan_secret_provider_id(), "bailian")

    def test_neoflow_route_maps_required_models(self):
        with patch.dict(os.environ, {"TOKENPLAN_PROVIDER": "neoflow"}, clear=True):
            self.assertEqual(
                get_api_model("bailian-qwen37plus"), "qwen/qwen3.7-plus"
            )
            self.assertEqual(
                get_api_model("bailian-deepseekv4"),
                "deepseek/deepseek-v4-pro",
            )
            self.assertEqual(
                get_tokenplan_base_url(), "https://neoflow.neo-net.com/api/v1"
            )
            self.assertEqual(get_tokenplan_secret_provider_id(), "neoflow")

    def test_neoflow_request_does_not_pin_upstream_provider(self):
        with patch.dict(os.environ, {"TOKENPLAN_PROVIDER": "neoflow"}, clear=True):
            spec = get_bailian_model("bailian-deepseekv4")
            self.assertIsNotNone(spec)
            extra_body = build_tokenplan_extra_body(spec, False, "high")
            self.assertEqual(extra_body, {"enable_thinking": False})
            self.assertNotIn("provider", extra_body)

    def test_neoflow_model_override_is_supported(self):
        with patch.dict(
            os.environ,
            {
                "TOKENPLAN_PROVIDER": "neoflow",
                "NEOFLOW_MODEL_bailian_qwen37plus": "qwen/custom-qwen",
            },
            clear=True,
        ):
            self.assertEqual(
                get_api_model("bailian-qwen37plus"), "qwen/custom-qwen"
            )

    def test_default_mention_model_is_qwen37_plus(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(get_default_mention_model_id(), "bailian-qwen37plus")

    def test_invalid_default_falls_back_to_qwen37_plus(self):
        with patch.dict(
            os.environ,
            {"TOKENPLAN_DEFAULT_MENTION_MODEL": "not-a-real-model"},
            clear=True,
        ):
            self.assertEqual(get_default_mention_model_id(), "bailian-qwen37plus")

    def test_neoflow_rejects_unavailable_model_without_override(self):
        with patch.dict(os.environ, {"TOKENPLAN_PROVIDER": "neoflow"}, clear=True):
            self.assertFalse(is_tokenplan_model_available("bailian-qwen37max"))
            with self.assertRaisesRegex(ValueError, "尚无 NeoFlow 映射"):
                get_api_model("bailian-qwen37max")

    def test_direct_route_keeps_full_legacy_catalog_available(self):
        with patch.dict(os.environ, {"TOKENPLAN_PROVIDER": "direct"}, clear=True):
            self.assertTrue(is_tokenplan_model_available("bailian-qwen37max"))

    def test_invalid_provider_is_rejected(self):
        with patch.dict(os.environ, {"TOKENPLAN_PROVIDER": "unknown"}, clear=True):
            with self.assertRaisesRegex(ValueError, "direct 或 neoflow"):
                get_tokenplan_base_url()


if __name__ == "__main__":
    unittest.main()
