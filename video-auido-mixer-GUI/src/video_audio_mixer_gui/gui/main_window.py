"""PySide6 主窗口实现。"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtWidgets import QHeaderView

from video_audio_mixer_gui.dragdrop.file_collector import collect_media_from_paths
from video_audio_mixer_gui.models.media import AudioClip, AudioCategory, ImportResult, MixSession
from video_audio_mixer_gui.core.config_manager import AppConfig


class AudioListWidget(QtWidgets.QListWidget):
    audioDropped = QtCore.Signal(list, AudioCategory)

    def __init__(self, category: AudioCategory, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._category = category
        self.setAcceptDrops(True)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(True)

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QtGui.QDropEvent) -> None:  # type: ignore[override]
        urls = event.mimeData().urls()
        paths = [Path(url.toLocalFile()) for url in urls]
        if paths:
            self.audioDropped.emit(paths, self._category)
        event.acceptProposedAction()


class MainWindow(QtWidgets.QMainWindow):
    """应用主窗口。"""

    mediaImported = QtCore.Signal(ImportResult)
    sessionSelected = QtCore.Signal(str)
    previewRequested = QtCore.Signal(str)
    mixRequested = QtCore.Signal(str)
    videoDeleteRequested = QtCore.Signal(str)
    audioDeleteRequested = QtCore.Signal(str, str)
    audioParametersChanged = QtCore.Signal(str, str, float, float)
    audioSelectionChanged = QtCore.Signal(str, str)
    globalConfigChanged = QtCore.Signal(bool, int, int, float, float, bool, Path, bool)
    audioFilesDropped = QtCore.Signal(list, AudioCategory)
    batchAudioSelected = QtCore.Signal(list, AudioCategory, list)

    def __init__(self, app_config: AppConfig) -> None:
        super().__init__()
        self.setWindowTitle("音视频混合工具")
        self.resize(1400, 760)
        self._current_video_id: Optional[str] = None
        self._shortcuts: List[QtGui.QShortcut] = []
        self._audio_lists: Dict[AudioCategory, AudioListWidget] = {}
        self._app_config = app_config
        self._current_video_fps: float = 0.0
        self._current_audio_clips: List[AudioClip] = []
        self._setup_ui()
        self._setup_actions()
        self._setup_drag_drop()
        self._setup_shortcuts()

    def _setup_ui(self) -> None:
        """初始化界面布局。"""

        central_widget = QtWidgets.QWidget(self)
        layout = QtWidgets.QHBoxLayout(central_widget)

        self.video_list = QtWidgets.QTreeWidget(central_widget)
        self.video_list.setColumnCount(5)
        self.video_list.setHeaderLabels(["#", "视频", "SE", "VO", "MUSIC"])
        self.video_list.setRootIsDecorated(False)
        self.video_list.setUniformRowHeights(True)
        self.video_list.setMinimumWidth(420)
        self.video_list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.video_list.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.video_list.setSortingEnabled(True)
        header = self.video_list.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Fixed)
        self.video_list.setColumnWidth(0, 50)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        for idx in (2, 3, 4):
            header.setSectionResizeMode(idx, QtWidgets.QHeaderView.Fixed)
            self.video_list.setColumnWidth(idx, 40)
        header.setDefaultAlignment(QtCore.Qt.AlignCenter)
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        self.video_list.sortByColumn(0, QtCore.Qt.AscendingOrder)
        layout.addWidget(self.video_list, stretch=3)

        right_panel = QtWidgets.QWidget(central_widget)
        right_layout = QtWidgets.QVBoxLayout(right_panel)
        self.audio_tabs = QtWidgets.QTabWidget(right_panel)
        self.audio_tabs.setMinimumWidth(380)
        for category, tab_name in (
            (AudioCategory.SE, "SE"),
            (AudioCategory.VO, "VO"),
            (AudioCategory.MUSIC, "MUSIC"),
        ):
            list_widget = AudioListWidget(category=category, parent=right_panel)
            self.audio_tabs.addTab(list_widget, tab_name)
            self._audio_lists[category] = list_widget
        right_layout.addWidget(self.audio_tabs, stretch=1)

        status_group = QtWidgets.QGroupBox("匹配状态", right_panel)
        status_layout = QtWidgets.QGridLayout(status_group)
        self.status_labels: Dict[AudioCategory, QtWidgets.QLabel] = {}
        row = 0
        for category, label in (
            (AudioCategory.SE, "SE"),
            (AudioCategory.VO, "VO"),
            (AudioCategory.MUSIC, "MUSIC"),
        ):
            indicator = QtWidgets.QLabel("未匹配")
            indicator.setMinimumWidth(60)
            indicator.setAlignment(QtCore.Qt.AlignCenter)
            status_layout.addWidget(QtWidgets.QLabel(label), row, 0)
            status_layout.addWidget(indicator, row, 1)
            self.status_labels[category] = indicator
            row += 1
        right_layout.addWidget(status_group)
        status_group.setMaximumHeight(90)

        config_group = QtWidgets.QGroupBox("全局参数", right_panel)
        config_layout = QtWidgets.QGridLayout(config_group)
        self.music_random_checkbox = QtWidgets.QCheckBox("音乐随机起点", config_group)
        self.music_random_checkbox.setChecked(self._app_config.music_random_enabled)
        self.music_retry_spin = QtWidgets.QSpinBox(config_group)
        self.music_retry_spin.setRange(1, 100)
        self.music_retry_spin.setValue(self._app_config.music_retry_limit)
        self.music_seed_spin = QtWidgets.QSpinBox(config_group)
        self.music_seed_spin.setRange(-1, 10_000_000)
        self.music_seed_spin.setValue(self._app_config.music_default_seed or -1)
        self.music_offset_spin = QtWidgets.QDoubleSpinBox(config_group)
        self.music_offset_spin.setRange(0.0, 100000.0)
        self.music_offset_spin.setDecimals(3)
        self.music_offset_spin.setValue(self._app_config.music_start_offset)
        self.video_lead_spin = QtWidgets.QDoubleSpinBox(config_group)
        self.video_lead_spin.setRange(0.0, 100000.0)
        self.video_lead_spin.setDecimals(3)
        self.video_lead_spin.setValue(self._app_config.video_audio_lead)
        self.enable_limiter_checkbox = QtWidgets.QCheckBox("amix normalize 开启", config_group)
        self.enable_limiter_checkbox.setChecked(self._app_config.enable_limiter)
        self.override_original_checkbox = QtWidgets.QCheckBox("覆盖原视频音频", config_group)
        self.override_original_checkbox.setChecked(self._app_config.override_original)
        self.output_dir_edit = QtWidgets.QLineEdit(str(self._app_config.output_directory), config_group)
        self.output_dir_button = QtWidgets.QPushButton("选择目录", config_group)
        config_layout.addWidget(self.music_random_checkbox, 0, 0, 1, 2)
        config_layout.addWidget(QtWidgets.QLabel("随机重试"), 1, 0)
        config_layout.addWidget(self.music_retry_spin, 1, 1)
        config_layout.addWidget(QtWidgets.QLabel("随机种子 (-1=禁用)"), 2, 0)
        config_layout.addWidget(self.music_seed_spin, 2, 1)
        config_layout.addWidget(QtWidgets.QLabel("音乐偏移 (秒)"), 3, 0)
        config_layout.addWidget(self.music_offset_spin, 3, 1)
        config_layout.addWidget(QtWidgets.QLabel("音频全局延迟 (秒)"), 4, 0)
        config_layout.addWidget(self.video_lead_spin, 4, 1)
        config_layout.addWidget(QtWidgets.QLabel("输出目录"), 5, 0)
        config_layout.addWidget(self.output_dir_edit, 5, 1)
        config_layout.addWidget(self.output_dir_button, 6, 0, 1, 2)
        config_layout.addWidget(self.enable_limiter_checkbox, 7, 0, 1, 2)
        config_layout.addWidget(self.override_original_checkbox, 8, 0, 1, 2)
        right_layout.addWidget(config_group)

        self.audio_form = QtWidgets.QGroupBox("音频参数", right_panel)
        form_layout = QtWidgets.QGridLayout(self.audio_form)
        self.start_seconds_spin = QtWidgets.QDoubleSpinBox(self.audio_form)
        self.start_seconds_spin.setRange(0.0, 100000.0)
        self.start_seconds_spin.setDecimals(3)
        self.start_seconds_spin.setSuffix(" s")
        self.start_frames_spin = QtWidgets.QSpinBox(self.audio_form)
        self.start_frames_spin.setRange(0, 1_000_000)
        self.start_frames_spin.setSuffix(" 帧")
        self.source_offset_spin = QtWidgets.QDoubleSpinBox(self.audio_form)
        self.source_offset_spin.setRange(0.0, 100000.0)
        self.source_offset_spin.setDecimals(3)
        self.source_offset_spin.setSuffix(" s")
        form_layout.addWidget(QtWidgets.QLabel("视频时间起点"), 0, 0)
        form_layout.addWidget(self.start_seconds_spin, 0, 1)
        form_layout.addWidget(QtWidgets.QLabel("视频时间起点 (帧)"), 1, 0)
        form_layout.addWidget(self.start_frames_spin, 1, 1)
        form_layout.addWidget(QtWidgets.QLabel("音频源偏移"), 2, 0)
        form_layout.addWidget(self.source_offset_spin, 2, 1)
        self.save_audio_button = QtWidgets.QPushButton("保存参数", self.audio_form)
        form_layout.addWidget(self.save_audio_button, 3, 0, 1, 2)
        right_layout.addWidget(self.audio_form)

        button_layout = QtWidgets.QHBoxLayout()
        self.preview_button = QtWidgets.QPushButton("预览", right_panel)
        self.preview_button.setMinimumWidth(100)
        self.mix_button = QtWidgets.QPushButton("开始混流", right_panel)
        button_layout.addWidget(self.preview_button)
        button_layout.addWidget(self.mix_button)
        right_layout.addLayout(button_layout)

        layout.addWidget(right_panel, stretch=3)
        self.setCentralWidget(central_widget)
        status_bar = QtWidgets.QStatusBar(self)
        status_bar.showMessage("准备就绪")
        self.setStatusBar(status_bar)

    def _setup_actions(self) -> None:
        """设置菜单与按钮动作。"""

        exit_action = QtGui.QAction("退出 (Ctrl+Q)", self)
        exit_action.setShortcut(QtGui.QKeySequence("Ctrl+Q"))
        exit_action.triggered.connect(QtWidgets.QApplication.quit)

        preview_action = QtGui.QAction("预览 (Ctrl+P)", self)
        preview_action.setShortcut(QtGui.QKeySequence("Ctrl+P"))
        preview_action.triggered.connect(self._on_preview_clicked)

        mix_action = QtGui.QAction("开始混流 (Ctrl+M)", self)
        mix_action.setShortcut(QtGui.QKeySequence("Ctrl+M"))
        mix_action.triggered.connect(self._on_mix_clicked)

        delete_action = QtGui.QAction("删除 (Del)", self)
        delete_action.setShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Delete))
        delete_action.triggered.connect(self._handle_delete)

        batch_se_action = QtGui.QAction("为选中视频批量添加 SE", self)
        batch_se_action.triggered.connect(lambda: self._trigger_batch_audio(AudioCategory.SE))
        batch_vo_action = QtGui.QAction("为选中视频批量添加 VO", self)
        batch_vo_action.triggered.connect(lambda: self._trigger_batch_audio(AudioCategory.VO))
        batch_music_action = QtGui.QAction("为选中视频批量添加 MUSIC", self)
        batch_music_action.triggered.connect(lambda: self._trigger_batch_audio(AudioCategory.MUSIC))

        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("文件")
        file_menu.addAction(preview_action)
        file_menu.addAction(mix_action)
        file_menu.addAction(delete_action)
        file_menu.addSeparator()
        file_menu.addAction(exit_action)

        tools_menu = menu_bar.addMenu("常用功能")
        tools_menu.addAction(batch_se_action)
        tools_menu.addAction(batch_vo_action)
        tools_menu.addAction(batch_music_action)

        self.preview_button.clicked.connect(self._on_preview_clicked)
        self.mix_button.clicked.connect(self._on_mix_clicked)
        self.video_list.itemSelectionChanged.connect(self._on_video_selected)
        self.save_audio_button.clicked.connect(self._on_save_audio_params)
        for widget in self._audio_lists.values():
            widget.itemSelectionChanged.connect(self._on_audio_selection_changed)
            widget.audioDropped.connect(self._on_audio_dropped)
        self.music_random_checkbox.stateChanged.connect(self._on_global_config_changed)
        self.music_retry_spin.valueChanged.connect(self._on_global_config_changed)
        self.music_seed_spin.valueChanged.connect(self._on_global_config_changed)
        self.music_offset_spin.valueChanged.connect(self._on_global_config_changed)
        self.video_lead_spin.valueChanged.connect(self._on_global_config_changed)
        self.enable_limiter_checkbox.stateChanged.connect(self._on_global_config_changed)
        self.override_original_checkbox.stateChanged.connect(self._on_global_config_changed)
        self.output_dir_edit.textChanged.connect(self._on_global_config_changed)
        self.output_dir_button.clicked.connect(self._select_output_directory)
        self.start_seconds_spin.valueChanged.connect(self._on_seconds_changed)
        self.start_frames_spin.valueChanged.connect(self._on_frames_changed)

    def _setup_drag_drop(self) -> None:
        """配置拖放行为。"""

        self.setAcceptDrops(True)

    def _setup_shortcuts(self) -> None:
        """配置快捷键。"""

        delete_shortcut = QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Delete), self)
        delete_shortcut.activated.connect(self._handle_delete)
        preview_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+P"), self)
        preview_shortcut.activated.connect(self._on_preview_clicked)
        mix_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+M"), self)
        mix_shortcut.activated.connect(self._on_mix_clicked)
        self._shortcuts.extend([delete_shortcut, preview_shortcut, mix_shortcut])

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QtGui.QDropEvent) -> None:  # type: ignore[override]
        urls = event.mimeData().urls()
        paths = [Path(url.toLocalFile()) for url in urls]
        self._emit_import(paths)

    def _emit_import(self, paths: List[Path]) -> None:
        """发出媒体导入信号。"""

        result = collect_media_from_paths(paths)
        self.mediaImported.emit(result)

    def _on_preview_clicked(self) -> None:
        """处理预览按钮点击。"""

        current_item = self.video_list.currentItem()
        if current_item is None:
            return
        video_id = current_item.data(0, QtCore.Qt.UserRole)
        if video_id is None:
            return
        self._current_video_id = video_id
        self.previewRequested.emit(video_id)

    def _on_mix_clicked(self) -> None:
        """处理混流按钮点击。"""

        current_item = self.video_list.currentItem()
        if current_item is None:
            return
        video_id = current_item.data(0, QtCore.Qt.UserRole)
        self._current_video_id = video_id
        self.mixRequested.emit(video_id)

    def _on_video_selected(self) -> None:
        """视频选择变化时发出会话选择信号。"""

        current_item = self.video_list.currentItem()
        if current_item is None:
            return
        video_id = current_item.data(0, QtCore.Qt.UserRole)
        self._current_video_id = video_id
        self.sessionSelected.emit(video_id)

    def _handle_delete(self) -> None:
        """处理删除快捷键。"""

        if self.video_list.hasFocus():
            self._emit_video_delete()
            return
        audio_widget = self._current_audio_widget()
        if audio_widget is not None and audio_widget.hasFocus():
            self._emit_audio_delete(audio_widget)

    def _emit_video_delete(self) -> None:
        """发出删除视频信号。"""

        if self._current_video_id is None:
            return
        self.videoDeleteRequested.emit(self._current_video_id)

    def _emit_audio_delete(self, widget: QtWidgets.QListWidget) -> None:
        """发出删除音频信号。"""

        if self._current_video_id is None:
            return
        current_item = widget.currentItem()
        if current_item is None:
            return
        audio_id = current_item.data(QtCore.Qt.UserRole)
        if audio_id is None:
            return
        self.audioDeleteRequested.emit(self._current_video_id, audio_id)

    def _current_audio_widget(self) -> Optional[QtWidgets.QListWidget]:
        """获取当前激活的音频列表控件。"""

        widget = self.audio_tabs.currentWidget()
        if isinstance(widget, AudioListWidget):
            return widget
        return None

    def get_audio_drop_category(self, widget: QtWidgets.QListWidget) -> Optional[AudioCategory]:
        for category, list_widget in self._audio_lists.items():
            if list_widget is widget:
                return category
        return None

    def set_video_sessions(self, sessions: List[MixSession]) -> None:
        """更新视频列表显示。"""

        current_id = self._current_video_id
        self.video_list.blockSignals(True)
        self.video_list.clear()
        index_to_select = 0
        for idx, session in enumerate(sessions, start=1):
            counts = self._count_audio(session.audio_clips)
            item = QtWidgets.QTreeWidgetItem(
                [
                    str(idx),
                    session.video_clip.display_name,
                    str(counts.get(AudioCategory.SE, 0)),
                    str(counts.get(AudioCategory.VO, 0)),
                    str(counts.get(AudioCategory.MUSIC, 0)),
                ]
            )
            item.setData(0, QtCore.Qt.UserRole, session.video_clip.clip_id)
            self.video_list.addTopLevelItem(item)
            if current_id and session.video_clip.clip_id == current_id:
                index_to_select = idx - 1
        if sessions:
            current_item = self.video_list.topLevelItem(index_to_select)
            self.video_list.setCurrentItem(current_item)
            self._current_video_id = current_item.data(0, QtCore.Qt.UserRole)
        else:
            self._current_video_id = None
        self.video_list.blockSignals(False)
        self.statusBar().showMessage(f"已加载视频 {len(sessions)} 个")

    @property
    def current_video_id(self) -> Optional[str]:
        """返回当前选中视频 ID。"""

        return self._current_video_id

    def select_video(self, video_id: str) -> None:
        """根据 ID 选中视频条目。"""

        if video_id is None:
            return
        for idx in range(self.video_list.topLevelItemCount()):
            item = self.video_list.topLevelItem(idx)
            if item.data(0, QtCore.Qt.UserRole) == video_id:
                self.video_list.setCurrentItem(item)
                return

    def set_audio_clips(self, video_id: str, clips: List[AudioClip], video_fps: float) -> None:
        """刷新音频标签页内容。"""

        self._current_video_id = video_id
        self._current_video_fps = video_fps
        self._current_audio_clips = list(clips)
        self._clear_audio_lists()
        for clip in clips:
            list_widget = self._audio_lists.get(clip.category)
            if list_widget is None:
                continue
            item = QtWidgets.QListWidgetItem(clip.display_name)
            item.setData(QtCore.Qt.UserRole, clip.clip_id)
            start_info = clip.start_frame if clip.start_frame is not None else 0
            item.setToolTip(f"起始帧: {start_info}\n时长: {clip.duration_seconds:.2f}s")
            list_widget.addItem(item)
        self._update_audio_form()
        self._refresh_status_indicators()
        self._refresh_video_row_counts(video_id)

    def _clear_audio_lists(self) -> None:
        """清空音频列表。"""

        for widget in self._audio_lists.values():
            widget.clear()
        self.start_seconds_spin.setValue(0.0)
        self.start_frames_spin.setValue(0)
        self.source_offset_spin.setValue(0.0)
        for indicator in self.status_labels.values():
            indicator.setText("未匹配")
            indicator.setStyleSheet("color: #b00")

    def show_warning(self, message: str) -> None:
        """弹出警告信息。"""

        QtWidgets.QMessageBox.warning(self, "警告", message)

    def clear_selection(self) -> None:
        """清空当前选中状态。"""

        self.video_list.clearSelection()
        self._clear_audio_lists()
        self._current_video_id = None

    def _update_audio_form(self) -> None:
        """根据当前选中音频更新表单。"""

        widget = self._current_audio_widget()
        if widget is None:
            self.start_seconds_spin.setValue(0.0)
            self.start_frames_spin.setValue(0)
            self.source_offset_spin.setValue(0.0)
            return
        current_item = widget.currentItem()
        if current_item is None:
            self.start_seconds_spin.setValue(0.0)
            self.start_frames_spin.setValue(0)
            self.source_offset_spin.setValue(0.0)
            return
        audio_id = current_item.data(QtCore.Qt.UserRole)
        if audio_id is None:
            return
        for clip in self._current_audio_clips:
            if clip.clip_id == audio_id:
                seconds = 0.0
                if clip.start_frame is not None and self._current_video_fps > 0:
                    seconds = clip.start_frame / self._current_video_fps
                self.start_seconds_spin.blockSignals(True)
                self.start_frames_spin.blockSignals(True)
                self.start_seconds_spin.setValue(seconds)
                self.start_frames_spin.setValue(
                    int(seconds * self._current_video_fps) if self._current_video_fps > 0 else 0
                )
                self.start_seconds_spin.blockSignals(False)
                self.start_frames_spin.blockSignals(False)
                self.source_offset_spin.setValue(clip.source_start_seconds)
                break

    def _on_save_audio_params(self) -> None:
        """保存音频参数修改。"""

        widget = self._current_audio_widget()
        if widget is None or self._current_video_id is None:
            return
        current_item = widget.currentItem()
        if current_item is None:
            return
        audio_id = current_item.data(QtCore.Qt.UserRole)
        if audio_id is None:
            return
        start_seconds = self.start_seconds_spin.value()
        source_offset = self.source_offset_spin.value()
        self.audioParametersChanged.emit(self._current_video_id, audio_id, start_seconds, source_offset)

    def _on_audio_selection_changed(self) -> None:
        widget = self._current_audio_widget()
        if widget is None or self._current_video_id is None:
            return
        current_item = widget.currentItem()
        if current_item is None:
            self.start_seconds_spin.setValue(0.0)
            self.start_frames_spin.setValue(0)
            self.source_offset_spin.setValue(0.0)
            return
        audio_id = current_item.data(QtCore.Qt.UserRole)
        if audio_id is None:
            return
        self.audioSelectionChanged.emit(self._current_video_id, audio_id)
        self._update_audio_form()
        self._refresh_status_indicators()

    def _on_audio_dropped(self, paths: list[Path], category: AudioCategory) -> None:
        self.audioFilesDropped.emit(paths, category)

    def _on_global_config_changed(self) -> None:
        self.globalConfigChanged.emit(
            self.music_random_checkbox.isChecked(),
            self.music_retry_spin.value(),
            self.music_seed_spin.value(),
            self.music_offset_spin.value(),
            self.video_lead_spin.value(),
            self.enable_limiter_checkbox.isChecked(),
            Path(self.output_dir_edit.text() or str(self._app_config.output_directory)),
            self.override_original_checkbox.isChecked(),
        )
        self._refresh_status_indicators()

    def _on_seconds_changed(self, value: float) -> None:
        if self._current_video_fps > 0:
            self.start_frames_spin.blockSignals(True)
            self.start_frames_spin.setValue(int(value * self._current_video_fps))
            self.start_frames_spin.blockSignals(False)

    def _on_frames_changed(self, value: int) -> None:
        if self._current_video_fps > 0:
            seconds = value / self._current_video_fps
            self.start_seconds_spin.blockSignals(True)
            self.start_seconds_spin.setValue(seconds)
            self.start_seconds_spin.blockSignals(False)

    def _refresh_status_indicators(self) -> None:
        clips_by_category: Dict[AudioCategory, int] = {
            AudioCategory.SE: 0,
            AudioCategory.VO: 0,
            AudioCategory.MUSIC: 0,
        }
        for clip in self._current_audio_clips:
            clips_by_category[clip.category] = clips_by_category.get(clip.category, 0) + 1
        for category, indicator in self.status_labels.items():
            if clips_by_category.get(category, 0) > 0:
                indicator.setText("已匹配")
                indicator.setStyleSheet("color: #090")
            else:
                indicator.setText("未匹配")
                indicator.setStyleSheet("color: #b00")

    def _count_audio(self, clips: List[AudioClip]) -> Dict[AudioCategory, int]:
        counts: Dict[AudioCategory, int] = {
            AudioCategory.SE: 0,
            AudioCategory.VO: 0,
            AudioCategory.MUSIC: 0,
        }
        for clip in clips:
            counts[clip.category] = counts.get(clip.category, 0) + 1
        return counts

    def _refresh_video_row_counts(self, video_id: str) -> None:
        for idx in range(self.video_list.topLevelItemCount()):
            item = self.video_list.topLevelItem(idx)
            if item.data(0, QtCore.Qt.UserRole) == video_id:
                counts = self._count_audio(self._current_audio_clips)
                item.setText(2, str(counts.get(AudioCategory.SE, 0)))
                item.setText(3, str(counts.get(AudioCategory.VO, 0)))
                item.setText(4, str(counts.get(AudioCategory.MUSIC, 0)))
                break

    def _trigger_batch_audio(self, category: AudioCategory) -> None:
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            "选择要添加的音频文件",
            str(Path.cwd()),
            "音频文件 (*.wav *.mp3 *.flac *.aac *.ogg *.m4a);;所有文件 (*)",
        )
        if not files:
            return
        selected_ids = [item.data(0, QtCore.Qt.UserRole) for item in self.video_list.selectedItems()]
        selected_ids = [vid for vid in selected_ids if vid]
        if not selected_ids:
            QtWidgets.QMessageBox.information(self, "提示", "请先选中要批量添加音频的视频。")
            return
        self.batchAudioSelected.emit(selected_ids, category, [Path(f) for f in files])

    def _select_output_directory(self) -> None:
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, "选择输出目录", str(self._app_config.output_directory))
        if directory:
            self.output_dir_edit.setText(directory)


