import os
import unittest
from unittest.mock import patch

from backend.services.schematic_review_prompt import (
    DEFAULT_SCHEMATIC_AI_ID,
    list_selectable_schematic_ai_models,
    normalize_schematic_default_ai_id,
)


class SchematicReviewPromptTests(unittest.TestCase):
    def test_neoflow_hides_unmapped_models_and_rejects_stale_default(self):
        with patch.dict(os.environ, {"TOKENPLAN_PROVIDER": "neoflow"}, clear=True):
            ids = {item["id"] for item in list_selectable_schematic_ai_models()}
            self.assertIn(DEFAULT_SCHEMATIC_AI_ID, ids)
            self.assertNotIn("bailian-deepseekv4flash", ids)
            self.assertEqual(
                normalize_schematic_default_ai_id("bailian-deepseekv4flash"),
                DEFAULT_SCHEMATIC_AI_ID,
            )

    def test_direct_token_plan_keeps_flash_selectable(self):
        with patch.dict(os.environ, {"TOKENPLAN_PROVIDER": "direct"}, clear=True):
            ids = {item["id"] for item in list_selectable_schematic_ai_models()}
            self.assertIn("bailian-deepseekv4flash", ids)
            self.assertEqual(
                normalize_schematic_default_ai_id("bailian-deepseekv4flash"),
                "bailian-deepseekv4flash",
            )


if __name__ == "__main__":
    unittest.main()
