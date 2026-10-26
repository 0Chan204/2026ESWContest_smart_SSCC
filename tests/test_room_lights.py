from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from src.integration.backend_client import BackendClient
from src.integration.runtime import IntegrationRuntime
from src.integration.schemas import iso_time
from src.integration.settings import load_settings
from src.integration.simulation import SimulationBackend
from src.llm.config import LLMConfig


class RoomLightTests(unittest.TestCase):
    def exercise_light(self, room, device_id, action):
        with tempfile.TemporaryDirectory() as directory:
            now = [1_700_000_000.0]
            clock = lambda: now[0]
            config = replace(load_settings(environ={}, mode='mock', data_dir=Path(directory)).integration,
                             llm_config=LLMConfig(provider='none'))
            backend = SimulationBackend(clock=clock)
            for item in backend.snapshot['items']:
                if item['device'] == 'stove':
                    item['is_on'] = False
                    item['current_state'].update(state='off', level=0)
                if item['deviceId'] == device_id:
                    item['is_on'] = action == 'off'
                    item['current_state']['power'] = 'on' if action == 'off' else 'off'
            client = BackendClient(config, backend)
            runtime = IntegrationRuntime(config, client, clock=clock)
            location = room if action == 'on' else ('room' if room != 'room' else 'kitchen')
            try:
                for second in range(55):
                    now[0] = 1_700_000_000.0 + second
                    runtime.ingest_device_states({'items': client.fetch_device_states()}, fetched_at=now[0])
                    runtime.ingest_location({'time': iso_time(now[0]), 'location': location,
                                             'location_confidence': .99}, received_at=now[0])
                    runtime.advance(now[0])
                    for _ in range(3):
                        runtime.dispatch_mock_once(now[0])
                requests = [payload for payload, _ in backend.accepted.values()
                            if payload['scenario'] == 'light_auto_' + action
                            and any(a['deviceId'] == device_id for a in payload['actions'])]
                self.assertEqual(len(requests), 1, runtime.outbox.rows())
                payload = requests[0]
                self.assertEqual(payload['room'], room)
                self.assertEqual(payload['actions'], [{'device': 'light', 'deviceId': device_id, 'action': action}])
                response = backend.accepted[payload['decisionId']][1]
                self.assertEqual(response['actions'][0]['deviceId'], device_id)
                item = next(item for item in backend.snapshot['items'] if item['deviceId'] == device_id)
                self.assertEqual(item['is_on'], action == 'on')
                self.assertEqual(item['current_state']['power'], action)
                expected_rooms = {'light-00': 'toilet', 'light-01': 'room', 'light-02': 'kitchen'}
                for request, _ in backend.accepted.values():
                    for command in request['actions']:
                        if command['device'] == 'light':
                            self.assertEqual(request['room'], expected_rooms[command['deviceId']])
            finally:
                runtime.close()

    def test_room_light_on_and_off(self):
        for action in ('on', 'off'):
            with self.subTest(action=action):
                self.exercise_light('room', 'light-01', action)

    def test_toilet_light_on_and_off(self):
        for action in ('on', 'off'):
            with self.subTest(action=action):
                self.exercise_light('toilet', 'light-00', action)

    def test_kitchen_light_on_and_off(self):
        for action in ('on', 'off'):
            with self.subTest(action=action):
                self.exercise_light('kitchen', 'light-02', action)

    def test_fall_blinks_light_in_incident_room(self):
        now = 1_700_000_000.0
        for room, device_id in (('room', 'light-01'), ('toilet', 'light-00'), ('kitchen', 'light-02')):
            with self.subTest(room=room):
                backend = SimulationBackend(clock=lambda: now)
                client = BackendClient(load_settings(environ={}, mode='mock').integration, backend)
                response = client.post_decision({
                    'decisionId': 'fall-' + room, 'scenario': 'fall_detected', 'confidence': .99,
                    'reason': 'Test fall', 'room': room, 'timestamp': iso_time(now), 'actions': [],
                })
                lights = [action for action in response.body['actions'] if action['device'] == 'light']
                self.assertEqual(lights, [{'device': 'light', 'deviceId': device_id,
                                          'action': 'blink', 'status': 'sent'}])


if __name__ == '__main__':
    unittest.main()
