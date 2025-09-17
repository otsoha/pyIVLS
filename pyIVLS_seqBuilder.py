# File: pyIVLS_seqBuilder.py
# GUI and functionality for the sequence builder in the QtDockWindow
#
# ver. 0.1
# ivarad
# 25.05.21
from os.path import sep
import os
import copy
import traceback

from PyQt6 import uic
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, Qt
from PyQt6.QtGui import QStandardItemModel, QStandardItem, QAction
from PyQt6.QtWidgets import QFileDialog, QMenu
from PyQt6.QtCore import QModelIndex

from components.threadStopped import thread_with_exception
from pathvalidate import is_valid_filename
import json


class pyIVLS_seqBuilder(QObject):
    #### Properties
    @property
    def item(self):
        return self._item

    @item.setter
    def item(self, value):
        if isinstance(value, QStandardItem):
            self._item = value
            # find the instance of the item in the model
            index = self.model.indexFromItem(value)
            if index.isValid():  # catch invisible root item
                self.widget.treeView.setCurrentIndex(index)
        else:
            raise TypeError("seqBuilder: Tried to assign a non-QStandardItem")

    #### Signals for communication

    info_message = pyqtSignal(str)
    _sigSeqEnd = pyqtSignal()
    log_message = pyqtSignal(str)

    #### Slots for communication
    @pyqtSlot(dict, list)
    def getPluginFunctions(self, plugin_dict, plugin_functions):
        """Populates the list of available functions for building sequencies. This is called from the container signal "seqComponents_signal".

        Args:
            plugin_dict: dict of available plugins needed to extract class (step or loop)
            plugin_functions: list of available functions returned by plugins
        """
        self.widget.comboBox_function.currentIndexChanged.disconnect(self.update_classView)
        self.available_instructions = {}
        self.widget.comboBox_function.clear()
        for plugin in plugin_dict:
            if not plugin_dict[plugin]["load"] == "True":
                continue
            if ("step" in plugin_dict[plugin]["class"]) or ("loop" in plugin_dict[plugin]["class"]):
                self.widget.comboBox_function.addItem(plugin)
                class_list = []
                if "step" in plugin_dict[plugin]["class"]:
                    class_list.append("step")
                if "loop" in plugin_dict[plugin]["class"]:
                    class_list.append("loop")
                for functions in plugin_functions:
                    if plugin in functions:
                        self.available_instructions[plugin] = {
                            "class": class_list,
                            "functions": functions[plugin],
                        }
                        break
        self.widget.comboBox_function.currentIndexChanged.connect(self.update_classView)
        self.update_classView()

    #### external functions

    #### Slots for interThread interaction
    @pyqtSlot()
    def _setNotRunning(self):
        self._setRunStatus(False)

    #### Internal functions
    def __init__(self, path):
        super().__init__()
        ui_file_name = path + "components" + sep + "pyIVLS_seqBuilder.ui"
        self.widget = uic.loadUi(ui_file_name)
        self.path = path

        self._connect_signals()
        self._init_treeView()

    def _init_treeView(self):
        self.model = QStandardItemModel(self.widget.treeView)
        self.model.setHorizontalHeaderLabels(["Step function", "Step class"])
        self._item = QStandardItem("pyIVLS measurement sequence")
        self.item.setEditable(False)
        self.model.appendRow(self.item)
        # set the item as active
        self.update_treeView()
        self.widget.treeView.setCurrentIndex(self.model.index(0, 0))
        #

    def _connect_signals(self):
        self.widget.comboBox_function.currentIndexChanged.connect(self.update_classView)
        self.widget.addInstructionButton.clicked.connect(self._addInstructionAction)
        self.widget.saveButton.clicked.connect(self._saveRecipeAction)
        self.widget.readButton.clicked.connect(self._readRecipeAction)
        self.widget.directoryButton.clicked.connect(self._getAddress)
        self.widget.runButton.clicked.connect(self._runAction)
        self.widget.stopButton.clicked.connect(self._stopAction)
        self.widget.testButton.clicked.connect(self._test_action)
        self._sigSeqEnd.connect(self._setNotRunning)
        self.widget.updateSettings.clicked.connect(self._updateInstructionSettings)
        self.widget.readSettingsButton.clicked.connect(self.read_and_update_instruction_settings)

        # connect the label click on gds to a function
        # add a custom context menu in the list widget to allow point deletion
        self.widget.treeView.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.widget.treeView.customContextMenuRequested.connect(self._tree_context_menu)
        self.widget.treeView.clicked.connect(self._root_item_changed)

    #### GUI functions

    def _tree_context_menu(self, position):
        def remove_item(row, idx_parent):
            # check if the row has children
            item = self.model.itemFromIndex(self.model.index(row, 0, idx_parent))
            if item.rowCount() > 0:
                self.info_message.emit("Can not delete item with children")
                return
            if item == self.model.invisibleRootItem().child(0):
                self.info_message.emit("Can not delete root item")
                return
            self.model.removeRow(row, idx_parent)
            # get the root item
            root_item = self.model.invisibleRootItem()
            # get the first child of the root item
            self.item = root_item.child(0)

        def update_settings_for_selected_item(row, idx_parent):
            item = self.model.itemFromIndex(self.model.index(row, 0, idx_parent))
            self._updateInstructionSettings(item)

        idx: QModelIndex = self.widget.treeView.indexAt(position)
        # get parent index
        idx_parent = idx.parent()
        # get the row number of the index
        row = idx.row()

        # check if the row has content
        if not idx.isValid():
            return

        menu = QMenu()
        delete_action = QAction("Delete", self.widget.treeView)
        update_action = QAction("Update Settings", self.widget.treeView)
        update_action.triggered.connect(lambda: update_settings_for_selected_item(row, idx_parent))
        delete_action.triggered.connect(lambda: remove_item(row, idx_parent))
        menu.addAction(update_action)
        menu.addAction(delete_action)
        menu.exec(self.widget.treeView.mapToGlobal(position))

    def _root_item_changed(self, idx):
        if idx.column() != 0:
            # modify the index to point to the first column
            idx = idx.siblingAtColumn(0)
        # read the contents of the entire line, aka column 0 and 1
        selected_item = self.model.itemFromIndex(idx)
        if selected_item is not None:
            # function_text = selected_item.text()
            item_idx = selected_item.index()
            # get the class text from the second column
            class_text = self.model.itemFromIndex(item_idx.siblingAtColumn(1)).text()

            if class_text == "step":
                # if the class is a step, set the item to be the parent item
                if self.item.parent() is not None:
                    self.item = self.item.parent()
                else:
                    self.item = self.model.invisibleRootItem().child(0)
            else:
                self.item = self.model.itemFromIndex(idx)

            #### GUI functions

    def update_classView(self):
        self.widget.comboBox_class.clear()
        if not (self.widget.comboBox_function.currentText() == "" or self.widget.comboBox_function.currentText() == "loop end"):
            for item in self.available_instructions[self.widget.comboBox_function.currentText()]["class"]:
                self.widget.comboBox_class.addItem(item)

    def update_treeView(self):
        self.widget.treeView.setModel(self.model)
        self.widget.treeView.expandAll()

    def _getAddress(self):
        address = self.widget.lineEdit_path.text()
        if not (os.path.exists(address)):
            address = self.path
        address = QFileDialog.getExistingDirectory(
            None,
            "Select directory for saving",
            address,
            options=QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks,
        )
        if address:
            self.widget.lineEdit_path.setText(address)

    def _saveRecipeAction(self):
        filename = self.widget.lineEdit_filename.text()
        if not is_valid_filename(filename):
            self.info_message.emit("Can not save sequence. Filename is invalid.")
            return 1
        with open(self.widget.lineEdit_path.text() + sep + filename, "w") as file:
            json.dump(
                self.extract_data(self.model.invisibleRootItem().child(0)),
                file,
                indent=4,
            )

    def _readRecipeAction(self):
        filename = QFileDialog.getOpenFileName(None, "Open pyIVLS sequence file", self.path, "json (*.json);; all (*.*)")
        if not filename[0]:
            return 1
        with open(filename[0], "r") as file:
            data = json.load(file)
        self._init_treeView()
        stack = copy.deepcopy(data)  #### it is necessary to make sure that we did not modify original data
        looping = []  # this will keep track of the steps inside the loop, every element is +1 depth to hierarchy level, value of the element is amount of steps left on the hierechy level
        while not stack == []:
            stackItem = stack.pop(0)
            if not looping == []:
                if looping[-1] == 0:
                    self.item = self.item.parent()
                    looping.pop(-1)
                else:
                    looping[-1] = looping[-1] - 1
            nextItem = QStandardItem(stackItem["function"])
            nextItem.setData(stackItem["settings"], Qt.ItemDataRole.UserRole)
            self.item.appendRow([nextItem, QStandardItem(stackItem["class"])])
            if stackItem["class"] == "loop":
                looping.append(len(stackItem["looping"]))
                stack = stackItem["looping"] + stack
                self.item = nextItem

    def _setRunStatus(self, status):
        self.widget.runButton.setEnabled(not status)
        self.widget.stopButton.setEnabled(status)

    def _test_action(self) -> bool:
        """Checks for self-referencing items and empty loops."""

        def has_self_as_child(item):
            """
            Recursively checks if the given item has itself as a child.
            """
            for row in range(item.rowCount()):
                child = item.child(row, 0)
                if child.text() == item.text() or has_self_as_child(child):
                    return True
            return False

        def loop_has_step_descendant(loop_item):
            """
            Recursively checks if a loop item has at least one descendant of class 'step'.
            """
            for row in range(loop_item.rowCount()):
                child = loop_item.child(row, 0)
                class_item = loop_item.child(row, 1)
                if class_item and class_item.text() == "step":
                    return True
                if loop_has_step_descendant(child):
                    return True
            return False

        root_item = self.model.invisibleRootItem().child(0)
        if has_self_as_child(root_item):
            self.info_message.emit("Error: item cannot have itself as a child.")
            return False

        # Check for empty loops
        def check_empty_loops(item) -> bool:
            for row in range(item.rowCount()):
                child_func = item.child(row, 0)
                child_class = item.child(row, 1)
                if child_class and child_class.text() == "loop":
                    if not loop_has_step_descendant(child_func):
                        self.info_message.emit(f"Error: Loop '{child_func.text()}' does not contain any step instructions.")
                        return True
                check_empty_loops(child_func)
                return False

        empty_loops = check_empty_loops(root_item)
        return not empty_loops

    #### Sequence functions

    def _addInstructionAction(self):
        instructionFunc = self.widget.comboBox_function.currentText()
        if instructionFunc == "":
            self.info_message.emit("Instruction function cannot be empty")
            return 1
        if instructionFunc == "loop end":
            if self.item.parent() is None:
                self.info_message.emit("Cannot end loop as there are no unfinished loops")
                return 1
            else:
                self.item = self.item.parent()
                return 0

        # Check if adding the instruction creates a circular reference BEFORE adding
        if self._is_in_ancestry(self.item, instructionFunc) or self.item.text() == instructionFunc:
            self.info_message.emit("Cannot add a plugin that already exists in its ancestry or as a direct child")
            return 1

        status, instructionSettings = self.available_instructions[instructionFunc]["functions"]["parse_settings_widget"]()
        if status:
            self.info_message.emit(instructionSettings["Error message"])
            return 1

        # Check the instruction class of self.item
        instructionClass = self.widget.comboBox_class.currentText()

        nextItem = QStandardItem(instructionFunc)
        nextItem.setData(instructionSettings, Qt.ItemDataRole.UserRole)
        self.item.appendRow([nextItem, QStandardItem(instructionClass)])

        # Update the parent item to be the newly added item if it is a loop
        if instructionClass == "loop":
            self.item = nextItem

        self.update_treeView()

    def _is_in_ancestry(self, item, name):
        """
        Recursively checks if the given name exists in the ancestry of the item.

        Args:
            item (QStandardItem): The item to start checking from.
            name (str): The name to check against.

        Returns:
            bool: True if the name exists in the ancestry, False otherwise.
        """
        parent = item.parent()
        while parent is not None:
            if parent.text() == name:
                return True
            parent = parent.parent()
        return False

    def extract_data(self, item):
        """Recursively extract the visible and hidden data from the model"""
        data = []
        # Recursively extract data from children
        for row in range(item.rowCount()):
            step_data = {}
            step_data["function"] = item.child(row, 0).text()
            step_data["class"] = item.child(row, 1).text()
            step_data["settings"] = item.child(row, 0).data(Qt.ItemDataRole.UserRole)
            if item.child(row, 0).rowCount() > 0:
                step_data["looping"] = self.extract_data(item.child(row, 0))
            data.append(step_data)
        return data

    def _runParser(self):
        """Runs the sequence parser, iterates through the sequence and executes the steps."""
        try:
            ###############Main logic of iteration: 0 - no iterations, 1 - only start point, 2 - start end end point, iterstep = (end-start)/(iternum -1).The same is used in sweepCommon for drainVoltage. !!!Adapt to logic of iteration, do not modify it!!!
            self.log_message.emit("pyIVLS_seqBuilder: Running sequence parser")
            data = self.extract_data(self.model.invisibleRootItem().child(0))
            stackData = copy.deepcopy(data)  #### it is necessary to make sure that we did not modify original data
            looping = []  # this will keep track of the steps inside the loop, every element is a dict[{looping -the steps to repeat, loopFunction - looping Function, totalSteps - number of steps in loop, currentStep, totalIterations, currentIteration}]
            while (not stackData == []) or (not looping == []):
                if not looping == []:
                    if looping[-1]["currentStep"] == 0:
                        [status, iterText] = self.available_instructions[looping[-1]["loopFunction"]]["functions"]["loopingIteration"](looping[-1]["currentIteration"])
                        if status:
                            raise ValueError(iterText)
                            """
                            print(f"Error: {iterText}")
                            self._sigSeqEnd.emit()  # Added
                            self._setNotRunning()  # Added
                            break
                            """
                        looping[-1]["namePostfix"] = iterText
                        looping[-1]["currentIteration"] = looping[-1]["currentIteration"] + 1
                        looping[-1]["currentStep"] = looping[-1]["currentStep"] + 1
                    elif looping[-1]["currentStep"] == looping[-1]["totalSteps"]:
                        if looping[-1]["currentIteration"] < looping[-1]["totalIterations"]:
                            looping[-1]["currentStep"] = 0
                            stackData = looping[-1]["looping"] + stackData
                        else:
                            looping.pop(-1)
                        continue
                    else:
                        looping[-1]["currentStep"] = looping[-1]["currentStep"] + 1
                stackItem = stackData.pop(0)
                nextStepFunction = stackItem["function"]
                nextStepSettings = stackItem["settings"]
                nextStepClass = stackItem["class"]
                self.available_instructions[nextStepFunction]["functions"]["setSettings"](nextStepSettings)
                if nextStepClass == "step":
                    namePostfix = ""
                    for loopItem in looping:
                        namePostfix = namePostfix + loopItem["namePostfix"]
                    [status, message] = self.available_instructions[nextStepFunction]["functions"]["sequenceStep"](namePostfix)
                    if status:
                        raise ValueError(message)
                        """
                        print(f"Error: {message}")
                        self._sigSeqEnd.emit()  # Added
                        self._setNotRunning()  # Added
                        """
                        break
                if nextStepClass == "loop":
                    iter = self.available_instructions[nextStepFunction]["functions"]["getIterations"]()
                    looping.append({"looping": stackItem["looping"], "loopFunction": nextStepFunction, "totalSteps": len(stackItem["looping"]), "currentStep": 0, "totalIterations": iter, "currentIteration": 0, "namePostfix": ""})
                    stackData = stackItem["looping"] + stackData
            self.log_message.emit("pyIVLS_seqBuilder: Sequence parser finished")
            self._sigSeqEnd.emit()
        except Exception as e:
            print(f"Error occurred: {e}")
        finally:
            self._setNotRunning()
            self._sigSeqEnd.emit()  


    def _runAction(self):
        # disable controls
        # recipe itself should be checked (i.e. no empty loops, same plugin is not used as step in the same plugins loop, etc.), but parse settings are done during the recipe formation
        passed = self._test_action()
        if not passed:
            self.info_message.emit("Sequence test failed. Please fix the errors before running the sequence.")
            return [1, "Sequence test failed."]
        self._setRunStatus(True)
        self.run_thread = thread_with_exception(self._runParser)
        self.run_thread.start()
        return [0, "OK"]

    def _stopAction(self):
        """Stops the running sequence thread."""
        if hasattr(self, "run_thread") and self.run_thread.is_alive():
            try:
                result = self.run_thread.thread_stop()
                self.info_message.emit("Stop requested: " + result[1])
            except Exception as e:
                self.info_message.emit(f"Failed to stop thread: {e}")
        else:
            self.info_message.emit("No running sequence to stop.")
        self._setRunStatus(False)

    def _updateInstructionSettings(self, item=None):
        """
        Updates the settings for a single instruction or all instructions in the sequence.

        Args:
            item (QStandardItem, optional): The item to update. If None, updates all instructions.
        """

        def update_item_settings(item):
            instructionFunc = item.text()
            if instructionFunc not in self.available_instructions:
                return [f"Instruction {instructionFunc} is not available."]

            # Validate settings using parse_settings_widget
            status, newSettings = self.available_instructions[instructionFunc]["functions"]["parse_settings_widget"]()
            if status:
                return [newSettings["Error message"]]

            # Compare old and new settings
            oldSettings = item.data(Qt.ItemDataRole.UserRole)
            changes = []
            for key, newValue in newSettings.items():
                oldValue = oldSettings.get(key, None) if oldSettings else None
                if oldValue != newValue:
                    changes.append(f"{key}: {oldValue} -> {newValue}")

            # Update the item's settings
            item.setData(newSettings, Qt.ItemDataRole.UserRole)

            return changes

        all_changes = []

        if item:
            # Update a single item
            changes = update_item_settings(item)
            if changes:
                all_changes.extend(changes)
        else:
            # Update all items in the sequence
            def traverse_and_update(item):
                for row in range(item.rowCount()):
                    child = item.child(row, 0)
                    changes = update_item_settings(child)
                    if changes:
                        all_changes.extend(changes)
                    traverse_and_update(child)

            root_item = self.model.invisibleRootItem()
            if root_item is None:
                self.info_message.emit("Error: The sequence tree is not properly initialized.")
                return

            first_child = root_item.child(0)
            if first_child is None:
                self.info_message.emit("Error: The sequence tree has no root item.")
                return

            traverse_and_update(first_child)

        # Emit a single aggregated message
        if all_changes:
            self.info_message.emit("Settings updated with the following changes:\n" + "\n".join(all_changes))
        else:
            self.info_message.emit("No changes were made.")

    def update_all_instruction_guis(self):
        """
        Iterates through all instructions in the sequence and calls `set_gui_from_settings` for each instruction plugin.
        Logs a message if `set_gui_from_settings` is not implemented for a plugin.
        """

        def update_item_gui(item):
            instruction_func = item.text()
            if instruction_func not in self.available_instructions:
                self.info_message.emit(f"Instruction {instruction_func} is not available.")
                return

            # Get the plugin's set_gui_from_settings function
            plugin_functions = self.available_instructions[instruction_func]["functions"]
            if "set_gui_from_settings" in plugin_functions:
                try:
                    plugin_functions["set_gui_from_settings"]()
                except Exception as e:
                    self.info_message.emit(f"Error while updating GUI for {instruction_func}: {str(e)}")
            else:
                self.info_message.emit(f"set_gui_from_settings is not implemented for {instruction_func}.")

        def traverse_and_update(item):
            for row in range(item.rowCount()):
                child = item.child(row, 0)
                update_item_gui(child)
                traverse_and_update(child)

        root_item = self.model.invisibleRootItem()
        if root_item is None:
            self.info_message.emit("Error: The sequence tree is not properly initialized.")
            return

        first_child = root_item.child(0)
        if first_child is None:
            self.info_message.emit("Error: The sequence tree has no root item.")
            return

        traverse_and_update(first_child)

    def read_and_update_instruction_settings(self):
        """
        Sends the saved settings data for all instructions to the plugins,
        and calls `set_gui_from_settings` to update the GUI fields based on the saved settings.
        """

        def process_item_settings(item):
            instruction_func = item.text()
            if instruction_func not in self.available_instructions:
                self.info_message.emit(f"Instruction {instruction_func} is not available.")
                return

            # Retrieve saved settings from the item
            saved_settings = item.data(Qt.ItemDataRole.UserRole)
            if not saved_settings:
                self.info_message.emit(f"No saved settings found for {instruction_func}.")
                return

            # Send the saved settings to the plugin
            plugin_functions = self.available_instructions[instruction_func]["functions"]
            if "setSettings" in plugin_functions:
                try:
                    plugin_functions["setSettings"](saved_settings)
                except Exception as e:
                    self.info_message.emit(f"Error sending settings to {instruction_func}: {str(e)}")
                    return

            # Update the GUI fields using set_gui_from_settings
            if "set_gui_from_settings" in plugin_functions:
                try:
                    plugin_functions["set_gui_from_settings"]()
                except Exception as e:
                    detailed_error = traceback.format_exc()
                    self.info_message.emit(f"Error updating GUI for {instruction_func}: {str(e)}\n{detailed_error}")
            else:
                self.info_message.emit(f"set_gui_from_settings is not implemented for {instruction_func}.")

        def traverse_and_process(item):
            for row in range(item.rowCount()):
                child = item.child(row, 0)
                process_item_settings(child)
                traverse_and_process(child)

        root_item = self.model.invisibleRootItem()
        if root_item is None:
            self.info_message.emit("Error: The sequence tree is not properly initialized.")
            return

        first_child = root_item.child(0)
        if first_child is None:
            self.info_message.emit("Error: The sequence tree has no root item.")
            return

        traverse_and_process(first_child)
