"""Show FPS round outcomes before resetting through the existing respawn action."""
import json
import time

from fps_settings import DRONE_EXPLOSION_LOG


class FPSAutoRespawn:
    def __init__(self, ui, player_log, reset_delay=2.0):
        self.ui = ui
        self.reset_delay = reset_delay
        self.player_log = player_log.open(errors='replace')
        self.player_log.seek(0, 2)
        self.report_path = player_log.parent / 'fps-session.json'
        self.partial_line = ''
        self.events = []
        self.pending = None
        self.key_down_at = None
        self.next_attempt = 0
        self.save()

    def update(self):
        now = time.monotonic()
        if self.key_down_at is not None and now - self.key_down_at >= 0.05:
            self.ui.send_key_event('p', False)
            self.key_down_at = None

        lines = (self.partial_line + self.player_log.read()).split('\n')
        self.partial_line = lines.pop()
        for line in lines:
            if 'detonated on the player at ' in line:
                self.queue_outcome('player_death', now)
            elif line.strip() == DRONE_EXPLOSION_LOG:
                self.queue_outcome('drone_destroyed', now)
            elif '[YOPO] Respawn published on /respawn.' in line and self.pending is not None:
                self.pending['respawn_confirmed_unix'] = time.time()
                self.pending['response_sec'] = (self.pending['respawn_confirmed_unix']
                                                - self.pending['outcome_detected_unix'])
                self.pending['reset_trigger'] = 'automatic' if self.pending['attempts'] else 'manual'
                print('FPS：已重置本轮，开始新一轮出生保护。', flush=True)
                self.pending = None
                self.save()

        if self.pending is not None and self.key_down_at is None and now >= self.next_attempt:
            if self.pending['attempts'] >= 3:
                raise RuntimeError('FPS 自动重生未收到确认，请检查 unity-player.log')
            # Send directly to Unity, including when the desktop focus belongs
            # to another application. Never type P into the user's editor.
            self.ui.send_key_event('p', True)
            self.key_down_at = now
            self.pending['attempts'] += 1
            self.pending.setdefault('respawn_requested_unix', time.time())
            self.next_attempt = now + 1
            self.save()

    def queue_outcome(self, outcome, now):
        if self.pending is not None:
            # A suicide explosion emits both player-death and drone-destruction
            # events. Keep a single countdown for the round, with death priority.
            if outcome == 'player_death' and self.pending['outcome'] != 'player_death':
                self.pending['outcome'] = outcome
                self.pending['death_detected_unix'] = time.time()
                self.save()
            return
        self.pending = {'outcome': outcome, 'outcome_detected_unix': time.time(),
                        'reset_delay_sec': self.reset_delay, 'attempts': 0}
        if outcome == 'player_death':
            self.pending['death_detected_unix'] = self.pending['outcome_detected_unix']
        self.events.append(self.pending)
        self.next_attempt = now + self.reset_delay
        label = '被无人机炸死' if outcome == 'player_death' else '无人机已被击落'
        print(f'FPS：{label}，保留结果 {self.reset_delay:g} 秒后重置。', flush=True)
        self.save()

    def report(self):
        return {'auto_respawn': True, 'reset_delay_sec': self.reset_delay,
                'deaths': sum(event['outcome'] == 'player_death' for event in self.events),
                'drones_destroyed': sum(event['outcome'] == 'drone_destroyed' for event in self.events),
                'respawns': sum('respawn_confirmed_unix' in event for event in self.events),
                'events': self.events}

    def save(self):
        self.report_path.write_text(json.dumps(self.report(), indent=2) + '\n')

    def close(self):
        if self.key_down_at is not None:
            self.ui.send_key_event('p', False)
            self.key_down_at = None
        self.player_log.close()
