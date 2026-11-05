"""Peripheral Battery 2 — Windows notification area battery monitor."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import time


def main():
    parser=argparse.ArgumentParser(description='Windows 无线设备电量托盘')
    parser.add_argument('--background',action='store_true')
    parser.add_argument('--autostart',action='store_true',help='由当前用户登录启动任务调用')
    parser.add_argument('--worker',metavar='REQUEST')
    parser.add_argument('--apply-update',metavar='REQUEST')
    parser.add_argument('--diagnose',action='store_true')
    parser.add_argument('--diagnose-mchose',action='store_true',help='仅诊断迈从状态接口，结果不含设备路径或序列号')
    parser.add_argument('--diagnose-hid',action='store_true',help='导出外设身份和 Feature 描述诊断，不读取键鼠输入')
    parser.add_argument('--diagnostic-output',metavar='JSON')
    parser.add_argument('--startup-check',action='store_true')
    parser.add_argument('--install-startup',action='store_true')
    parser.add_argument('--configure-updates',metavar='JSON',help='导入仅保存在本机用户目录的更新部署配置')
    parser.add_argument('--quit',action='store_true')
    parser.add_argument('--capture',metavar='PNG')
    parser.add_argument('--demo',action='store_true',help='明确标注的演示数据，不查询硬件')
    parser.add_argument('--demo-count',type=int,default=3)
    args=parser.parse_args()
    from settings import LOCAL_PREVIEW
    if LOCAL_PREVIEW and any((args.configure_updates, args.apply_update, args.autostart,
                              args.install_startup)):
        return 2
    if args.configure_updates:
        from update_config import save_config
        try:
            raw=Path(args.configure_updates).read_bytes()
            if len(raw)>16384:return 2
            save_config(json.loads(raw));return 0
        except (OSError,ValueError):return 2
    if args.apply_update:
        from installer import apply_update
        return apply_update(args.apply_update)
    # Dispatch before importing Qt. The GUI can terminate a blocked native worker.
    if args.worker:
        from process_tree import join_worker_job
        join_worker_job()
        from worker import run
        return run(args.worker)
    from settings import VERSION,EXPERIMENTAL_ENABLED,Settings,DeviceStore,configure_logging,atomic_json,data_dir,redact,cleanup_workers,migrate_legacy_data
    import startup
    migrate_legacy_data()
    logger=configure_logging();preferences=Settings()
    if args.autostart:
        try:startup.cleanup_legacy()
        except OSError as error:logger.warning('legacy startup cleanup: %s',redact(error))
    cleanup_workers()
    logger.info('boot version=%s pid=%s background=%s frozen=%s autostart=%s',VERSION,os.getpid(),args.background,getattr(sys,'frozen',False),args.autostart)
    if args.install_startup:
        current=startup.set_enabled(True);preferences.set('autostart_requested',True)
        logger.info('startup registration enabled target=%s',redact(current.target));return 0
    if args.startup_check:
        value=asdict(startup.state())
        if args.diagnostic_output:atomic_json(args.diagnostic_output,value)
        elif sys.stdout:print(json.dumps(value,ensure_ascii=False,indent=2))
        return 0
    if args.diagnose_hid:
        from providers import diagnose_hid
        value={'version':VERSION,'generated_at':time.time(),**diagnose_hid()}
        if args.diagnostic_output:atomic_json(args.diagnostic_output,value)
        elif sys.stdout:print(json.dumps(value,ensure_ascii=False,indent=2))
        return 0
    if args.diagnose_mchose:
        from providers import diagnose_mchose
        value={'version':VERSION,'scope':'仅迈从 HID 设备状态；不包含设备路径或序列号',**diagnose_mchose()}
        if args.diagnostic_output:atomic_json(args.diagnostic_output,value)
        elif sys.stdout:print(json.dumps(value,ensure_ascii=False,indent=2))
        return 0
    if args.diagnose:
        from providers import Scanner
        devices,errors=Scanner().scan()
        value={'version':VERSION,'devices':[d.to_dict() for d in devices],'errors':errors}
        if args.diagnostic_output:atomic_json(args.diagnostic_output,value)
        elif sys.stdout:print(json.dumps(value,ensure_ascii=False,indent=2))
        return 0
    import ctypes
    app_id = 'LocalTools.PeripheralBattery.Preview' if LOCAL_PREVIEW else 'LocalTools.PeripheralBattery'
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    from PySide6.QtCore import QTimer,QLockFile
    from PySide6.QtNetwork import QLocalServer,QLocalSocket
    from PySide6.QtWidgets import QApplication,QSystemTrayIcon,QMenu,QFileDialog
    # Explicit import ensures the SVG engine is bundled for official vector logos.
    from PySide6 import QtSvg
    from jobs import ScanController
    from scheduling import RefreshTimer
    from classification import apply_saved_modes
    from icons import tray_icon,font
    from appearance import panel_dark
    from models import Device,lowest
    from notifications import collect_low_alerts
    from catalog import visible_devices
    from ui import Flyout
    from ipc import server_name,command
    import windows
    app=QApplication(sys.argv);app.setApplicationName('PeripheralBattery');app.setOrganizationName('LocalTools')
    app.setQuitOnLastWindowClosed(False);app.setFont(font(12))
    name = server_name() + ('.ui-preview' if LOCAL_PREVIEW else '')
    if args.capture or args.demo:
        name += '.demo.' + str(os.getpid())
    socket=QLocalSocket();socket.connectToServer(name)
    if socket.waitForConnected(300):
        socket.write(b'quit\n' if args.quit else b'ping\n' if args.background else b'show\n')
        socket.waitForBytesWritten(400);socket.disconnectFromServer();return 0
    if args.quit:return 0
    lock=QLockFile(str(data_dir()/(name+'.lock')));lock.setStaleLockTime(10_000)
    if not lock.tryLock(200):logger.warning('another instance holds lock');return 0
    server=QLocalServer();server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    server.setMaxPendingConnections(4);QLocalServer.removeServer(name)
    if not server.listen(name):logger.error('IPC listen failed: %s',server.errorString());return 1
    if not args.demo and not args.capture:
        from maintenance import cleanup_cache
        logger.info('owned cache cleanup: %s',cleanup_cache())
        QTimer.singleShot(30000,lambda:logger.info('post-install cache cleanup: %s',cleanup_cache()))
        if not LOCAL_PREVIEW:
            try:
                current=startup.repair_if_requested(preferences)
                logger.info('startup state enabled=%s valid=%s blocked=%s',current.enabled,current.valid,current.blocked)
            except OSError as error:logger.warning('startup repair failed: %s',redact(error))
    store=DeviceStore();flyout=Flyout(preferences,store.history);flyout.devices=store.snapshot()
    from desktop_overlay import DesktopOverlay
    desktop=DesktopOverlay(preferences)
    tray_title = '设备电量 · 界面测试版' if LOCAL_PREVIEW else '设备电量'
    tray=QSystemTrayIcon(tray_icon(style=preferences.get('tray_style')),app)
    tray.setToolTip(tray_title + ' · 正在读取')
    app.setWindowIcon(tray_icon());menu=QMenu()
    show_action=menu.addAction('打开设备电量');refresh_action=menu.addAction('立即刷新')
    directory_action=menu.addAction('品牌目录与设备管理');menu.addSeparator()
    startup_action=menu.addAction('开机自启');startup_action.setCheckable(True)
    promote_action=menu.addAction('显示到任务栏（无需拖动）')
    automatic_action=menu.addAction('恢复显示最低电量设备')
    tray_style_menu = menu.addMenu('托盘图标样式')
    from PySide6.QtGui import QActionGroup
    tray_styles = QActionGroup(tray_style_menu)
    tray_styles.setExclusive(True)
    for style, title in (('meter', '图标＋电量条'), ('number', '数字＋设备标识')):
        action = tray_style_menu.addAction(title)
        action.setCheckable(True)
        action.setChecked(preferences.get('tray_style') == style)
        tray_styles.addAction(action)
        action.triggered.connect(lambda checked, value=style: change_tray_style(value) if checked else None)
    if LOCAL_PREVIEW:
        startup_action.setEnabled(False)
        promote_action.setVisible(False)
    export_action=menu.addAction('导出诊断信息…');menu.addAction('任务栏设置',windows.show_tray_settings)
    menu.addSeparator();quit_action=menu.addAction('退出');tray.setContextMenu(menu)
    controller=ScanController(store,preferences,logger,app)
    if EXPERIMENTAL_ENABLED:flyout.research_controller=controller
    def install_update(info):
        from installer import prepare_update
        try:prepare_update(info)
        except (OSError,ValueError) as error:
            flyout.update_button.setToolTip(str(error));flyout.update_button.setText('安装失败，重试');flyout.download_progress.setFormat('安装未启动，可重试');return
        QTimer.singleShot(0,quit_app)
    flyout.installUpdateRequested.connect(install_update)
    from learning_jobs import LearningController
    learning=LearningController(controller,app);flyout.learning=learning;flyout.research_controller=controller
    def learning_changed():
        active=learning.session.get('state') in ('observing','awaiting_unplug','paused')
        flyout.test_button.setToolTip(('观察进行中：' if active else '验证电量或查看采样结果：')+learning.session.get('message','一次测试一台设备'))
    learning.changed.connect(learning_changed);learning_changed()
    state={'quitting':False,'captured':False,'devices':store.snapshot(),'errors':[],
           'alerts':set(),'tray_ready':False,'theme':None,'clients':set()}
    update_timer=None

    def show():
        if flyout.raise_catalog():return
        flyout.show_at_tray(tray.geometry())
        if args.demo:flyout.summary.setText('演示数据 · 不代表真实设备')
        if not args.demo:controller.refresh()

    def publish(devices,errors):
        state['devices']=devices;state['errors']=errors;flyout.rebuild(devices,errors)
        if args.demo:flyout.summary.setText('演示数据 · 不代表真实设备')
        desktop.sync(devices)
        available=visible_devices(devices,preferences)
        low=lowest(available);pinned=next((d for d in available if d.key==preferences.get('pinned_key') and (d.usable or d.fresh_grade or d.cached)),None)
        cached=next((d for d in available if d.key==state.get('tray_key') and d.cached),None)
        grade=min((d for d in available if d.fresh_grade),key=lambda d:({'耗尽':0,'低':1,'中':2,'高':3,'满':4}[d.battery_grade],d.key),default=None)
        chosen=pinned or low or grade or cached or max((d for d in available if d.cached),key=lambda d:d.last_observed_at,default=None)
        state['tray_key']=chosen.key if chosen else '';tray.setIcon(tray_icon(chosen, preferences.get('tray_style')))
        ordered=sorted(available,key=lambda d:(d.key!=(chosen.key if chosen else ''),not (d.usable or d.fresh_grade),d.name))
        lines = []
        for d in ordered:
            reading = '不适用' if d.kind == 'auxiliary' else '电量未知' if d.reading_text == '—' else d.reading_text
            status = d.status
            if d.cached and '上次' not in status:
                status += ' · 上次 ' + d.last_read_time
            lines.append(f'{d.name[:40]}  {reading} · {status}')
        tip = tray_title + (' · 演示数据' if args.demo else '') + '\n' + '\n'.join(lines)
        tray.setToolTip(tip[:127]);state['theme']=(panel_dark(preferences),windows.is_taskbar_dark())
        threshold=preferences.get('low_threshold',20)
        newly_low=collect_low_alerts(available,state['alerts'],threshold,
            not args.demo and not args.capture and preferences.get('low_notifications'))
        if newly_low:
            message='；'.join(f'{d.name} {d.percent}%' for d in newly_low[:3])
            if len(newly_low)>3:message+=f' 等 {len(newly_low)} 台设备'
            tray.showMessage('设备电量较低',message,QSystemTrayIcon.MessageIcon.Warning,8000)

    def busy(on):
        flyout.refresh.setEnabled(not on);refresh_action.setEnabled(not on)
        flyout.refresh.setToolTip('正在刷新…' if on else '立即刷新')
        if args.capture and not on and not state['captured']:
            state['captured']=True;flyout.pinned=True;show()
            def capture():
                target=Path(args.capture).resolve();target.parent.mkdir(parents=True,exist_ok=True)
                flyout.grab().save(str(target));quit_app()
            QTimer.singleShot(500,capture)

    def refresh():
        if args.demo:publish(state['devices'],[])
        else:controller.refresh(True)

    def change_tray_style(style):
        preferences.set('tray_style', style)
        publish(state['devices'], state['errors'])

    def preferences_changed():
        poll.set_seconds(preferences.get('refresh_seconds',15))
        apply_saved_modes(store,preferences)
        publish(store.snapshot() if not args.demo else state['devices'],state['errors'])

    def forget(key):
        store.forget(key);preferences_changed()

    def export():
        path,_=QFileDialog.getSaveFileName(flyout,'导出诊断信息',str(Path.home()/'Desktop/设备电量诊断.json'),'JSON (*.json)')
        if path:
            value={'version':VERSION,'startup':asdict(startup.state()),'errors':state['errors'],
                   'devices':[d.to_dict() for d in state['devices']]}
            atomic_json(path,redact_export(value))
            flyout.statusline.setText('诊断信息已导出')

    def sync_menu():
        flyout.menu_open = True
        if not LOCAL_PREVIEW:
            startup_action.setChecked(startup.state().enabled)

    def change_startup(on):
        flyout.change_startup(on);startup_action.setChecked(startup.state().enabled)

    def promote():
        if LOCAL_PREVIEW:
            windows.show_tray_settings()
            return
        try:
            count=windows.set_tray_promoted(True)
            logger.info('tray visibility updated owned_records=%s',count)
            tray.hide();state['tray_ready']=False
            QTimer.singleShot(200,ensure_tray)
        except OSError as error:
            logger.warning('tray visibility: %s',redact(error));windows.show_tray_settings()

    def quit_app():
        if state['quitting']:return
        state['quitting']=True;poll.stop();tray_ready.stop()
        if update_timer:update_timer.stop()
        if learning and learning.session.get('state') in ('observing','awaiting_unplug'):learning.pause('程序已退出，观察暂停。')
        controller.shutdown()
        try:store.save()
        except OSError as error:logger.warning('cache write failed: %s',redact(error))
        try:store.history.save(True)
        except OSError as error:logger.warning('history write failed: %s',redact(error))
        desktop.hide();desktop.deleteLater();tray.hide();flyout.close_windows();server.close();lock.unlock();logger.info('shutdown complete');app.quit()

    def incoming():
        while server.hasPendingConnections():
            client=server.nextPendingConnection();state['clients'].add(client);client.setReadBufferSize(65)
            packet=bytearray();timer=QTimer(client);timer.setSingleShot(True);timer.setInterval(1200)
            timer.timeout.connect(client.disconnectFromServer);timer.start()
            def read(c=client,p=packet,t=timer):
                p.extend(bytes(c.readAll()))
                if len(p)>64:c.disconnectFromServer();return
                if b'\n' not in p:return
                action=command(p);t.stop()
                if action=='show':show()
                elif action=='quit':QTimer.singleShot(0,quit_app)
                if action:c.write(b'ok\n');c.flush()
                c.disconnectFromServer()
            def release(c=client):state['clients'].discard(c);c.deleteLater()
            client.readyRead.connect(read);client.disconnected.connect(release)
            if client.bytesAvailable():read()

    def ensure_tray():
        available=QSystemTrayIcon.isSystemTrayAvailable()
        if available and not state['tray_ready']:
            tray.show();state['tray_ready']=True;logger.info('notification area ready')
            QTimer.singleShot(500,lambda:logger.info('tray position rect=%s',tray.geometry().getRect()))
        elif not available:state['tray_ready']=False
        theme=(panel_dark(preferences),windows.is_taskbar_dark())
        if state['theme']!=theme:publish(state['devices'],state['errors'])

    desktop.preferencesChanged.connect(preferences_changed)
    controller.updated.connect(publish);controller.busyChanged.connect(busy)
    flyout.refreshRequested.connect(refresh);flyout.preferencesChanged.connect(preferences_changed)
    flyout.forgetRequested.connect(forget);show_action.triggered.connect(show)
    flyout.promoteTrayRequested.connect(promote)
    refresh_action.triggered.connect(refresh);directory_action.triggered.connect(flyout.open_catalog)
    startup_action.triggered.connect(change_startup);automatic_action.triggered.connect(lambda:flyout.pin_device(''))
    promote_action.triggered.connect(promote)
    export_action.triggered.connect(export);quit_action.triggered.connect(quit_app)
    menu.aboutToShow.connect(sync_menu);menu.aboutToHide.connect(lambda:setattr(flyout,'menu_open',False))
    tray.activated.connect(lambda reason:(flyout.hide() if flyout.isVisible() else show())
                           if reason==QSystemTrayIcon.ActivationReason.Trigger else None)
    server.newConnection.connect(incoming);app.aboutToQuit.connect(controller.shutdown)
    poll=RefreshTimer(lambda:controller.refresh(),preferences.get('refresh_seconds',15),app)
    tray_ready=QTimer(app);tray_ready.setInterval(1000);tray_ready.timeout.connect(ensure_tray)
    tray_ready.start();ensure_tray()
    if args.demo:
        names=[('Razer','Viper V3 Pro','mouse'),('SteelSeries','Arctis Nova 5','headset'),('Scyrox','V12M Ultra','mouse'),
               ('Logitech','G PRO X SUPERLIGHT 2','mouse'),('ROG','Harpe Ace','mouse'),('ATK','F1 Ultimate','mouse')]
        devices=[Device('demo'+str(i),*names[i%len(names)],percent=28+i*9%72,connected=True,
                        observed_at=time.time(),last_seen=time.time()) for i in range(max(1,min(20,args.demo_count)))]
        publish(devices,[]);QTimer.singleShot(100,lambda:busy(False) if args.capture else show())
    else:
        poll.start();QTimer.singleShot(0,lambda:controller.refresh(True))
        if not args.capture and not LOCAL_PREVIEW:
            from scheduling import UpdateTimer
            update_timer=UpdateTimer(lambda:flyout.check_update(automatic=True),app)
        if not args.background and not args.capture:QTimer.singleShot(180,show)
    logger.info('event loop ready')
    result=app.exec();server.close();lock.unlock();return result


def redact_export(value):
    if isinstance(value,dict):return {key:redact_export(item) for key,item in value.items()}
    if isinstance(value,list):return [redact_export(item) for item in value]
    if isinstance(value,str):return value.replace(str(Path.home()),'%USERPROFILE%')
    return value


if __name__=='__main__':
    try:sys.exit(main())
    except Exception:
        from settings import configure_logging
        configure_logging().exception('fatal startup error')
        raise
