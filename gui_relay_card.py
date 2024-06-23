from queue import Queue, Empty
import serial
import serial.tools.list_ports
from PyQt5.QtWidgets import QMessageBox, QApplication, QLayout, QComboBox, QGridLayout, QHBoxLayout, QVBoxLayout, QWidget,QMainWindow, QPushButton
from PyQt5.QtCore import QObject, pyqtSignal, QThread, QTimer
from relay_config import load_config
from protocol_conrad import ConradRelayCard
import logging
import math

log = logging.getLogger("GUI Relay Card")
logging.basicConfig(level=logging.DEBUG)

__author__ = "Robert Detlof"
__title__  = "RDE Relay Tool v0.3"
__max_special_buttons__ = 16
__max_label_length__ = 14

class GuiUpdateWorker(QObject):
    state_change = pyqtSignal(list)
    finished = pyqtSignal()

    def __init__(self: QObject, queue_relay_state:Queue=None) -> None:
        super().__init__()
        self.interrupt_requested = False
        self.queue_relay_state = queue_relay_state

    def _interrupt_worker(self):
        self.interrupt_requested = True

    def run(self):
        while not self.interrupt_requested:
            try:
                state_flags = self.queue_relay_state.get(timeout=1.0)
                self.state_change.emit(state_flags)
            except Empty:
                log.debug("GuiUpdateWorker: No updates")

        self.finished.emit()


class RelaySwitcherWorker(QObject):
    finished = pyqtSignal()
    work_ongoing = pyqtSignal()
    work_done = pyqtSignal()

    def __init__(self: QObject, relay_card, queue_relay_state:Queue, queue_gui_update:Queue) -> None:
        super().__init__()
        self.interrupt_requested = False
        self.queue_relay_state = queue_relay_state
        self.queue_gui_update = queue_gui_update
        self.relay_card = relay_card


    def _interrupt_worker(self):
        self.interrupt_requested = True

    def run(self):
        while not self.interrupt_requested:
            try:
                state_flags, additional_wait_time = self.queue_relay_state.get(timeout=1.0)
                
                log.debug(f"RelaySwitcherWorker: Requested state {state_flags}")
                new_state_flags = self.relay_card.hacky_set_relays(card_id=0, relay_flags_bool=state_flags)
                
                self.queue_gui_update.put(new_state_flags)

                log.debug(f"additional_wait_time: {additional_wait_time}", )
                QThread.msleep(additional_wait_time)


            except Empty:
                log.debug("RelaySwitcherWorker: No updates")

            except Exception as e:
                log.error(str(e))

        self.finished.emit()


class RelayWindow(QWidget):

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        config = self._load_relay_config()

        self.relay_buttons = []
        self.meta_buttons = []
        self.setup_relay_layout(config)

        self.selected_com_port = None
        self.relay_card = ConradRelayCard()

        # gui updater
        self.queue_update_gui = Queue()
        self.gui_update_worker = GuiUpdateWorker(self.queue_update_gui)
        self.gui_update_thread = QThread()
        self.gui_update_worker.moveToThread(self.gui_update_thread)
        self.gui_update_thread.started.connect(self.gui_update_worker.run)
        self.gui_update_worker.finished.connect(self.gui_update_thread.quit)
        self.gui_update_worker.finished.connect(self.gui_update_worker.deleteLater)
        self.gui_update_thread.finished.connect(self.gui_update_thread.deleteLater)
        self.gui_update_worker.state_change.connect(self._update_relay_button_representation)
        
        # relay networker
        self.queue_update_relay = Queue()
        self.relay_update_worker = RelaySwitcherWorker(relay_card=self.relay_card, queue_relay_state=self.queue_update_relay, queue_gui_update=self.queue_update_gui)
        self.relay_update_thread = QThread()
        self.relay_update_worker.moveToThread(self.relay_update_thread)
        self.relay_update_thread.started.connect(self.relay_update_worker.run)
        self.relay_update_worker.finished.connect(self.relay_update_thread.quit)
        self.relay_update_worker.finished.connect(self.relay_update_worker.deleteLater)
        self.relay_update_thread.finished.connect(self.relay_update_thread.deleteLater)

        # initial state
        self.current_state = [False, False, False, False, False, False, False, False]


    def _load_relay_config(self):
        try:
            return load_config(allow_write=True)
        
        except Exception as e:
            _make_error_window(e, kill_process=True, headline="Error Parsing Relay Config", popup_title="Relay Config Error")

    def _factorize_special_buttons(self, config, parent_widget, logical_container=[]):
        config_buttons = config.get("buttons")[:__max_special_buttons__]

        x = 0
        y = 0
        for b in config_buttons:
            log.debug(str(b))
            button_temp = QPushButton(b.get("label")[:__max_label_length__])
            button_temp.custom_action = b.get("action")
            button_temp.custom_targets = b.get("targets")
            button_temp.custom_duration = b.get("duration")
            button_temp.clicked.connect(self.special_action)
            parent_widget.addWidget(button_temp, y, x % 4)
            logical_container.append(button_temp)

            x = x + 1
            y = math.floor(x / 4)


    def special_action(self):
        event_cause = self.sender() # event cause
        custom_action = event_cause.custom_action

        if custom_action == "activate":
            self.action_activate_selective(event_cause.custom_targets)
        elif custom_action == "deactivate":
            self.action_disable_selective(event_cause.custom_targets)
        elif custom_action == "pulse":
            duration = 500
            if event_cause.custom_duration:
                duration = event_cause.custom_duration

            self.action_pulse_selective(event_cause.custom_targets, duration=duration)
        else:
            _make_error_window(Exception("Unknown special button action. Cannot perform"), kill_process=False)
        
    def boring_old_button_action(self):
        event_cause = self.sender() # event cause
        card_id = 0
        relay_index = event_cause.relay_index
        #state = self.current_state.copy()
        state = self.current_state

        self._display_button_limbo(event_cause)

        # toggle
        state[relay_index] = not state[relay_index]
        self.queue_update_relay.put( (state, 0) )


    def _update_relay_button_representation(self, flags: list[bool]):
        if len(self.relay_buttons) != len(flags):
            raise Exception("Mismatch number of relay buttons and state flags")
        
        for i, btn in enumerate(self.relay_buttons):
            if flags[i] == True:
                self._display_button_enabled(btn)
            else:
                self._display_button_disabled(btn)

        self.current_state = flags


    def _display_button_enabled(self, btn):
        btn.setStyleSheet("""
                QPushButton {
                    background-color: #cc0000; 
                    border-color: #990000;
                }
                QPushButton:hover {
                    border-color: black;
                }
                """)
        
    def _display_button_limbo(self, btn):
        btn.setStyleSheet("""
                QPushButton {
                    background-color: orange; 
                    border-color: #990000;
                }
                QPushButton:hover {
                    border-color: black;
                }
                """)
        
    def _display_button_disabled(self, btn):
        btn.setStyleSheet(btn.default_stylesheet)


    def action_activate_selective(self, targets=[]):
        state = self.current_state.copy()
        targets = list(dict.fromkeys(targets))
        
        for t in targets:
            if (t - 1) < len(state):
                state[t - 1] = True

        self.queue_update_relay.put((state, 0))


    def action_disable_selective(self, targets=[]):
        state = self.current_state.copy()
        targets = list(dict.fromkeys(targets))
        
        for t in targets:
            if (t - 1) < len(state):
                state[t - 1] = False

        self.queue_update_relay.put((state, 0))

    def action_pulse_selective(self, targets=[], duration=500):
        state_a = self.current_state.copy()
        state_b = state_a.copy()

        for t in targets:
            if (t - 1) < len(state_a):
                state_a[t - 1] = True
                state_b[t - 1] = False

        self.queue_update_relay.put( (state_a, duration) )
        self.queue_update_relay.put( (state_b, 0) )

        self._disable_relay_buttons()
        self.timer = QTimer()
        self.timer.timeout.connect(self._enable_relay_buttons)
        self.timer.start(duration + 200)


    def list_ports(self):
        ports = serial.tools.list_ports.comports()
        port_names = []

        for port, desc, hwid in sorted(ports):
                port_names.append(
                    {'port': port, 
                     'hwid': hwid,
                     'desc': desc 
                     })
                log.info("{}: {} [{}]".format(port, desc, hwid))
                log.debug(f"port: {port}", )
                log.debug(f"desc: {desc}", )
                log.debug(f"hwid: {hwid}")
                log.debug("-" * 64)

        return port_names

    def _set_buttons_enabled(self, state=True):
        for b in self.meta_buttons:
            b.setEnabled(state)

        for b in self.relay_buttons:
            b.setEnabled(state)

    def _enable_relay_buttons(self):
        self._set_buttons_enabled(state=True)

    def _disable_relay_buttons(self):
        self._set_buttons_enabled(state=False)

    def _connect_relay_card(self):
        #self.selected_com_port = self.combobox_ports.currentText()
        self.selected_com_port = self.combobox_ports.itemData(self.combobox_ports.currentIndex())

        if self.selected_com_port == None or self.selected_com_port == "":
            pass

        try:
            self.relay_card.connect(self.selected_com_port)
            pre_state = self.relay_card.check_relay_state()
            self.queue_update_gui.put(pre_state)
            self._enable_relay_buttons()

            # thread start
            self.gui_update_thread.start()
            self.relay_update_thread.start()

            self.connect_button.setEnabled(False)

        except ConnectionError as ce:
            log.error(str(ce))
            _make_error_window(ConnectionError("Could not connect to Relay Card. Is the card powered?"), kill_process=False, headline="Error", popup_title="Connection Error")
            self.relay_card.shutdown()
        
        except Exception as e:
            log.error(str(e))
            _make_error_window(e, kill_process=False, headline="Error", popup_title="Connection Error")
            self.relay_card.shutdown()



    def setup_relay_layout(self, config):
        vbox_layout = QVBoxLayout()
        self.setLayout(vbox_layout)

        # connection area
        widget_com_selection = QWidget(self)
        layout_com_selection = QHBoxLayout()
        widget_com_selection.setLayout(layout_com_selection)
        self.combobox_ports = QComboBox()
        
        for port in self.list_ports():
            adendum = ""
            if port.get("desc").startswith("Silicon Labs CP210x USB"):
                adendum = "- Conrad"

            self.combobox_ports.addItem(f"{port.get('port')} {adendum}", userData=port.get("port"))

        # CONNECT BUTTON
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self._connect_relay_card)
        layout_com_selection.addWidget(self.combobox_ports)
        layout_com_selection.addWidget(self.connect_button)
        vbox_layout.addWidget(widget_com_selection)
        
        # META BUTTONS
        widget_meta_actions = QWidget(self)
        #layout_meta_actions = QHBoxLayout()
        layout_meta_actions = QGridLayout()
        layout_meta_actions.setContentsMargins(7, 0, 7, 0)
        widget_meta_actions.setLayout(layout_meta_actions)
        self._factorize_special_buttons(config=config, parent_widget=layout_meta_actions, logical_container=self.meta_buttons)
        vbox_layout.addWidget(widget_meta_actions)

        # RELAY BUTTONS
        widget_relay_buttons = QWidget()
        grid = QGridLayout()
        grid.setContentsMargins(7, 0, 7, 7)
        widget_relay_buttons.setLayout(grid)

        custom_labels = config.get("labels")
        self.relay_buttons = []
        i = 0
        for y in range(0,2):
            for x in range(0,4):

                custom_label = ""
                if i < len(custom_labels):
                    custom_label = f"\n{custom_labels[i]}"
                
                b = QPushButton(f"{i + 1}{custom_label[:__max_label_length__]}")
                b.relay_state = False
                b.relay_index = i
                b.default_stylesheet = b.styleSheet()
                b.setFixedSize(100, 100)
                grid.addWidget(b, y, x)
                self.relay_buttons.append(b)
                b.clicked.connect( self.boring_old_button_action )
                i += 1

        vbox_layout.addWidget(widget_relay_buttons)
        self._disable_relay_buttons()
        self.setGeometry(100, 100, 280, 80)
        vbox_layout.setSizeConstraint(QLayout.SetFixedSize)
        

class RelayMainWindow(QMainWindow):
    def __init__(self, parent=None):
        super(RelayMainWindow, self).__init__(parent)
        self.form_widget = RelayWindow() 
        self.setCentralWidget(self.form_widget)

def _make_error_window(e, kill_process=False, headline="Error", popup_title="Error"):
    msg = QMessageBox()
    msg.setIcon(QMessageBox.Critical)
    #msg.setText(f"{headline}:\n{type(e).__name__}")
    msg.setText(f"{type(e).__name__}")
    msg.setInformativeText(str(e))
    msg.setWindowTitle(popup_title)
    msg.exec_()

    if kill_process:
        import sys
        sys.exit(1)


def main():
    try:
        app = QApplication([])
        main_window = RelayMainWindow()
        main_window.setWindowTitle(__title__)
        main_window.show()
        main_window.setFixedSize(main_window.width(), main_window.height())
        app.exec()
    
    except Exception as e:
        log.error(str(e))
        _make_error_window(e, kill_process=True, headline="Critical Application Error", popup_title="Critical Error")

main()