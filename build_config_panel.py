"""Form controls for existing Cocos iOS build options."""
import copy
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QFormLayout,QCheckBox,QLineEdit,
    QComboBox,QGroupBox,QListWidget,QListWidgetItem,QPushButton,QLabel,QSizePolicy)


class BuildConfigPanel(QWidget):
    changed=Signal()
    reset_requested=Signal()

    def __init__(self,parent=None):
        super().__init__(parent)
        self.original={};self.fields={};self.loading=False
        layout=QVBoxLayout(self)
        self.toggle=QPushButton('Cocos iOS Build Config ▸')
        self.toggle.setCheckable(True)
        self.toggle.setToolTip('Bấm để mở hoặc thu gọn cấu hình build iOS')
        layout.addWidget(self.toggle)
        group=QGroupBox()
        self.body=group
        layout.addWidget(group)
        group.setVisible(False)
        self.toggle.toggled.connect(group.setVisible)
        self.toggle.toggled.connect(lambda opened: self.toggle.setText('Cocos iOS Build Config ▾' if opened else 'Cocos iOS Build Config ▸'))
        form=QFormLayout(group)
        def check(label,key):
            field=QCheckBox(label);field.toggled.connect(self.edited)
            self.fields[key]=field;form.addRow(field)
        def text(label,key,secret=False):
            field=QLineEdit();field.textEdited.connect(self.edited)
            if secret: field.setEchoMode(QLineEdit.EchoMode.Password)
            self.fields[key]=field;form.addRow(label,field)
        self.debug=QComboBox();self.debug.addItem('Debug',True);self.debug.addItem('Release',False)
        self.debug.currentIndexChanged.connect(self.edited)
        form.addRow('Chế độ build',self.debug)
        text('Tên build','name');text('Thư mục output','buildPath');text('Tên thư mục con','outputName')
        for label,key in [('MD5 Cache','md5Cache'),('Source Maps','sourceMaps'),('Auto Atlas','packAutoAtlas'),('Bỏ qua nén texture','skipCompressTexture')]: check(label,key)
        self.compression=QComboBox()
        for value in ['merge_dep','merge_all_json','none']: self.compression.addItem(value,value)
        self.compression.currentIndexChanged.connect(self.edited)
        form.addRow('Main bundle compression',self.compression)
        text('iOS tối thiểu','packages.ios.targetVersion')
        check('Auto Rotate (tự xoay theo các hướng đã chọn)','builderAutoRotate')
        self.fields['builderAutoRotate'].setChecked(True)
        self.fields['builderAutoRotate'].setToolTip('Áp dụng override trong native/engine/ios/ViewController.mm được sinh ra; không sửa native-templates. Tắt để dùng logic xoay gốc của game.')
        for label,key in [('Portrait','portrait'),('Portrait Upside Down','upsideDown'),('Landscape Left','landscapeLeft'),('Landscape Right','landscapeRight')]:
            check(label,'packages.ios.orientation.'+key)
        check('Metal','packages.ios.renderBackEnd.metal')
        check('Mã hóa script','packages.native.encrypted')
        text('Khóa XXTEA','packages.native.xxteaKey',True)
        check('Nén ZIP native','packages.native.compressZip')
        self.scenes=QListWidget();self.scenes.setMaximumHeight(160)
        self.scenes.itemChanged.connect(self.scenes_changed)
        form.addRow('Scenes đưa vào build',self.scenes)
        self.start=QComboBox();self.start.currentIndexChanged.connect(self.edited)
        self.start.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.start.setMinimumContentsLength(12)
        self.start.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
        self.start.setMinimumWidth(140)
        self.start.currentTextChanged.connect(self.start.setToolTip)
        form.addRow('Scene khởi động',self.start)
        note=QLabel('Bundle ID và Apple Team ID dùng các ô phía trên. Simulator / iPhone theo thiết bị đã chọn.\nThay đổi cấu hình sẽ tự xuất lại Cocos; chế độ chỉ build native bị bỏ qua cho lượt đó.')
        note.setWordWrap(True);form.addRow(note)
        reset=QPushButton('Khôi phục cấu hình Cocos');reset.clicked.connect(self.reset_requested)
        form.addRow(reset)

    def edited(self,*args):
        if not self.loading: self.changed.emit()

    def load(self,options,scene_catalog=None):
        self.loading=True;self.original=copy.deepcopy(options)
        self.debug.setCurrentIndex(0 if options.get('debug',True) else 1)
        for key,field in self.fields.items():
            value=options
            for part in key.split('.'): value=value.get(part,{}) if isinstance(value,dict) else {}
            if key == 'builderAutoRotate': value=options.get(key,True)
            if isinstance(field,QCheckBox): field.setChecked(value is True)
            else: field.setText('' if isinstance(value,dict) else str(value))
        value=options.get('mainBundleCompressionType','merge_dep')
        if self.compression.findData(value)<0:self.compression.addItem(value,value)
        self.compression.setCurrentIndex(self.compression.findData(value))
        self.scenes.clear()
        catalog={s['uuid']:s for s in (scene_catalog or [])+options.get('scenes',[]) if s.get('uuid')}
        selected={s['uuid'] for s in options.get('scenes',[])}
        for uuid,scene in catalog.items():
            item=QListWidgetItem(scene.get('url',uuid));item.setData(Qt.ItemDataRole.UserRole,scene)
            item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if uuid in selected else Qt.CheckState.Unchecked)
            self.scenes.addItem(item)
        self.rebuild_start(options.get('startScene'))
        self.loading=False

    def selected_scenes(self):
        return [copy.deepcopy(self.scenes.item(i).data(Qt.ItemDataRole.UserRole)) for i in range(self.scenes.count()) if self.scenes.item(i).checkState()==Qt.CheckState.Checked]

    def rebuild_start(self,current):
        self.start.blockSignals(True);self.start.clear()
        for s in self.selected_scenes():self.start.addItem(s.get('url',s['uuid']),s['uuid'])
        index=self.start.findData(current)
        if index>=0:self.start.setCurrentIndex(index)
        self.start.blockSignals(False)

    def scenes_changed(self,*args):
        if self.loading:return
        self.rebuild_start(self.start.currentData());self.edited()

    def options(self):
        result=copy.deepcopy(self.original)
        result['debug']=self.debug.currentData()
        result['mainBundleCompressionType']=self.compression.currentData()
        for key,field in self.fields.items():
            value=field.isChecked() if isinstance(field,QCheckBox) else field.text().strip()
            parts=key.split('.');target=result
            for part in parts[:-1]:target=target.setdefault(part,{})
            target[parts[-1]]=value
        result['scenes']=self.selected_scenes();result['startScene']=self.start.currentData() or ''
        return result
