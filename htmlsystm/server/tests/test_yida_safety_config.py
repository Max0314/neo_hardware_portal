# -*- coding: utf-8 -*-
import ssl
import unittest
from unittest.mock import patch

from server import yida_client
from server import yida_config


class TestYidaSafetyConfig(unittest.TestCase):
    def test_requires_allowlist_when_auto_discovery_is_disabled(self):
        with patch.object(yida_config, 'YIDA_SPECIAL_MATERIAL_SOURCES', []), \
             patch.object(yida_config, 'YIDA_MATERIAL_SOURCES', []), \
             patch.object(yida_config, 'YIDA_AUTO_DISCOVER_MATERIAL_FORMS', False):
            ok, message = yida_config.check_material_sync_config()

        self.assertFalse(ok)
        self.assertIn('YIDA_MATERIAL_FORMS', message)

    def test_named_allowlist_is_accepted(self):
        source = {
            'form_uuid': 'FORM-EXAMPLE',
            'source_name': '0402电容(C)',
            'library_name': '0402电容(C)',
        }
        with patch.object(yida_config, 'YIDA_SPECIAL_MATERIAL_SOURCES', []), \
             patch.object(yida_config, 'YIDA_MATERIAL_SOURCES', [source]), \
             patch.object(yida_config, 'YIDA_AUTO_DISCOVER_MATERIAL_FORMS', False):
            ok, message = yida_config.check_material_sync_config()

        self.assertTrue(ok)
        self.assertIsNone(message)

    def test_yida_tls_verification_and_retry_jitter_are_enabled(self):
        context = yida_client._ssl_context()
        with patch.object(yida_client.random, 'uniform', return_value=0.25):
            delay = yida_client._retry_delay(2.0, 2)

        self.assertEqual(ssl.CERT_REQUIRED, context.verify_mode)
        self.assertTrue(context.check_hostname)
        self.assertEqual(8.25, delay)
