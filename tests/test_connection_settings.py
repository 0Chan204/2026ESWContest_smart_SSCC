import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock

from src.integration.mqtt_source import MQTTSource
from src.integration.settings import DEFAULT_CONFIG, MQTTSettings, load_settings


class ConnectionSettingsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / 'homevis.toml'

    def policy(self, content, extra=''):
        self.path.write_text('decision_policy = "decision_policy.toml"\n' + extra, encoding='utf-8')
        (self.root / 'decision_policy.toml').write_text(content, encoding='utf-8')

    def test_shipped_settings(self):
        settings = load_settings(DEFAULT_CONFIG, environ={})
        self.assertEqual(settings.integration.base_url, 'http://localhost:8000')
        self.assertEqual((settings.mqtt.host, settings.mqtt.port), ('localhost', 1883))
        self.assertIsNone(settings.mqtt.ca_file)
        self.assertTrue(settings.integration.multi_room_lights)

    def test_policy_connections_are_loaded_relative_to_config(self):
        self.policy('''[backend]
base_url = "https://backend.example"
http_timeout = 7.0
poll_interval = 4.0
[mqtt]
host = "broker.example"
port = 8883
client_id = "board-ai"
tls = true
ca_file = "certs/ca.pem"
location_topic = "home/edge/result"
behavior_topic = "home/behavior"
fall_status_topic = "home/fall/status"
''')
        settings = load_settings(self.path, environ={})
        self.assertEqual(settings.integration.base_url, 'https://backend.example')
        self.assertEqual(settings.integration.http_timeout, 7)
        self.assertEqual(settings.integration.poll_interval, 4)
        self.assertEqual(settings.mqtt.host, 'broker.example')
        self.assertEqual(settings.mqtt.port, 8883)
        self.assertEqual(settings.mqtt.client_id, 'board-ai')
        self.assertTrue(settings.mqtt.tls)
        self.assertEqual(settings.mqtt.ca_file, 'certs/ca.pem')
        self.assertEqual(settings.mqtt.location_topic, 'home/edge/result')
        self.assertEqual(settings.mqtt.behavior_topic, 'home/behavior')
        self.assertEqual(settings.mqtt.fall_status_topic, 'home/fall/status')

    def test_environment_overrides_policy_and_cli_overrides_environment(self):
        env = {
            'HOMEVIS_BACKEND_URL': 'https://backend.example',
            'HOMEVIS_MQTT_HOST': 'broker.example', 'HOMEVIS_MQTT_PORT': '8883',
            'HOMEVIS_MQTT_CLIENT_ID': 'env-ai', 'HOMEVIS_MQTT_TLS': 'true',
            'HOMEVIS_MQTT_CA_FILE': 'ca.pem', 'HOMEVIS_LOCATION_TOPIC': 'home/edge/result',
            'HOMEVIS_BEHAVIOR_TOPIC': 'home/behavior', 'HOMEVIS_FALL_STATUS_TOPIC': 'home/fall/status',
            'HOMEVIS_BACKEND_TOKEN': 'test-token', 'HOMEVIS_MQTT_USERNAME': 'test-user',
            'HOMEVIS_MQTT_PASSWORD': 'test-password',
        }
        settings = load_settings(environ=env)
        self.assertEqual(settings.integration.base_url, 'https://backend.example')
        self.assertEqual(settings.integration.headers, {'Authorization': 'Bearer test-token'})
        self.assertEqual((settings.mqtt.host, settings.mqtt.port), ('broker.example', 8883))
        self.assertEqual(settings.mqtt.client_id, 'env-ai')
        self.assertEqual(settings.mqtt.ca_file, 'ca.pem')
        self.assertEqual(settings.mqtt.location_topic, 'home/edge/result')
        self.assertEqual(settings.mqtt.behavior_topic, 'home/behavior')
        self.assertEqual(settings.mqtt.fall_status_topic, 'home/fall/status')
        self.assertTrue(settings.mqtt.tls)
        self.assertEqual(settings.mqtt.username, 'test-user')
        self.assertEqual(settings.mqtt.password, 'test-password')
        self.assertNotIn('test-token', repr(settings))
        self.assertNotIn('test-password', repr(settings))
        self.assertEqual(load_settings(environ=env, base_url='http://cli.example').integration.base_url,
                         'http://cli.example')

    def test_empty_environment_ca_uses_system_certificates(self):
        self.policy('[mqtt]\ntls = true\nca_file = "custom.pem"\n')
        settings = load_settings(self.path, environ={'HOMEVIS_MQTT_CA_FILE': '', 'HOMEVIS_MQTT_TLS': 'false'})
        self.assertIsNone(settings.mqtt.ca_file)
        self.assertFalse(settings.mqtt.tls)

    def test_legacy_standalone_configuration(self):
        self.path.write_text('[backend]\nbase_url = "http://legacy.example"\n[mqtt]\nhost = "old-broker"\n',
                             encoding='utf-8')
        settings = load_settings(self.path, environ={})
        self.assertEqual(settings.integration.base_url, 'http://legacy.example')
        self.assertEqual(settings.mqtt.host, 'old-broker')

    def test_duplicate_connections_rejected(self):
        self.policy('[mqtt]\nhost = "broker"\n', '[mqtt]\nhost = "other"\n')
        with self.assertRaisesRegex(ValueError, 'defined twice'):
            load_settings(self.path, environ={})

    def test_unknown_keys_and_credentials_rejected_in_policy(self):
        for content in ('[mqtt]\nhots = "typo"', '[mqtt]\npassword = "secret"',
                        '[backend.headers]\nAuthorization = "secret"'):
            with self.subTest(content=content):
                self.policy(content)
                with self.assertRaises(ValueError):
                    load_settings(self.path, environ={})

    def test_invalid_environment_rejected(self):
        for env in ({'HOMEVIS_MQTT_PORT': '0'}, {'HOMEVIS_MQTT_PORT': '65536'},
                    {'HOMEVIS_MQTT_PORT': 'invalid'}, {'HOMEVIS_MQTT_TLS': 'yes'},
                    {'HOMEVIS_MQTT_HOST': 'mqtt://broker'}, {'HOMEVIS_MQTT_HOST': 'broker:1883'},
                    {'HOMEVIS_MQTT_CLIENT_ID': ''}, {'HOMEVIS_MQTT_CA_FILE': 'ca.pem'},
                    {'HOMEVIS_BACKEND_URL': 'http://backend/api/v1'}):
            with self.subTest(env=env), self.assertRaises(ValueError):
                load_settings(environ=env)
        self.assertEqual(MQTTSettings(host='::1').host, '::1')

    def test_mqtt_adapter_uses_connection_overrides(self):
        settings = load_settings(environ={
            'HOMEVIS_MQTT_HOST': 'broker.example', 'HOMEVIS_MQTT_PORT': '8883',
            'HOMEVIS_MQTT_TLS': 'true', 'HOMEVIS_MQTT_CA_FILE': 'ca.pem',
            'HOMEVIS_MQTT_USERNAME': 'user', 'HOMEVIS_MQTT_PASSWORD': 'test-password',
        })
        client = Mock()
        source = MQTTSource(settings.mqtt, client=client)
        source.start()
        self.addCleanup(source.close)
        client.connect_async.assert_called_once_with('broker.example', 8883, keepalive=30)
        client.tls_set.assert_called_once_with(ca_certs='ca.pem')
        client.username_pw_set.assert_called_once_with('user', 'test-password')
        client.publish.assert_not_called()


if __name__ == '__main__':
    unittest.main()
