"""Regression checks for choosing 1–5 instances without running LDPlayer."""
import importlib.util
from pathlib import Path
import queue
import unittest
from unittest.mock import Mock, patch


SOURCE = Path(__file__).resolve().parents[1] / 'gestoria_5_instancias.py'
SPEC = importlib.util.spec_from_file_location('gestoria_instance_count', SOURCE)
bot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bot)


class Variable:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def application(cantidad=3):
    app = bot.App.__new__(bot.App)
    app.busy = False
    app.nombres = tuple(bot.nombres_instancias(cantidad))
    app.iniciado = True
    app.cantidad_var = Variable(str(cantidad))
    app.inst_sel = Variable(app.nombres[-1])
    app.marcos_filas = {name: Mock() for name in bot.TODOS_NOMBRES}
    app.aviso = Mock()
    app.selector_instancia = Mock()
    app.selector_cantidad = Mock()
    app.btn = Mock()
    app.events = queue.Queue()
    app.estado = Mock()
    app.emit = Mock()
    app.ruta = Mock(return_value='fake/ldconsole.exe')
    return app


def instance(index, running=True):
    return {'index': str(index), 'real': f'GESTORIA_DIAZ_00{index}',
            'android': running, 'pid': str(100 + index) if running else '0',
            'running': running}


class InstanceCountTests(unittest.TestCase):
    def test_all_allowed_counts_have_correct_unique_names(self):
        for count in range(1, 6):
            with self.subTest(count=count):
                expected = [f'GESTORIA_DIAZ_00{i}' for i in range(1, count + 1)]
                self.assertEqual(bot.nombres_instancias(count), expected)
                self.assertEqual(bot.nombres_instancias(str(count)), expected)

    def test_count_rejects_invalid_or_fractional_values(self):
        for invalid in (0, 6, -1, 2.5, True, None, '', 'abc', '2.5'):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    bot.nombres_instancias(invalid)

    def test_selection_can_change_one_to_five_to_two(self):
        app = application()
        for count in (1, 5, 2):
            with self.subTest(count=count):
                app.cantidad_var.set(str(count))
                self.assertTrue(app.aplicar_cantidad())
                self.assertEqual(app.nombres, tuple(bot.nombres_instancias(count)))
                self.assertIn(app.inst_sel.get(), app.nombres)
                self.assertFalse(app.iniciado)
                app.selector_instancia.configure.assert_called_with(values=app.nombres)
                for name, frame in app.marcos_filas.items():
                    if name in app.nombres:
                        frame.pack.assert_called_with(fill='x', pady=3)
                    else:
                        frame.pack_forget.assert_called_with()

    def test_selection_is_frozen_while_preparing(self):
        app = application(2)
        app.busy = True
        app.cantidad_var.set('5')
        self.assertFalse(app.aplicar_cantidad())
        self.assertEqual(app.nombres, tuple(bot.nombres_instancias(2)))
        self.assertEqual(app.cantidad_var.get(), '2')
        app.selector_instancia.configure.assert_not_called()

    def test_selection_is_restored_while_a_pin_unlock_is_in_flight(self):
        app = application(2)
        app.desbloqueando = True
        app.cantidad_var.set('5')
        self.assertFalse(app.aplicar_cantidad())
        self.assertEqual(app.nombres, tuple(bot.nombres_instancias(2)))
        self.assertEqual(app.cantidad_var.get(), '2')
        self.assertTrue(app.iniciado)
        app.selector_instancia.configure.assert_not_called()
        app.aviso.configure.assert_not_called()
        self.assertTrue(all(not frame.pack.called and not frame.pack_forget.called
                            for frame in app.marcos_filas.values()))

    def test_prepare_disables_count_selector_and_starts_only_on_request(self):
        app = application(1)
        app.iniciado = False
        app.cantidad_var.set('5')
        with patch.object(bot.threading, 'Thread') as thread:
            app.start()
        self.assertTrue(app.iniciado)
        self.assertTrue(app.busy)
        self.assertEqual(app.nombres, tuple(bot.nombres_instancias(5)))
        app.selector_cantidad.configure.assert_called_with(state='disabled')
        thread.assert_called_once_with(target=app.work,
                                       args=('fake/ldconsole.exe',), daemon=True)
        thread.return_value.start.assert_called_once_with()

    def test_work_creates_and_launches_only_the_chosen_instances(self):
        for count in (1, 3, 5):
            with self.subTest(count=count):
                app = application(count)
                # Existing instances beyond the selection must be preserved.
                instances = {name: instance(i) for i, name in enumerate(
                    bot.TODOS_NOMBRES, start=1) if i > count}
                instances['PLANTILLA'] = {
                    'index': '0', 'real': 'PLANTILLA', 'android': False,
                    'pid': '0', 'running': False}

                def command(console, *args, **kwargs):
                    if args[0] == 'copy':
                        name = args[2]
                        instances[name] = instance(int(name[-1]), running=False)
                    elif args[0] == 'launch':
                        for info in instances.values():
                            if info['index'] == args[2]:
                                info.update(running=True, android=True)
                    return ''

                with patch.object(bot, 'reparar', return_value=instances) as repair, \
                     patch.object(bot, 'listar', side_effect=lambda path: instances), \
                     patch.object(bot, 'run', side_effect=command) as run, \
                     patch.object(bot, 'celular'), patch.object(bot.time, 'sleep'):
                    app.work('fake/ldconsole.exe')
                self.assertEqual(repair.call_args.args[2], app.nombres)
                copied = [call.args[3] for call in run.call_args_list
                          if call.args[1] == 'copy']
                launched = [call.args[3] for call in run.call_args_list
                            if call.args[1] == 'launch']
                self.assertEqual(copied, list(app.nombres))
                self.assertEqual(launched, [str(i) for i in range(1, count + 1)])
                self.assertFalse(any(call.args[1] in ('remove', 'quit')
                                     for call in run.call_args_list))
                self.assertTrue(all(name in instances for name in bot.TODOS_NOMBRES))

    def test_repair_does_not_inspect_or_restart_unselected_instances(self):
        instances = {name: instance(i) for i, name in enumerate(bot.TODOS_NOMBRES, start=1)}
        app = application(1)
        with patch.object(bot, 'listar', return_value=instances), \
             patch.object(bot, 'es_tablet', return_value=False) as tablet, \
             patch.object(bot, 'run') as run, \
             patch.object(bot, 'asegurar_adb') as adb:
            result = bot.reparar('fake/ldconsole.exe', app.emit, app.nombres)
        self.assertEqual(result, instances)
        tablet.assert_called_once_with('fake/ldconsole.exe', '1')
        run.assert_not_called()
        adb.assert_not_called()

    def test_list_recognizes_the_fifth_instance_after_name_loss(self):
        with patch.object(bot, 'run', return_value='5,LDPlayer-5,0,0,1,105,0'), \
             patch.object(bot, 'leer_mapa', return_value={'GESTORIA_DIAZ_005': '5'}), \
             patch.object(bot, 'guardar_mapa') as save:
            instances = bot.listar('fake/ldconsole.exe')
        self.assertIn('GESTORIA_DIAZ_005', instances)
        self.assertEqual(instances['GESTORIA_DIAZ_005']['index'], '5')
        save.assert_not_called()

    def test_monitor_waits_for_prepare_and_only_watches_selected_instances(self):
        for started in (False, True):
            with self.subTest(started=started):
                app = application(2)
                app.iniciado = started
                app.vigilar = Mock()
                app.auto_on = True
                app.ultimo_auto = 0
                instances = {name: instance(i) for i, name in enumerate(
                    bot.TODOS_NOMBRES, start=1)}
                with patch.object(bot.time, 'sleep', side_effect=[None, StopIteration]), \
                     patch.object(bot, 'listar', return_value=instances) as listed:
                    with self.assertRaises(StopIteration):
                        app.monitor()
                if started:
                    self.assertEqual([call.args[1] for call in app.vigilar.call_args_list],
                                     list(app.nombres))
                else:
                    listed.assert_not_called()
                    app.vigilar.assert_not_called()


if __name__ == '__main__':
    unittest.main()
