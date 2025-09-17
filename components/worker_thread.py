from PyQt6.QtCore import QThread, pyqtSignal


class WorkerThread(QThread):
    progress = pyqtSignal(object)  # Signal to emit progress updates with any data type
    finished = pyqtSignal()  # Signal to indicate task completion
    error = pyqtSignal(str)  # Signal to emit error messages
    result_signal = pyqtSignal(object)  # Optional: Signal to emit the final result

    def __init__(self, task, *args, **kwargs):
        super().__init__()
        self.task = task
        self.args = args
        self.kwargs = kwargs
        self._stop_requested = False
        # to handle deletion
        self.finished.connect(self.deleteLater)
        self.result_return = None

    def run(self):
        """Run the task in the thread."""
        try:
            self._stop_requested = False
            self.result_return = self.task(self, *self.args, **self.kwargs)
            if not self._stop_requested:
                if self.result_return is not None:
                    self.result_signal.emit(self.result_return)  # Emit the final result if available
                self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))
        finally:
            if not self._stop_requested:
                if self.result_return is not None:
                    self.result_signal.emit(self.result_return)  # Emit the final result if available

    def stop(self):
        """Request the thread to stop gracefully."""
        self._stop_requested = True

    def is_stop_requested(self):
        """Check if a stop has been requested."""
        return self._stop_requested
