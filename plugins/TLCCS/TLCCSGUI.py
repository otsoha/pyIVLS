'''
This is a GUI plugin for CCS175 spectrometer

This file should provide
- functions for interaction with other plugins (those that will be exported on get_functions hook call, these should not start with "_")
- functions that will implement functionality of the hooks (see pyIVLS_TLCCS)
- GUI functionality - code that interracts with Qt GUI elements from widgets

This plugin should have double functionality
(i) it may be independently used to run spectrometer preview and save individual spectra
(ii) it provides functionality of getting spectra for other plugins

Because of (i) it requires to send log and message signals, i.e. it is a child of QObject

version 0.2
2025.03.07
ivarad

version 0.3
added spectrometerGetIntegrationTime
added auto detection for integration time
ivarad
2025.06.11

version 0.4beta
added spectrometerGetScan as atomic method to get spectrum
Deprecated spectrometerGetSpectrum?
Deprecated spectrometerStartScan?


'''
import TLCCS_const as const

import time
import os
import numpy as np
from datetime import datetime
from pathvalidate import is_valid_filename
from PyQt6 import uic
from PyQt6.QtCore import QObject, pyqtSignal, Qt
from PyQt6.QtWidgets import QVBoxLayout, QFileDialog
from MplCanvas import MplCanvas
from threadStopped import ThreadStopped, thread_with_exception 
from threading import Lock, Event

from TLCCS import CCSDRV


class TLCCS_GUI(QObject):
    """spectrometer plugin for pyIVLS"""
    non_public_methods = [] # add function names here, if they should not be exported as public to another plugins
    public_methods = ["parse_settings_preview",
                      "parse_settings_widget", 
                      "spectrometerConnect", 
                      "spectrometerDisconnect", 
                      "spectrometerSetIntegrationTime", 
                      "spectrometerGetIntegrationTime", 
                      "spectrometerStartScan", 
                      "spectrometerGetScan",
                      "spectrometerGetSpectrum",
                      "createFile",
                      "getAutoTime"
                    ] # necessary for descendents of QObject, otherwise _get_public_methods returns a lot of QObject methods

########Signals

    log_message = pyqtSignal(str)     
    info_message = pyqtSignal(str)
    closeLock = pyqtSignal(bool) 
    
    filedelimeter = "\t"
    
    default_timerInterval = 20 # ms, it is close to 24*2 fps (twice the standard for movies and TV)
#limits for auto time detection
    autoTime_min = 0.04 # s, used to be 4
    autoTime_max = 10 #s, used to be 10000
    autoValue_min = 0.2 # spectrum value in arb.(?) units
    autoValue_max = 0.8 # spectrum value in arb.(?) units
    intTimeMaxIterations = 10

########Functions       
    def __init__(self):
        super(TLCCS_GUI,self).__init__()
        # Load the settings based on the name of this file.
        self.path = os.path.dirname(__file__) + os.path.sep
        ##IRtothink#### I do not like have filename hardly coded, 
        ############### but in any case the refrences to the GUI elements will be hardly coded, so it may be OK
        self.settingsWidget = uic.loadUi(self.path + "TLCCS_settingsWidget.ui")
        self.previewWidget = uic.loadUi(self.path + "TLCCS_MDIWidget.ui")

        # create the driver
        self.drv = CCSDRV()

        self._connect_signals()
        self._create_plt()

        self.lastspectrum = [] #data for saving from preview
        self.preview_running = False
        self.integrationTimeChanged = False
        self.scanRunning = False

        correction_file = r'SC175_correction'
        self.correction = np.loadtxt(self.path + correction_file)
        self.settings = {}

        self._scan_lock = Lock()  
    
    def _connect_signals(self):
        self.settingsWidget.connectButton.clicked.connect(self._connectAction)
        self.settingsWidget.disconnectButton.clicked.connect(self._disconnectAction)
        self.settingsWidget.setIntegrationTimeButton.clicked.connect(self._setIntTimeAction)
        self.settingsWidget.previewButton.clicked.connect(self._previewAction)
        self.settingsWidget.saveButton.clicked.connect(self._saveAction)
        self.settingsWidget.correctionCheck.stateChanged.connect(self._correctionChanged)
        self.settingsWidget.directoryButton.clicked.connect(self._getAddress)
        self.settingsWidget.getIntegrationTime_combo.currentIndexChanged.connect(self._integrationTime_mode_changed)
        self.settingsWidget.getTime_button.clicked.connect(self._getTimeAction)

    def _create_plt(self):
        self.sc = MplCanvas(self, width=5, height=4, dpi=100)
        self.axes = self.sc.fig.add_subplot(111)
       
        self.axes.set_xlabel('Wavelength (nm)')
        self.axes.set_ylabel('Intensity (calib. arb. un.)')

        self.axes.set_xlim(const.CCS175_MIN_WV,const.CCS175_MAX_WV) # limits are given by spectral range of the device

        layout = QVBoxLayout()
        layout.addWidget(self.sc._create_toolbar(self.previewWidget))
        layout.addWidget(self.sc)
        self.previewWidget.setLayout(layout)

########Functions
################################### internal

    def _update_spectrum(self):
        """Updates the spectrum in the preview window.

        Returns:
            _type_: _description_
        """
        [status, info] = self.spectrometerGetSpectrum()
        if status:
            return [status, info]    
        self.scanRunning = False
        if self.settings["previewCorrection"]:
            preview_data = [m * n * 1000 for m, n in zip(info, self.correction[:, 1])]
        else:
            preview_data = info
        xmin, xmax = self.axes.get_xlim()
        ymin, ymax = self.axes.get_ylim()
        self.axes.cla()
        self.axes.set_xlabel('Wavelength (nm)')
        self.axes.set_ylabel('Intensity (calib. arb. un.)')
        self.axes.plot(self.correction[:,0], preview_data, 'b-')
        self.axes.set_xlim(xmin,xmax)
        self.axes.set_ylim(ymin,ymax)
        self.sc.draw()
        self.lastspectrum = [info, self.settings]
        return [0, [self.correction[:,0], info]]

########Functions 
########GUI Slots

    def _connectAction(self):
        self.parse_settings_widget()
        [status, info] = self.spectrometerConnect()
        if status:
                self.log_message.emit(datetime.now().strftime("%H:%M:%S.%f") + f" : TLCCS plugin : {info}, status = {status}")
                self.info_message.emit(f"TLCCS plugin : {info['Error message']}")
                return [status, info]    
        self._GUIchange_deviceConnected(True)#see comment in _GUIchange_deviceConnected

    def _disconnectAction(self):
        if self.preview_running:
                self.info_message.emit(f"Stop preview before disconnecting")        
        else:
                [status, info] = self.spectrometerDisconnect()
                if status: ##IRtodo## some error handling is necessary, as connected devices will not allow to switch off the GUI
                    self.log_message.emit(datetime.now().strftime("%H:%M:%S.%f") + f" : TLCCS plugin : {info}, status = {status}")
                    self.info_message.emit(f"TLCCS plugin : {info['Error message']}")
                self._GUIchange_deviceConnected(False)#see comment in _GUIchange_deviceConnected
                
    def _previewAction(self):
        """interface for the preview button. Opens the camera, sets the exposure and previews the feed"""
        if self.preview_running:
            self.run_thread.thread_stop()
            if self.scanRunning:
                self.scanRunning = False
            self.preview_running = False
            self._enableSaveButton()
            self.closeLock.emit(not self.preview_running)
        else:
            [status, info] = self.parse_settings_preview()
            if status:
                self.log_message.emit(datetime.now().strftime("%H:%M:%S.%f") + f" : TLCCS plugin : {info}, status = {status}")
                self.info_message.emit(f"TLCCS plugin : {info['Error message']}")
                return [status, info]
            self.integrationTimeChanged = True
            self.preview_running = True
            self.closeLock.emit(not self.preview_running)
            self.settingsWidget.saveButton.setEnabled(False)
            self.run_thread = thread_with_exception(self._previewIteration)
            self.run_thread.start()    

    def _previewIteration(self):
        try:        
            while True:
                if self.integrationTimeChanged:
                    [status, info] = self.spectrometerSetIntegrationTime(self.settings["integrationTime"])
                    self.integrationTimeChanged = False
                    if self.settings["integrationTime"]*1000 < self.default_timerInterval:
                        self.sleep_time = self.default_timerInterval/1000
                    else:
                        self.sleep_time = self.settings["integrationTime"]
                    if status:
                        self.log_message.emit(datetime.now().strftime("%H:%M:%S.%f") + f" : TLCCS plugin : {info}, status = {status}")
                        self.info_message.emit(f"TLCCS plugin : {info['Error message']}")
                        self.preview_running = False
                        return [status, info]
                [status, info] = self.spectrometerStartScan()
                if status:
                    self.log_message.emit(datetime.now().strftime("%H:%M:%S.%f") + f" : TLCCS plugin : {info}, status = {status}")
                    self.info_message.emit(f"TLCCS plugin : {info['Error message']}")
                    self.preview_running = False
                    return [status, info]
                time.sleep(self.sleep_time)
                [status, info] = self._update_spectrum()
                if status:
                    self.log_message.emit(datetime.now().strftime("%H:%M:%S.%f") + f" : TLCCS plugin : {info}, status = {status}")
                    if not status==1:                
                        self.info_message.emit(f"TLCCS plugin : {info}")
                    return [status, info]
        except ThreadStopped:      
            ## spectrometer status shuld be checked here, if not IDLE some action may be considered
            return [0, "preview stopped"]

    def _setIntTimeAction(self):
        if self.preview_running: #this function is useful only in preview mode
            [status, info] = self._parse_settings_integrationTime()
            if status:
                self.log_message.emit(datetime.now().strftime("%H:%M:%S.%f") + f" : TLCCS plugin : {info}, status = {status}")
                self.info_message.emit(f"TLCCS plugin : {info['Error message']}")
                return [status, info]
            self.integrationTimeChanged = True
            return [0, "OK"]

    def _saveAction(self):
        [status, info] = self._parseSaveData()
        if status:
            self.info_message.emit(f"TLCCS plugin : {info['Error message']}")
            return [status, info]
        varDict ={}
        varDict['integrationtime'] = self.lastspectrum[1]['integrationTime']
        varDict['triggermode'] = 1 if self.lastspectrum[1]['externalTrigger'] else 0
        varDict['name'] = self.settings["samplename"]
        varDict['comment'] = self.settings["comment"]
        self.createFile(varDict, self.filedelimeter, address = self.settings["address"] + os.sep + self.settings["filename"] + ".csv", data = self.lastspectrum[0])
        return [0, "OK"]

    def _getTimeAction(self):
        preview_status = False
        [status, info] = self._parse_settings_autoTime()
        if status:
            self.log_message.emit(datetime.now().strftime("%H:%M:%S.%f") + f" : TLCCS plugin : {info}, status = {status}")
            self.info_message.emit(f"TLCCS plugin : {info['Error message']}")
            return [status, info]
        if self.preview_running:
            preview_status = self.preview_running
            self._previewAction()
        self.settingsWidget.saveButton.setEnabled(False)
        self.closeLock.emit(False)
        #check if get time may be used (spectrometer IDLE)
        status, autoTime = self.getAutoTime()
        if not status:
            self.settingsWidget.lineEdit_Integ.setText(f"{round(autoTime*1000)}")
        else:
            print(f"Error in getting auto time: {status} {info}")
        if preview_status:
            self._previewAction()
        else:
            self.settingsWidget.saveButton.setEnabled(True)
            self.closeLock.emit(True)
        return [0, "OK"]

    def getAutoTime(self) -> tuple[int, float|dict]:
        low = self.autoValue_min  # spectrum low
        high = self.autoValue_max # spectrum high

        low_ms = int(self.autoTime_min * 1000)
        high_ms = int(self.autoTime_max * 1000)
        if self.settings["integrationtimetype"] == 'auto':
            if self.settings["useintegrationtimeguess"]:
                guessIntTime_ms = int(self.settings["integrationTime"] * 1000)
            else:
                guessIntTime_ms = (low_ms + high_ms) // 2

            for iter in range(self.intTimeMaxIterations):
                print(f"iteration {iter+1} of {self.intTimeMaxIterations}")
                guessIntTime_s = guessIntTime_ms / 1000.0
                self.settings["integrationTime"] = guessIntTime_s #needed for keeping self.lastspectrum in order
                [status, info] = self.spectrometerSetIntegrationTime(guessIntTime_s) 
                if status:
                    print(f"tried to set:{guessIntTime_s}. Error in setting integration time inside AutoTime: {status} {info}")
                    return [status, info]
                [status, info] = self.spectrometerStartScan()
                if status:
                    print(f"Error in starting scan inside AutoTime: {status} {info}")
                    return [status, info]
                [status, info] = self._update_spectrum()
                if status:
                    print(f"Error in getting spectrum inside AutoTime: {status} {info}")
                    return [status, info]
                ################ check that info is [wv, spectrum] !!!!!
                if self.settings["saveautoattmepts"]:
                    varDict ={}
                    varDict['integrationtime'] = guessIntTime_s
                    varDict['triggermode'] = 1 if self.settings['externalTrigger'] else 0
                    varDict['name'] = self.settings["samplename"]
                    varDict['comment'] = self.settings["comment"] + " Auto adjust of integration time."
                    self.createFile(varDict = varDict, filedelimeter=self.filedelimeter, address = self.settings["address"] + os.sep + self.settings["filename"] + f"_{guessIntTime*1000}ms.csv", data = info[1])
                max_val = max(info[1])
                print(f"max(info[1]) = {max_val}, guessIntTime = {guessIntTime_ms} ms")
                if low <= max_val <= high:
                    print(f"found integration time: {guessIntTime_ms} ms")
                    return 0, guessIntTime_s
                elif max_val < low:
                    print(f"max_val < low, setting guessIntTime_ms = {guessIntTime_ms + 1} ms")
                    low_ms = guessIntTime_ms + 1
                else:
                    print(f"max_val > high, setting guessIntTime_ms = {guessIntTime_ms - 1} ms")
                    high_ms = guessIntTime_ms - 1

                if low_ms > high_ms:
                    print(f"low_ms > high_ms, ran out of integration time range, returning 0")
                    break

                guessIntTime_ms = (low_ms + high_ms) // 2
        print("end of iterations")
        return 0, guessIntTime_ms / 1000.0


########Functions
###############GUI setting up
               
    def _initGUI(self, plugin_info:"dictionary with settings obtained from plugin_data in pyIVLS_*_plugin"):
        ##settings are not initialized here, only GUI
        ## i.e. no settings checks are here. Practically it means that anything may be used for initialization (var types still should be checked), but functions should not work if settings are not OK
        self.settingsWidget.lineEdit_Integ.setText(plugin_info["integrationtime"])
        if plugin_info["externatrigger"]:
            self.settingsWidget.extTriggerCheck.setChecked(True)
        if plugin_info["usecorrection"]:
            self.settingsWidget.correctionCheck.setChecked(True)
        currentIndex = self.settingsWidget.getIntegrationTime_combo.findText(plugin_info["integrationtimetype"], Qt.MatchFlag.MatchFixedString)
        if currentIndex > -1:
           self.settingsWidget.getIntegrationTime_combo.setCurrentIndex(currentIndex)
        if plugin_info["useintegrationtimeguess"]:
            self.settingsWidget.useIntegrationTimeGuess_check.setChecked(True)
        if plugin_info["saveattempts_check"]:
            self.settingsWidget.saveAttempts_check.setChecked(True)
        self._GUIchange_deviceConnected(False)
        self.settingsWidget.saveButton.setEnabled(False)
        self.settingsWidget.lineEdit_path.setText(plugin_info["address"])
        self.settingsWidget.lineEdit_filename.setText(plugin_info["filename"])
        self.settingsWidget.lineEdit_sampleName.setText(plugin_info["samplename"])
        self.settingsWidget.lineEdit_comment.setText(plugin_info["comment"])

    def _getAddress(self):
        address = self.settingsWidget.lineEdit_path.text()
        if not(os.path.exists(address)):
                address = self.path
        address = QFileDialog.getExistingDirectory(None, "Select directory for saving", address, options = QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks)
        if address:
                self.settingsWidget.lineEdit_path.setText(address)
########Functions
###############GUI react to change

    def _GUIchange_deviceConnected(self, status):
        #NOTE: status is direct, i.e. when spectrometer is connected received status should True, when disconnected status should be False
        if status:
                        self.settingsWidget.connectionIndicator.setStyleSheet("border-radius: 10px; background-color: rgb(38, 162, 105); min-height: 20px; min-width: 20px;")
        else:
                        self.settingsWidget.connectionIndicator.setStyleSheet("border-radius: 10px; background-color: rgb(165, 29, 45); min-height: 20px; min-width: 20px;")
        self.settingsWidget.setIntegrationTimeButton.setEnabled(status)
        self.settingsWidget.previewBox.setEnabled(status)
        if status:
            self._integrationTime_mode_changed()
        self.settingsWidget.disconnectButton.setEnabled(status)
        self.settingsWidget.connectButton.setEnabled(not status)

    def _enableSaveButton(self):
        if not self.lastspectrum:
            self.settingsWidget.saveButton.setEnabled(False)
        else:
            self.settingsWidget.saveButton.setEnabled(True)

    def _correctionChanged(self, int):
        if self.preview_running: #this function is useful only in preview mode
            self.settings["previewCorrection"] = self._parse_spectrumCorrection()
            
    def _integrationTime_mode_changed(self):
        integrationTimeMode = self.settingsWidget.getIntegrationTime_combo.currentText()
        if integrationTimeMode == 'manual':
            self.settingsWidget.autoIntegrationTime_box.setEnabled(False)
            self.settingsWidget.getTime_button.setEnabled(False)
        else:
            self.settingsWidget.autoIntegrationTime_box.setEnabled(True)
            self.settingsWidget.getTime_button.setEnabled(True)
########Functions
########plugins interraction
        
    def _get_public_methods(self):
        """
        Returns a nested dictionary of public methods for the plugin
        """
        # if the plugin type matches the requested type, return the functions

        methods = {
            method: getattr(self, method)
            for method in dir(self)
            if callable(getattr(self, method))
            and not method.startswith("__")
            and not method.startswith("_")
            and method not in self.non_public_methods
            and method in self.public_methods
        }
        return methods

    def _getLogSignal(self):
        return self.log_message
        
    def _getInfoSignal(self):
        return self.info_message

    def _getCloseLockSignal(self):
        return self.closeLock           

    def _parse_settings_integrationTime(self) -> "status":
        """
        Parses the integration time from the GUI line edit and stores it in the settings dictionary.

        stored in self.settings["integrationTime"] as float in seconds

        Returns:
            list: [0, "OK"] on success, or [1, {"Error message": ...}] on error.
        """
        try:
             self.settings["integrationTime"] = int(self.settingsWidget.lineEdit_Integ.text())
        except ValueError:
             return [1, {"Error message":"Value error in TLCCS plugin: integration time field should be integer"}]
        if self.settings["integrationTime"]>const.CCS_SERIES_MAX_INT_TIME*1000:
             return [1, {"Error message":"Value error in TLCCS plugin: integration time should can not be greater than maximum integration time {const.CCS_SERIES_MAX_INT_TIME} s"}]
        if self.settings["integrationTime"]<1:
             return [1, {"Error message":"Value error in TLCCS plugin: integration time should can not be smaller than 1 ms"}]
        self.settings["integrationTime"] = self.settings["integrationTime"]/1000
        return [0, "OK"]

    def _parse_settings_autoTime(self) -> "status":
        self.settings["integrationtimetype"] =  self.settingsWidget.getIntegrationTime_combo.currentText()
        self.settings["saveautoattmepts"] = self.settingsWidget.saveAttempts_check.isChecked()
        self.settings["useintegrationtimeguess"] = self.settingsWidget.useIntegrationTimeGuess_check.isChecked()
        
        if self.settings["saveautoattmepts"]:
            [status, info] = self._parseSaveData()
            if status:
                return [status, info]
        if self.settings["useintegrationtimeguess"]:
            [status, info] = self._parse_settings_integrationTime()
            if status:
                return [status, info]
        
        return [0, "OK"]
    
    def _parse_spectrumCorrection(self):
        if self.settingsWidget.correctionCheck.isChecked():
            return True
        else:    
            return False

    def _parseSaveData(self) -> "status":
        self.settings["address"] = self.settingsWidget.lineEdit_path.text()
        if not os.path.isdir(self.settings["address"] + os.sep):
                self.log_message.emit(datetime.now().strftime("%H:%M:%S.%f") + f" : TLCCS plugin : address string should point to a valid directory")
                return [1, {"Error message":f"TLCCS plugin : address string should point to a valid directory"}]           
        self.settings["filename"] = self.settingsWidget.lineEdit_filename.text()
        if not is_valid_filename(self.settings["filename"]):
                self.log_message.emit(datetime.now().strftime("%H:%M:%S.%f") + f" : TLCCS plugin : filename is not valid")
                self.info_message.emit(f"TLCCS plugin : filename is not valid")
                return [1, {"Error message":f"TLCCS plugin : filename is not valid"}]
               
        self.settings["samplename"] = self.settingsWidget.lineEdit_sampleName.text()
        self.settings["comment"] = self.settingsWidget.lineEdit_comment.text()
        return [0,"Ok"]

    def parse_settings_preview(self) -> "status":
        """Parses the settings widget for the spectrometer. Extracts current values

        Returns:
            0 - no error
            ~0 - error (add error code later on if needed)
        """   
        self.settings = {}
        [status, info] = self._parse_settings_autoTime()
        if status:
             return [status, info]
        if not self.settings["useintegrationtimeguess"]:
            [status, info] = self._parse_settings_integrationTime()
            if status:
                return [status, info]
        if not self.settings["saveautoattmepts"]:
            [status, info] = self._parseSaveData()
            if status:
                return [status, info]    
        if self.settingsWidget.extTriggerCheck.isChecked():
            self.settings["externalTrigger"] = True
        else:    
            self.settings["externalTrigger"] = False
        self.settings["previewCorrection"] = self._parse_spectrumCorrection()
        self.settings["autoTime_min"]= self.autoTime_min
        self.settings["autoTime_max"] = self.autoTime_max
        self.settings["autoValue_min"] = self.autoValue_min
        self.settings["autoValue_max"] = self.autoValue_max
        self.settings["intTimeMaxIterations"] = self.intTimeMaxIterations
        return [0, self.settings]
    

    def parse_settings_widget(self) -> tuple[int, dict]:
        """Parses the settings widget for the spectrometer. Extracts current values

        Returns:
            0 - no error
            ~0 - error (add error code later on if needed)
        """   
        self.settings = {}
        [status, info] = self._parse_settings_autoTime()
        if status:
             return [status, info]
        if not self.settings["useintegrationtimeguess"]:
            [status, info] = self._parse_settings_integrationTime()
            if status:
                return [status, info]
        if not self.settings["saveautoattmepts"]:
            [status, info] = self._parseSaveData()
            if status:
                return [status, info]    
        if self.settingsWidget.extTriggerCheck.isChecked():
            self.settings["externalTrigger"] = True
        else:    
            self.settings["externalTrigger"] = False
        self.settings["previewCorrection"] = self._parse_spectrumCorrection()
        return [0, self.settings]

########Functions
########device functions
    def spectrometerConnect(self):
        #self._parse_settings_integrationTime()
        try:    
            status = self.drv.open(const.CCS175_VID, const.CCS175_PID, self.settings["integrationTime"])
            if not status:
                self.log_message.emit(datetime.now().strftime("%H:%M:%S.%f") + f" : TLCCS plugin : can not connect to spectrometer")
                self.info_message.emit(f"peltierController plugin : can not connect to spectrometer")
                return [4, {"Error message":"Can not connect to spectrometer"}]
            return [0, "OK"]
        except Exception as e:
            return [4, {"Error message":f"{e}"}]

    def spectrometerDisconnect(self):
        try:
            self.drv.close()
            return [0, "OK"]
        except:
                return [4, {"Error message":"Can not disconnect the spectrometer"}]

    def spectrometerSetIntegrationTime(self, integrationTime):
        try:
            self.drv.set_integration_time(integrationTime)
            return[0, 'OK']
        except ThreadStopped: 
            pass
        except Exception as e:
            return [4, {"Error message":f"{e}"}]

    def spectrometerGetIntegrationTime(self):
        #return current integration time in seconds
        try:
            intTime = self.drv.get_integration_time()
            return[0, intTime]
        except ThreadStopped: 
            pass
        except Exception as e:
            return [4, {"Error message":f"{e}"}]

    def spectrometerStartScan(self):
        print("someone called spectrometerStartScan >:(")
        try:
            if self.scanRunning:
                print("scan is already running")
                return [1, {"Error message":"Scan is already running"}]                
            self.drv.start_scan()
            self.scanRunning = True
            print("ok, scan started")
            return[0, 'OK']
        except ThreadStopped: 
            print("thread stopped")
            return[0, 'ThreadStopped']
        except:
            print("can not start scan")
            return [4, {"Error message":"Can not start scan"}]
            
    def spectrometerGetSpectrum(self):
        """Gets the spectrum from the spectrometer. It waits until the scan is finished.

        Returns:
            list[int, np.array|dict]: 
        """
        try:
            while self.scanRunning:     
                if not("SCAN_TRANSFER" in self.drv.get_device_status()):
                    time.sleep(self.settings["integrationTime"])
                else:
                    break 
            if not self.scanRunning:
                print("scan is not running, returning empty data")
                return [1, {"Error message":"Scan stopped"}]
            else:
                print("scan is finished, getting data")
                return[0, self.drv.get_scan_data()]
        except ThreadStopped: 
            pass
        except:
            self.scanRunning = False
            return [4, {"Error message":"Can not get spectrum"}]
        
    def spectrometerGetScan(self):
        """Atomically get a spectrum"""
        with self._scan_lock:
            try:
                statuses = self.drv.get_device_status()
                if "SCAN_TRANSFER" in statuses:
                    # Scan is running, read the data
                    stale = self.drv.get_scan_data()
                # No scan running, start a new scan
                self.drv.start_scan()
                data = self.drv.get_scan_data()
                return [0, data]
            except ThreadStopped:
                return [0, 'ThreadStopped']
            except Exception as e:
                return [4, {"Error message": f"Can not get scan: {e}"}]

########Functions
###############save data

    def createFile(self, varDict, filedelimeter, address, data):
        fileheader = self._spectrometerMakeHeader(varDict, separator = filedelimeter)
        np.savetxt(address, list(zip(self.correction[:,0], data)), fmt='%.9e', delimiter=filedelimeter, newline='\n', header=fileheader, footer='#[EndOfFile]', comments='#')

    def _spectrometerMakeHeader(self, varDict = {}, separator = ';'):
        ###following the structure of files generated by Thorlabs software
        ### a part of values are just const, they may be replaces with real values
        #
        #structure of the varDict
        #
        #varDict['average'] - int:averaging
        #varDict['integrationtime'] - float:integration time in seconds
        #varDict['triggermode'] - external trigger = 1 / internal = 0
        #varDict['name'] - str:sample name
        #varDict['comment'] - str:comment
        comment = "Thorlabs FTS operated by pyIVSL\n"
        comment = f"{comment}#[SpectrumHeader]\n"
        comment = f"{comment}Date{separator}{datetime.now().strftime('%Y%m%d')}\n"
        comment = f"{comment}Time{separator}{datetime.now().strftime('%H%M%S%f')[:-4]}\n"
        comment = f"{comment}GMTTime{separator}{datetime.utcnow().strftime('%H%M%S%f')[:-4]}\n"
        comment = f"{comment}XAxisUnit{separator}nm_air\n"
        comment = f"{comment}YAxisUnit{separator}intensity\n"
        if "average" in varDict:
            comment = f"{comment}Average{separator}{varDict['average']}\n"
        else:
            comment = f"{comment}Average{separator}0\n"
        comment = f"{comment}RollingAverage{separator}0\n"
        comment = f"{comment}SpectrumSmooth{separator}0\n"
        comment = f"{comment}SSmoothParam1{separator}0\n"
        comment = f"{comment}SSmoothParam2{separator}0\n"
        comment = f"{comment}SSmoothParam3{separator}0\n"
        comment = f"{comment}SSmoothParam4{separator}0\n"
        comment = f"{comment}IntegrationTime{separator}{varDict['integrationtime']}\n"
        comment = f"{comment}TriggerMode{separator}{varDict['triggermode']}\n"
        comment = f"{comment}InterferometerSerial{separator}M00903839\n"
        comment = f"{comment}Source\n"
        comment = f"{comment}AirMeasureOpt{separator}0\n"
        comment = f"{comment}WnrMin{separator}0\n"
        comment = f"{comment}WnrMax{separator}0\n"
        comment = f"{comment}Length{separator}3648\n"
        comment = f"{comment}Resolution{separator}0\n"
        comment = f"{comment}ADC{separator}0\n"
        comment = f"{comment}Instrument{separator}0\n"
        comment = f"{comment}Model{separator}CCS175\n"
        comment = f"{comment}Type{separator}emission\n"
        comment = f"{comment}AirTemp{separator}0\n"
        comment = f"{comment}AirPressure{separator}0\n"
        comment = f"{comment}AirRelHum{separator}0\n"
        if "name" in varDict:
            comment = f"{comment}Name{separator}{varDict['name']}\n"
        else:
            comment = f"{comment}Name{separator}\n"
        if "comment" in varDict:
            comment = f"{comment}Comment{separator}\"{varDict['comment']}\"\n"
        else:
            comment = f"{comment}Comment{separator} \"\"\n"
        comment = f"{comment}#[Data]\n"
        return comment