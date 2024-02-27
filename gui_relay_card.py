from PyQt5.QtWidgets import QApplication, QLayout, QComboBox, QGridLayout, QHBoxLayout, QVBoxLayout, QWidget,QMainWindow, QPushButton
from PyQt5.QtCore import Qt, QSize, QObject, pyqtSignal, QThread
import serial
import serial.tools.list_ports
from queue import Queue, Empty
from conrad import ConradRelayCard

__author__="Robert Detlof"

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
                print("GuiUpdateWorker: No updates")

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
                
                print("RelaySwitcherWorker: Requested state", state_flags)
                new_state_flags = self.relay_card.hacky_set_relays(card_id=0, relay_flags_bool=state_flags)
                
                self.queue_gui_update.put(new_state_flags)

                print("additional_wait_time", additional_wait_time)
                QThread.msleep(additional_wait_time)


            except Empty:
                print("RelaySwitcherWorker: No updates")

            except Exception as e:
                print(e)

        self.finished.emit()


class RelayWindow(QWidget):

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self.relay_buttons = []
        self.meta_buttons = []
        self.setup_relay_layout()

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

        
    def hacky_button_action(self):
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
        print("Limbo called")
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


    def action_enable_all(self):
        self.queue_update_relay.put( ([True, True, True, True, True, True, True, True], 0))

    def action_disable_all(self):
        self.queue_update_relay.put(([False, False, False, False, False, False, False, False], 0))

    def action_check(self):
        pass

    def action_activate_first_five(self):
        self.queue_update_relay.put(([True, True, True, True, True, False, False, False], 0))

    def list_ports(self):
        ports = serial.tools.list_ports.comports()
        port_names = []

        for port, desc, hwid in sorted(ports):
                port_names.append(port)
                print("{}: {} [{}]".format(port, desc, hwid))

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

    def connect_relay_card(self):
        self.selected_com_port = self.combobox_ports.currentText()
        
        if self.selected_com_port == None or self.selected_com_port == "":
            pass

        try:
            print("self.selected_com_port)", self.selected_com_port)
            self.relay_card.connect(self.selected_com_port)
            pre_state = self.relay_card.check_relay_state()
            self.queue_update_gui.put(pre_state)
            self._enable_relay_buttons()

            # thread start
            self.gui_update_thread.start()
            self.relay_update_thread.start()

            self.connect_button.setEnabled(False)

        except Exception as e:
            print(e)


    def action_pulse(self):
        #relay_index = event_cause.relay_index
        #state = self.current_state.copy()
        state_a = self.current_state.copy()
        state_b = state_a.copy()

        state_a[5] = True
        state_a[6] = True
        state_a[7] = True
        self.queue_update_relay.put( (state_a, 500) )

        state_b[5] = False
        state_b[6] = False
        state_b[7] = False
        self.queue_update_relay.put( (state_b, 0) )


    def setup_relay_layout(self):
        vbox_layout = QVBoxLayout()
        self.setLayout(vbox_layout)

        # connection area
        widget_com_selection = QWidget(self)
        layout_com_selection = QHBoxLayout()
        widget_com_selection.setLayout(layout_com_selection)
        self.combobox_ports = QComboBox()
        
        for port_name in self.list_ports():
            self.combobox_ports.addItem(port_name)

        #self.combobox_ports.currentTextChanged.connect(self.on_combobox_changed)
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self.connect_relay_card)
        layout_com_selection.addWidget(self.combobox_ports)
        layout_com_selection.addWidget(self.connect_button)

        vbox_layout.addWidget(widget_com_selection)

        # meta buttons area
        widget_meta_actions = QWidget(self)
        
        layout_meta_actions = QHBoxLayout()
        layout_meta_actions.setContentsMargins(7, 0, 7, 0)

        widget_meta_actions.setLayout(layout_meta_actions)
        
        # button all on
        button_all_on = QPushButton("All On")
        button_all_on.clicked.connect(self.action_enable_all)
        layout_meta_actions.addWidget(button_all_on)
        self.meta_buttons.append(button_all_on)
        
        # button all off
        button_all_off = QPushButton("All Off")
        button_all_off.clicked.connect(self.action_disable_all)
        layout_meta_actions.addWidget(button_all_off)
        self.meta_buttons.append(button_all_off)

        # button 1-5 on
        button_five_on = QPushButton("1-5 On")
        button_five_on.clicked.connect(self.action_activate_first_five)
        layout_meta_actions.addWidget(button_five_on)
        self.meta_buttons.append(button_five_on)

        # button check
        """
        button_check = QPushButton("Check")
        button_check.clicked.connect(self.action_check)
        layout_meta_actions.addWidget(button_check)
        self.meta_buttons.append(button_check)
        """

        # button pulse 6-8
        button_pulse = QPushButton("Pulse 6,7,8")
        button_pulse.clicked.connect(self.action_pulse)
        layout_meta_actions.addWidget(button_pulse)
        self.meta_buttons.append(button_pulse)

        vbox_layout.addWidget(widget_meta_actions)

        # relay buttons
        widget_relay_buttons = QWidget()
        grid = QGridLayout()
        grid.setContentsMargins(7, 0, 7, 7)
        widget_relay_buttons.setLayout(grid)

        self.relay_buttons = []
        i = 1
        for y in range(0,2):
            for x in range(0,4):
                b = QPushButton(f"{i}")
                b.relay_state = False
                b.relay_index = i - 1
                b.default_stylesheet = b.styleSheet()
                b.setFixedSize(100, 100)
                i += 1
                grid.addWidget(b, y, x)
                self.relay_buttons.append(b)
                b.clicked.connect( self.hacky_button_action )

        vbox_layout.addWidget(widget_relay_buttons)
        self._disable_relay_buttons()
        self.setWindowTitle("Relay Card Control")
        self.setGeometry(100, 100, 280, 80)
        vbox_layout.setSizeConstraint(QLayout.SetFixedSize)
        

class MyMainWindow(QMainWindow):
    def __init__(self, parent=None):
        super(MyMainWindow, self).__init__(parent)
        self.form_widget = RelayWindow() 
        self.setCentralWidget(self.form_widget)
        self.setWindowTitle("Main Window")

app = QApplication([])
main_window = MyMainWindow()
main_window.setWindowTitle("RDE Relay Tool v0.1")
main_window.show()
app.exec()