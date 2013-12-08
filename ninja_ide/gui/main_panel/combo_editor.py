# -*- coding: utf-8 -*-
#
# This file is part of NINJA-IDE (http://ninja-ide.org).
#
# NINJA-IDE is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# any later version.
#
# NINJA-IDE is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with NINJA-IDE; If not, see <http://www.gnu.org/licenses/>.
from __future__ import absolute_import
from __future__ import unicode_literals

import bisect

from PyQt4.QtGui import QApplication
from PyQt4.QtGui import QMessageBox
#from PyQt4.QtGui import QStandardItemModel
#from PyQt4.QtGui import QAbstractItemView
from PyQt4.QtGui import QClipboard
from PyQt4.QtGui import QWidget
from PyQt4.QtGui import QCursor
from PyQt4.QtGui import QMenu
from PyQt4.QtGui import QIcon
from PyQt4.QtGui import QFrame
from PyQt4.QtGui import QVBoxLayout
from PyQt4.QtGui import QHBoxLayout
from PyQt4.QtGui import QStackedLayout
from PyQt4.QtGui import QStyle
from PyQt4.QtGui import QLabel
from PyQt4.QtGui import QComboBox
from PyQt4.QtGui import QSizePolicy
from PyQt4.QtGui import QPushButton
from PyQt4.QtCore import SIGNAL
from PyQt4.QtCore import Qt

from ninja_ide import translations
from ninja_ide.core import settings
from ninja_ide.gui.ide import IDE


try:
    # For Python2
    str = unicode  # lint:ok
except NameError:
    # We are in Python3
    pass


class ComboEditor(QWidget):
    """
    SIGNALS:
    @recentTabsModified()
    @focusGained(PyQt_PyObject)
    """

    def __init__(self, original=False):
        super(ComboEditor, self).__init__()
        self.__original = original
        self._symbols_index = []
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        self.bar = ActionBar()
        vbox.addWidget(self.bar)

        self.stacked = QStackedLayout()
        vbox.addLayout(self.stacked)

        self._main_container = IDE.get_service('main_container')

        self.connect(self.bar, SIGNAL("changeCurrent(PyQt_PyObject)"),
            self.set_current)
        self.connect(self.bar, SIGNAL("runFile(QString)"),
            self._run_file)
        self.connect(self.bar, SIGNAL("addToProject(QString)"),
            self._add_to_project)
        self.connect(self.bar, SIGNAL("goToSymbol(int)"),
            self._go_to_symbol)
        self.connect(self.bar, SIGNAL("reopenTab(QString)"),
            lambda path: self._main_container.open_file(path))
        self.connect(self.bar, SIGNAL("recentTabsModified()"),
            lambda: self._main_container.recent_files_changed())
        self.connect(self.bar.code_navigator.btnPrevious, SIGNAL("clicked()"),
            lambda: self._navigate_code(False))
        self.connect(self.bar.code_navigator.btnNext, SIGNAL("clicked()"),
            lambda: self._navigate_code(True))

    def _navigate_code(self, val):
        op = self.bar.code_navigator.operation
        self._main_container.navigate_code_history(val, op)

    def currentWidget(self):
        return self.stacked.currentWidget()

    def add_editor(self, neditable):
        """Add Editor Widget to the UI area."""
        if neditable.editor:
            self.stacked.addWidget(neditable.editor)
            self.bar.add_item(neditable.display_name, neditable)

            # Editor Signals
            self.connect(neditable.editor, SIGNAL("cursorPositionChanged()"),
                self._update_cursor_position)
            self.connect(neditable.editor, SIGNAL("currentLineChanged(int)"),
                self._set_current_symbol)
            self.connect(neditable, SIGNAL("checkersUpdated(PyQt_PyObject)"),
                self._show_notification_icon)
            self.connect(neditable, SIGNAL("fileSaved(PyQt_PyObject)"),
                self._update_symbols)
            self.connect(neditable, SIGNAL("focusGained()"),
                self._editor_focus)

            # Connect file system signals only in the original
            self.connect(neditable, SIGNAL("fileClosing(PyQt_PyObject)"),
                self._close_file)
            if self.__original:
                self.connect(neditable,
                    SIGNAL("neverSavedFileClosing(PyQt_PyObject)"),
                    self._ask_for_save)

            # Load Symbols
            self._load_symbols(neditable)

    def show_combo_file(self):
        self.bar.combo.showPopup()

    def close_current_file(self):
        self.bar.about_to_close_file()

    def _close_file(self, neditable):
        index = self.bar.close_file(neditable)
        layoutItem = self.stacked.takeAt(index)
        neditable.editor.completer.cc.unload_module()
        self._add_to_last_opened(neditable.file_path)
        layoutItem.widget().deleteLater()

    def _add_to_last_opened(self, path):
        if path not in settings.LAST_OPENED_FILES:
            settings.LAST_OPENED_FILES.append(path)
            if len(settings.LAST_OPENED_FILES) > settings.MAX_REMEMBER_TABS:
                self.__lastOpened = self.__lastOpened[1:]
            self.emit(SIGNAL("recentTabsModified()"))

    def _ask_for_save(self, neditable):
        val = QMessageBox.No
        fileName = neditable.file_path
        val = QMessageBox.question(
            self, (self.tr('The file %s was not saved') %
                fileName),
                self.tr("Do you want to save before closing?"),
                QMessageBox.Yes | QMessageBox.No |
                QMessageBox.Cancel)
        if val == QMessageBox.No:
            neditable.nfile.close(force_close=True)
        elif val == QMessageBox.Yes:
            self._main_container.save_file(neditable.editor)
            neditable.nfile.close()

    def _run_file(self, path):
        self._main_container.run_file(path)

    def _add_to_project(self, path):
        self._main_container._add_to_project(path)

    def set_current(self, neditable):
        if neditable:
            self.stacked.setCurrentWidget(neditable.editor)
            self._update_cursor_position(ignore_sender=True)
            neditable.editor.setFocus()
            self._main_container.current_editor_changed(
                neditable.file_path)

    def widget(self, index):
        return self.stacked.widget(index)

    def count(self):
        """Return the number of editors opened."""
        return self.stacked.count()

    def _update_cursor_position(self, ignore_sender=False):
        obj = self.sender()
        editor = self.stacked.currentWidget()
        # Check if it's current to avoid signals from other splits.
        if ignore_sender or editor == obj:
            line = editor.textCursor().blockNumber() + 1
            col = editor.textCursor().columnNumber()
            self.bar.update_line_col(line, col)

    def _set_current_symbol(self, line, ignore_sender=False):
        obj = self.sender()
        editor = self.stacked.currentWidget()
        # Check if it's current to avoid signals from other splits.
        if ignore_sender or editor == obj:
            index = bisect.bisect(self._symbols_index, line)
            if (index >= len(self._symbols_index) or
                self._symbols_index[index] > (line + 1)):
                index -= 1
            self.bar.set_current_symbol(index)

    def _go_to_symbol(self, index):
        line = self._symbols_index[index]
        editor = self.stacked.currentWidget()
        editor.go_to_line(line)

    def _update_symbols(self, neditable):
        editor = self.stacked.currentWidget()
        # Check if it's current to avoid signals from other splits.
        if editor == neditable.editor:
            self._load_symbols(neditable)

    def _load_symbols(self, neditable):
        symbols_handler = settings.get_symbols_handler('py')
        source = neditable.editor.toPlainText()
        source = source.encode(neditable.editor.encoding)
        symbols, symbols_simplified = symbols_handler.obtain_symbols(
            source, simple=True)
        self._symbols_index = sorted(symbols_simplified.keys())
        symbols_simplified = sorted(
            list(symbols_simplified.items()), key=lambda x: x[0])
        self.bar.add_symbols(symbols_simplified)
        line = neditable.editor.textCursor().blockNumber()
        self._set_current_symbol(line, True)
        tree_symbols = IDE.get_service('symbols_explorer')
        tree_symbols.update_symbols_tree(symbols, neditable.file_path)

    def _show_notification_icon(self, neditable):
        checkers = neditable.sorted_checkers
        icon = QIcon()
        for items in checkers:
            checker, color, _ = items
            if checker.checks:
                if isinstance(checker.checker_icon, int):
                    icon = self.style().standardIcon(checker.checker_icon)
                elif isinstance(checker.checker_icon, str):
                    icon = QIcon(checker.checker_icon)
                break
        self.bar.update_item_icon(neditable, icon)

    def _editor_focus(self):
        self.emit(SIGNAL("focusGained(PyQt_PyObject)"), self)


class ActionBar(QFrame):
    """
    SIGNALS:
    @changeCurrent(PyQt_PyObject)
    @runFile(QString)
    @reopenTab(QString)
    @recentTabsModified()
    """

    def __init__(self):
        super(ActionBar, self).__init__()
        self.setObjectName("actionbar")
        hbox = QHBoxLayout(self)
        hbox.setContentsMargins(1, 1, 1, 1)
        hbox.setSpacing(1)

        self.lbl_checks = QLabel('')
        self.lbl_checks.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.lbl_checks.setFixedWidth(48)
        self.lbl_checks.setVisible(False)
        hbox.addWidget(self.lbl_checks)

        self.combo = QComboBox()
        #model = QStandardItemModel()
        #self.combo.setModel(model)
        #self.combo.view().setDragDropMode(QAbstractItemView.InternalMove)
        self.combo.setMaximumWidth(300)
        self.combo.setObjectName("combotab")
        self.connect(self.combo, SIGNAL("currentIndexChanged(int)"),
            self.current_changed)
        self.combo.setToolTip(translations.TR_COMBO_FILE_TOOLTIP)
        self.combo.setContextMenuPolicy(Qt.CustomContextMenu)
        self.connect(self.combo, SIGNAL(
            "customContextMenuRequested(const QPoint &)"),
            self._context_menu_requested)
        hbox.addWidget(self.combo)

        self.symbols_combo = QComboBox()
        self.symbols_combo.setObjectName("combo_symbols")
        self.connect(self.symbols_combo, SIGNAL("activated(int)"),
            self.current_symbol_changed)
        hbox.addWidget(self.symbols_combo)

        self.code_navigator = CodeNavigator()
        hbox.addWidget(self.code_navigator)

        self._pos_text = "Line: %d, Col: %d"
        self.lbl_position = QLabel(self._pos_text % (0, 0))
        self.lbl_position.setObjectName("position")
        self.lbl_position.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        hbox.addWidget(self.lbl_position)

        self.btn_close = QPushButton(
            self.style().standardIcon(QStyle.SP_DialogCloseButton), '')
        self.btn_close.setObjectName('navigation_button')
        self.btn_close.setToolTip(translations.TR_CLOSE_SPLIT)
        self.btn_close.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.connect(self.btn_close, SIGNAL("clicked()"),
            self.about_to_close_file)
        hbox.addWidget(self.btn_close)

    def add_item(self, text, neditable):
        """Add a new item to the combo and add the neditable data."""
        self.combo.addItem(text, neditable)
        self.combo.setCurrentIndex(self.combo.count() - 1)

    def add_symbols(self, symbols):
        """Add the symbols to the symbols's combo."""
        self.symbols_combo.clear()
        for symbol in symbols:
            data = symbol[1]
            if data[1] == 'f':
                icon = QIcon(":img/function")
            else:
                icon = QIcon(":img/class")
            self.symbols_combo.addItem(icon, data[0])

    def set_current_symbol(self, index):
        self.symbols_combo.setCurrentIndex(index)

    def update_item_icon(self, neditable, icon):
        index = self.combo.findData(neditable)
        self.combo.setItemIcon(index, icon)

    def current_changed(self, index):
        """Change the current item in the combo."""
        neditable = self.combo.itemData(index)
        self.emit(SIGNAL("changeCurrent(PyQt_PyObject)"), neditable)

    def current_symbol_changed(self, index):
        """Change the current symbol in the combo."""
        self.emit(SIGNAL("goToSymbol(int)"), index)

    def update_line_col(self, line, col):
        """Update the line and column position."""
        self.lbl_position.setText(self._pos_text % (line, col))

    def _context_menu_requested(self, point):
        """Display context menu for the combo file."""
        if self.combo.count() == 0:
            # If there is not an Editor opened, don't show the menu
            return
        menu = QMenu()
        actionAdd = menu.addAction(translations.TR_ADD_TO_PROJECT)
        actionRun = menu.addAction(translations.TR_RUN_FILE)
        menuSyntax = menu.addMenu(translations.TR_CHANGE_SYNTAX)
        self._create_menu_syntax(menuSyntax)
        menu.addSeparator()
        actionClose = menu.addAction(translations.TR_CLOSE_FILE)
        actionCloseAll = menu.addAction(translations.TR_CLOSE_ALL_FILES)
        actionCloseAllNotThis = menu.addAction(
            translations.TR_CLOSE_OTHER_FILES)
        menu.addSeparator()
        actionSplitH = menu.addAction(translations.TR_SPLIT_VERTICALLY)
        actionSplitV = menu.addAction(translations.TR_SPLIT_HORIZONTALLY)
        menu.addSeparator()
        actionCopyPath = menu.addAction(
            translations.TR_COPY_FILE_PATH_TO_CLIPBOARD)
        actionReopen = menu.addAction(translations.TR_REOPEN_FILE)
        if len(settings.LAST_OPENED_FILES) == 0:
            actionReopen.setEnabled(False)
        #Connect actions
        self.connect(actionSplitH, SIGNAL("triggered()"),
            lambda: self._split_this_tab(True))
        self.connect(actionSplitV, SIGNAL("triggered()"),
            lambda: self._split_this_tab(False))
        self.connect(actionRun, SIGNAL("triggered()"),
            self._run_this_file)
        self.connect(actionAdd, SIGNAL("triggered()"),
            self._add_to_project)
        self.connect(actionClose, SIGNAL("triggered()"),
            self.about_to_close_file)
        self.connect(actionCloseAllNotThis, SIGNAL("triggered()"),
            self._close_all_files_except_this)
        self.connect(actionCloseAll, SIGNAL("triggered()"),
            self._close_all_files)
        self.connect(actionCopyPath, SIGNAL("triggered()"),
            self._copy_file_location)
        self.connect(actionReopen, SIGNAL("triggered()"),
            self._reopen_last_tab)

        menu.exec_(QCursor.pos())

    def _create_menu_syntax(self, menuSyntax):
        """Create Menu with the list of syntax supported."""
        syntax = list(settings.SYNTAX.keys())
        syntax.sort()
        for syn in syntax:
            menuSyntax.addAction(syn)
            self.connect(menuSyntax, SIGNAL("triggered(QAction*)"),
                self._reapply_syntax)

    def _reapply_syntax(self, syntaxAction):
        #TODO
        if [self.currentIndex(), syntaxAction] != self._resyntax:
            self._resyntax = [self.currentIndex(), syntaxAction]
            self.emit(SIGNAL("syntaxChanged(QWidget, QString)"),
                self.currentWidget(), syntaxAction.text())

    def about_to_close_file(self, index=None):
        """Close the NFile object."""
        if index is None:
            index = self.combo.currentIndex()
        neditable = self.combo.itemData(index)
        if neditable:
            neditable.nfile.close()

    def close_file(self, neditable):
        """Receive the confirmation to close the file."""
        index = self.combo.findData(neditable)
        self.combo.removeItem(index)
        return index

    def _run_this_file(self):
        """Execute the current file."""
        neditable = self.combo.itemData(self.combo.currentIndex())
        self.emit(SIGNAL("runFile(QString)"), neditable.file_path)

    def _add_to_project(self):
        """Emit a signal to let someone handle the inclusion of the file
        inside a project."""
        neditable = self.combo.itemData(self.combo.currentIndex())
        self.emit(SIGNAL("addToProject(QString)"), neditable.file_path)

    def _reopen_last_tab(self):
        self.emit(SIGNAL("reopenTab(QString)"),
            settings.LAST_OPENED_FILES.pop())
        self.emit(SIGNAL("recentTabsModified()"))

    def _split_this_tab(self, orientation):
        #TODO
        self.emit(SIGNAL("splitTab(QTabWidget, int, bool)"),
            self, self.currentIndex(), orientation)

    def _copy_file_location(self):
        """Copy the path of the current opened file to the clipboard."""
        neditable = self.combo.itemData(self.combo.currentIndex())
        QApplication.clipboard().setText(neditable.file_path,
            QClipboard.Clipboard)

    def _close_all_files(self):
        """Close all the files opened."""
        for i in range(self.combo.count()):
            self.about_to_close_file(0)

    def _close_all_files_except_this(self):
        """Close all the files except the current one."""
        neditable = self.combo.itemData(self.combo.currentIndex())
        for i in reversed(list(range(self.combo.count()))):
            ne = self.combo.itemData(i)
            if ne is not neditable:
                self.about_to_close_file(i)


class CodeNavigator(QWidget):

    def __init__(self):
        QWidget.__init__(self)
        self.setContextMenuPolicy(Qt.DefaultContextMenu)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setContentsMargins(0, 0, 0, 0)
        hbox = QHBoxLayout(self)
        hbox.setContentsMargins(1, 1, 5, 1)
        hbox.setSpacing(0)
        self.btnPrevious = QPushButton(
            QIcon(":img/nav-code-left"), '')
        self.btnPrevious.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.btnPrevious.setObjectName('navigation_button')
        self.btnPrevious.setToolTip(translations.TR_TOOLTIP_NAV_BUTTONS)
        self.btnNext = QPushButton(
            QIcon(":img/nav-code-right"), '')
        self.btnNext.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.btnNext.setObjectName('navigation_button')
        self.btnNext.setToolTip(translations.TR_TOOLTIP_NAV_BUTTONS)
        hbox.addWidget(self.btnPrevious)
        hbox.addWidget(self.btnNext)

        self.menuNavigate = QMenu(self.tr("Navigate"))
        self.codeAction = self.menuNavigate.addAction(
            translations.TR_NAV_CODE_JUMP)
        self.codeAction.setCheckable(True)
        self.codeAction.setChecked(True)
        self.bookmarksAction = self.menuNavigate.addAction(
            translations.TR_NAV_BOOKMARKS)
        self.bookmarksAction.setCheckable(True)
        self.breakpointsAction = self.menuNavigate.addAction(
            translations.TR_NAV_BREAKPOINTS)
        self.breakpointsAction.setCheckable(True)

        # 0 = Code Jumps
        # 1 = Bookmarks
        # 2 = Breakpoints
        self.operation = 0

        self.connect(self.codeAction, SIGNAL("triggered()"),
            self._show_code_nav)
        self.connect(self.breakpointsAction, SIGNAL("triggered()"),
            self._show_breakpoints)
        self.connect(self.bookmarksAction, SIGNAL("triggered()"),
            self._show_bookmarks)

    def contextMenuEvent(self, event):
        self.show_menu_navigation()

    def show_menu_navigation(self):
        self.menuNavigate.exec_(QCursor.pos())

    def _show_bookmarks(self):
        self.btnPrevious.setIcon(QIcon(':img/book-left'))
        self.btnNext.setIcon(QIcon(':img/book-right'))
        self.bookmarksAction.setChecked(True)
        self.breakpointsAction.setChecked(False)
        self.codeAction.setChecked(False)
        self.operation = 1

    def _show_breakpoints(self):
        self.btnPrevious.setIcon(QIcon(':img/break-left'))
        self.btnNext.setIcon(QIcon(':img/break-right'))
        self.bookmarksAction.setChecked(False)
        self.breakpointsAction.setChecked(True)
        self.codeAction.setChecked(False)
        self.operation = 2

    def _show_code_nav(self):
        self.btnPrevious.setIcon(QIcon(':img/nav-code-left'))
        self.btnNext.setIcon(QIcon(':img/nav-code-right'))
        self.bookmarksAction.setChecked(False)
        self.breakpointsAction.setChecked(False)
        self.codeAction.setChecked(True)
        self.operation = 0
