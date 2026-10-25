"""Regresiones del modo practica y la seleccion paginada, sin abrir ventanas."""
import copy
import os
import tempfile
import unittest

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

import pygame
import main


class PracticeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_data = os.environ.get('XDG_DATA_HOME')
        os.environ['XDG_DATA_HOME'] = self.temp.name
        self.game = main.Game()

    def tearDown(self):
        pygame.quit()
        if self.old_data is None:
            os.environ.pop('XDG_DATA_HOME', None)
        else:
            os.environ['XDG_DATA_HOME'] = self.old_data
        self.temp.cleanup()

    def key(self, key):
        self.game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key))

    def test_checkpoint_restores_modes_and_consumables(self):
        g = self.game
        g.practice = True
        for mode in (main.MODE_CUBE, main.MODE_SHIP, main.MODE_BALL):
            g.start()
            g.sim._set_mode(mode)
            for _ in range(8):
                g.sim.step(main.STEP, False, False)
            g.sim.used_orbs.add(123)
            g.sim.used_pads.add(456)
            self.key(pygame.K_z)
            snapshot = copy.deepcopy(g.checkpoints[-1])
            g.sim.used_orbs.add(999)
            g.sim.die('test')
            g.respawn()
            self.assertIs(g.sim.data, g.data)
            self.assertEqual({k: v for k, v in vars(g.sim).items() if k != 'data'}, snapshot)
            g.sim.used_orbs.add(888)
            self.assertNotIn(888, g.checkpoints[-1]['used_orbs'])
            g.draw()

    def test_practice_does_not_save_normal_records(self):
        g = self.game
        g.practice = True
        g.start()
        g.sim.x = g.data.finish_x
        g.sim.finished = True
        g.record()
        self.assertEqual(g.records, {})
        self.assertFalse(os.path.exists(main.save_path()))
        self.key(pygame.K_p)
        self.assertFalse(g.practice)
        self.assertEqual(g.sim.x, main.SPAWN_X)
        g.sim.finished = True
        g.record()
        self.assertTrue(main.load_records()[g.level.name]['done'])

    def test_remove_restart_and_change_level(self):
        g = self.game
        g.practice = True
        g.start()
        g.place_checkpoint()
        g.sim.x += 20
        g.place_checkpoint()
        self.key(pygame.K_x)
        self.assertEqual(len(g.checkpoints), 1)
        g.restart()
        self.assertFalse(g.checkpoints)
        g.place_checkpoint()
        g.load_level(1)
        self.assertFalse(g.checkpoints)

    def test_falling_into_gap_kills_with_lava(self):
        from levels import LevelBuilder, Level, THEMES
        b = LevelBuilder().pit(5, 20)
        level = Level('lava-test', '', '', THEMES['neon'], b.objs, 40)
        sim = main.Sim(main.LevelData(level))
        sim.x = 8 * main.TILE
        for _ in range(120):
            sim.step(main.STEP, False, False)
            if not sim.alive:
                break
        self.assertFalse(sim.alive)
        self.assertEqual(sim.cause, 'lava')

    def test_all_menu_pages_allow_mouse_selection(self):
        g = self.game
        for i in range(len(main.LEVELS)):
            g.state = main.MENU
            g.load_level(i)
            g.draw()
            index, rect = next((j, r) for j, r in g.card_rects if j == i)
            self.assertTrue(pygame.Rect(0, 0, main.W, main.H).contains(rect))
            g.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center))
            self.assertEqual(g.sel, index)
            self.assertEqual(g.state, main.PLAY)


if __name__ == '__main__':
    unittest.main()
