"""Round timing and outcome handling, without Unity or an X11 desktop."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from fps_session import FPSAutoRespawn
from fps_settings import DRONE_EXPLOSION_LOG


class FPSRoundTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.log = Path(directory.name) / 'unity-player.log'
        self.log.write_text('Drone 0 detonated on the player at old-round.\n')
        self.ui = Mock(spec=['send_key_event'])
        self.now = 0
        mono = patch('fps_session.time.monotonic', side_effect=lambda: self.now)
        wall = patch('fps_session.time.time', side_effect=lambda: 1000 + self.now)
        mono.start()
        wall.start()
        self.addCleanup(mono.stop)
        self.addCleanup(wall.stop)
        self.session = FPSAutoRespawn(self.ui, self.log, reset_delay=2)
        self.addCleanup(self.session.close)

    def emit(self, text):
        with self.log.open('a') as stream:
            stream.write(text)
        self.session.update()

    def advance(self, seconds):
        self.now += seconds
        self.session.update()

    def confirm(self):
        self.advance(.06)
        self.emit('[YOPO] Respawn published on /respawn.\n')

    def test_death_keeps_result_before_respawn(self):
        self.session.update()
        self.assertEqual(self.session.report()['deaths'], 0)
        self.emit('Drone 0 detonated on the player at (0, 0, 0).\n')
        self.advance(1.99)
        self.ui.send_key_event.assert_not_called()
        self.advance(.02)
        self.ui.send_key_event.assert_called_once_with('p', True)
        self.confirm()
        self.assertEqual(self.ui.send_key_event.call_args.args, ('p', False))
        self.assertEqual(self.session.report()['respawns'], 1)
        self.assertGreaterEqual(self.session.events[0]['response_sec'], 2)

    def test_drone_shot_down_resets_after_delay(self):
        self.emit(DRONE_EXPLOSION_LOG + '\n')
        self.advance(1)
        self.ui.send_key_event.assert_not_called()
        self.advance(1.01)
        self.confirm()
        self.assertEqual(self.session.report()['drones_destroyed'], 1)
        self.assertEqual(self.session.report()['deaths'], 0)
        self.assertEqual(self.session.events[0]['reset_trigger'], 'automatic')

    def test_suicide_explosion_counts_once_without_extending_delay(self):
        self.emit(DRONE_EXPLOSION_LOG + '\n')
        self.advance(.5)
        self.emit('Drone 0 detonated on the player at (0, 0, 0).\n')
        self.advance(1)
        self.emit(DRONE_EXPLOSION_LOG + '\n')
        self.advance(.51)
        self.confirm()
        self.assertEqual(len(self.session.events), 1)
        self.assertEqual(self.session.report()['deaths'], 1)
        self.assertEqual(self.session.report()['drones_destroyed'], 0)
        self.assertEqual(self.session.report()['respawns'], 1)

    def test_manual_reset_cancels_delayed_reset(self):
        self.emit(DRONE_EXPLOSION_LOG + '\n')
        self.advance(.3)
        self.emit('[YOPO] Respawn published on /respawn.\n')
        self.advance(5)
        self.ui.send_key_event.assert_not_called()
        self.assertEqual(self.session.events[0]['reset_trigger'], 'manual')

    def test_partial_lines_and_next_round(self):
        self.emit('Drone Explosion ')
        self.advance(3)
        self.ui.send_key_event.assert_not_called()
        self.emit('Sound\n')
        self.advance(2.01)
        self.confirm()
        self.emit('Drone 0 detonated on the player at next-round.\n')
        self.advance(1.99)
        self.assertEqual(self.ui.send_key_event.call_count, 2)
        self.advance(.02)
        self.confirm()
        self.assertEqual(self.session.report()['respawns'], 2)


if __name__ == '__main__':
    unittest.main()
