import io
import logging
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.core import logging as rose_logging


class FileLoggingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = logging.getLogger()
        self.old_handlers = self.root.handlers[:]
        self.old_level = self.root.level
        self.addCleanup(self.restore_logging)
        mode = patch.object(rose_logging, '_CURRENT_LOG_MODE', rose_logging.get_log_mode())
        mode.start()
        self.addCleanup(mode.stop)
        with (
            patch('utils.core.paths.get_user_data_dir', return_value=Path(self.temp.name)),
            patch('sys.stdout', io.StringIO()),
            patch('sys.stderr', io.StringIO()),
        ):
            rose_logging.setup_logging('verbose')
        self.handlers = self.root.handlers[:]
        self.file_output = next(
            handler for handler in self.handlers
            if isinstance(getattr(handler, 'target_handler', handler), rose_logging.SizeRotatingCompositeHandler)
        )
        self.file_handler = getattr(self.file_output, 'target_handler', self.file_output)
        self.log_path = self.file_handler.base_path
        self.logger = logging.getLogger('file-logging-test')
        for handler in self.handlers:
            if hasattr(handler, 'queue'):
                handler.queue.join()

    def restore_logging(self):
        for handler in self.root.handlers[:]:
            handler.close()
        self.root.handlers[:] = self.old_handlers
        self.root.setLevel(self.old_level)

    def close_outputs(self):
        for handler in self.handlers:
            handler.close()

    def test_the_log_file_is_the_one_this_session_writes(self):
        # The init error dialogs show it (they read a handler the tracer logger does not have)
        self.assertEqual(rose_logging.get_log_file(), self.log_path)
        self.assertTrue(rose_logging.get_log_file().is_file())

    def test_slow_disk_does_not_block_the_calling_thread(self):
        entered = threading.Event()
        release = threading.Event()
        returned = threading.Event()

        def slow_write(record):
            entered.set()
            release.wait(5)

        def log_from_bridge():
            self.logger.info('client request')
            returned.set()

        with patch.object(self.file_handler.current_handler, 'emit', side_effect=slow_write):
            caller = threading.Thread(target=log_from_bridge)
            caller.start()
            try:
                self.assertTrue(entered.wait(1), 'The file write was not reached')
                self.assertTrue(returned.wait(0.5), 'The caller is waiting for disk I/O')
            finally:
                release.set()
                caller.join(2)
                self.close_outputs()

    def test_close_writes_pending_records_before_closing_the_file(self):
        entered = threading.Event()
        release = threading.Event()
        closed = threading.Event()
        emit = self.file_handler.current_handler.emit

        def slow_first_write(record):
            if record.getMessage() == 'first':
                entered.set()
                release.wait(5)
            emit(record)

        def close():
            self.file_output.close()
            closed.set()

        with patch.object(self.file_handler.current_handler, 'emit', side_effect=slow_first_write):
            caller = threading.Thread(target=lambda: self.logger.info('first'))
            caller.start()
            closer = threading.Thread(target=close)
            try:
                self.assertTrue(entered.wait(1))
                self.logger.info('second')
                self.logger.info('last')
                closer.start()
                self.assertFalse(closed.wait(0.05))
                release.set()
                self.assertTrue(closed.wait(2))
            finally:
                release.set()
                caller.join(2)
                if closer.ident is not None:
                    closer.join(2)

        text = self.log_path.read_text(encoding='utf-8')
        self.assertLess(text.index('first'), text.index('second'))
        self.assertLess(text.index('second'), text.index('last'))
        self.assertIsNone(self.file_handler.current_handler.stream)

    def test_full_queue_does_not_block_the_caller(self):
        entered = threading.Event()
        release = threading.Event()
        returned = threading.Event()

        def slow_write(record):
            entered.set()
            release.wait(5)

        def log_many():
            for index in range(1100):
                self.logger.info('record %s', index)
            returned.set()

        with patch.object(self.file_handler.current_handler, 'emit', side_effect=slow_write):
            caller = threading.Thread(target=log_many)
            caller.start()
            try:
                self.assertTrue(entered.wait(1))
                self.assertTrue(returned.wait(1), 'A full log queue blocked the caller')
            finally:
                release.set()
                caller.join(2)
                self.close_outputs()

    def test_file_keeps_levels_unicode_and_exception_tracebacks(self):
        self.logger.log(rose_logging.TRACE, 'filtered trace')
        self.logger.debug('debug details')
        try:
            raise ValueError('example failure')
        except ValueError:
            self.logger.exception('Ошибка запроса')
        self.close_outputs()

        text = self.log_path.read_text(encoding='utf-8')
        self.assertNotIn('filtered trace', text)
        self.assertIn('DEBUG', text)
        self.assertIn('debug details', text)
        self.assertIn('Ошибка запроса', text)
        self.assertIn('Traceback (most recent call last)', text)
        self.assertIn('ValueError: example failure', text)

    def test_file_timestamp_is_the_event_time(self):
        record = self.logger.makeRecord(self.logger.name, logging.INFO, __file__, 0, 'past event', (), None)
        record.created = 946684800
        self.logger.handle(record)
        self.close_outputs()

        expected = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(record.created))
        self.assertIn(f'{expected} | INFO    | past event', self.log_path.read_text(encoding='utf-8'))

    def test_queued_records_are_written_across_rotation(self):
        self.file_handler.max_bytes = 1
        self.logger.info('before rotation')
        self.logger.info('after rotation')
        self.close_outputs()

        paths = list(self.log_path.parent.glob(self.log_path.name + '*'))
        text = ''.join(path.read_text(encoding='utf-8') for path in paths)
        self.assertGreater(len(paths), 1)
        self.assertIn('before rotation', text)
        self.assertIn('after rotation', text)

    def test_normal_process_exit_writes_pending_file_records(self):
        directory = Path(self.temp.name) / 'child'
        script = '''
import logging
import sys
from pathlib import Path
from unittest.mock import patch
from utils.core.logging import setup_logging

with patch('utils.core.paths.get_user_data_dir', return_value=Path(sys.argv[1])):
    setup_logging('verbose')
for index in range(50):
    logging.getLogger('exit-test').info('exit record %s', index)
'''
        result = subprocess.run(
            [sys.executable, '-c', script, str(directory)],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
        (path,) = (directory / 'logs').glob('rose_*.log')
        text = path.read_text(encoding='utf-8')
        self.assertEqual(text.count('exit record '), 50)
        self.assertIn('exit record 49', text)

    def test_a_forced_exit_writes_pending_file_records(self):
        directory = Path(self.temp.name) / 'forced'
        script = '''
import logging
import sys
from pathlib import Path
from unittest.mock import patch
from utils.core.logging import exit_now, setup_logging

with patch('utils.core.paths.get_user_data_dir', return_value=Path(sys.argv[1])):
    setup_logging('verbose')
for index in range(300):
    logging.getLogger('exit-test').warning('forced record %s', index)
logging.getLogger('exit-test').error('forcing the exit')
exit_now(3)
'''
        result = subprocess.run(
            [sys.executable, '-c', script, str(directory)],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 3, result.stderr.decode('utf-8', errors='replace'))
        (path,) = (directory / 'logs').glob('rose_*.log')
        text = path.read_text(encoding='utf-8')
        self.assertEqual(text.count('forced record '), 300)
        self.assertIn('forcing the exit', text)
