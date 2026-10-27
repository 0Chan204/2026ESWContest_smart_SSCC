// 테스트용 백엔드 응답 (app/schemas.py 형식). 실제 값이 아니라 형식 확인용.

Map<String, dynamic> snapshotJson({bool stoveOn = false}) => {
      'serverTime': '2026-10-26T10:00:00Z',
      'session': stoveOn
          ? {
              'sessionId': 'sess-1',
              'startedAt': '2026-10-26T09:50:00Z',
              'status': 'active',
              'peakTemperature': 120,
              'timeline': [
                {'at': '2026-10-26T09:50:00Z', 'type': 'cooking_started', 'summary': '조리를 시작했어요'},
              ],
            }
          : null,
      'rooms': {
        'kitchen': {
          'presence': {'room': 'kitchen', 'present': true, 'zone': 'kitchen', 'absentSec': 0, 'confidence': 0.92, 'observedAt': '2026-10-26T10:00:00Z'},
        },
      },
      'appliances': [
        {
          'deviceId': 'induction-01',
          'burners': [
            {'burnerId': 'burner-1', 'deviceState': stoveOn ? 'on' : 'off', 'level': stoveOn ? 5 : 0, 'temperature': stoveOn ? 110.5 : 24, 'activeSec': stoveOn ? 600 : 0},
          ],
          'lastControl': {'publisher': 'user'},
        },
      ],
      'devices': [
        {'device': 'stove', 'deviceId': 'induction-01', 'room': 'kitchen', 'online': true, 'is_on': stoveOn},
        {'device': 'light', 'deviceId': 'light-01', 'room': 'room', 'online': true, 'is_on': true, 'current_state': {'power': 'on', 'brightness': 100}, 'control_state': 'user'},
        {'device': 'light', 'deviceId': 'light-00', 'room': 'toilet', 'online': true, 'is_on': false},
        // 백엔드 v0.8: 주방 전등
        {'device': 'light', 'deviceId': 'light-02', 'room': 'kitchen', 'online': true, 'is_on': false, 'current_state': {'power': 'off'}},
        {'device': 'water_purifier', 'deviceId': 'water-01', 'room': 'kitchen', 'online': true, 'is_on': false, 'current_state': {'lastDispensedMl': 250}, 'control_state': 'homevis', 'updatedAt': '2026-10-26T07:10:00Z'},
        {'device': 'fan', 'deviceId': 'fan-01', 'room': 'kitchen', 'online': true, 'is_on': true, 'current_state': {'power': 'on', 'speed': 'high'}, 'control_state': 'homevis'},
        {'device': 'fan', 'deviceId': 'fan-02', 'room': 'toilet', 'online': false, 'is_on': false},
        {'device': 'air_purifier', 'deviceId': 'air-01', 'room': 'room', 'online': true, 'is_on': true, 'current_state': {'power': 'on', 'mode': 'auto', 'airQuality': {'pm25': 41.6, 'pm10': 60, 'level': 'bad'}}},
      ],
    };

Map<String, dynamic> eventJson(String id, String type, {String room = 'kitchen', String at = '2026-10-26T09:55:00Z', String severity = 'warning', String? sessionId}) => {
      'eventId': id,
      'type': type,
      'severity': severity,
      'occurredAt': at,
      'room': room,
      if (sessionId != null) 'sessionId': sessionId,
      'trigger': '부재 3분',
      'action': '화력을 1단으로 낮춤',
      'guidance': '주방을 오래 비우셔서 화력을 낮췄어요.',
    };
