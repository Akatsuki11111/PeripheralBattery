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
    parser.add_argument('--diagnose',action='store_true')
    parser.add_argument('--diagnose-mchose',action='store_true',help='仅诊断迈从状态接口，结果不含设备路径或序列号')
    parser.add_argument('--diagnose-hid',action='store_true',help='导出外设身份和 Feature 描述诊断，不读取键鼠输入')
    parser.add_argument('--diagnostic-output',metavar='JSON')
    parser.add_argument('--startup-check',action='store_true')
    parser.add_argument('--install-startup',action='store_true')
    parser.add_argument('--quit',action='store_true')
    parser.add_argument('--capture',metavar='PNG')
    parser.add_argument('--demo',action='store_true',help='明确标注的演示数据，不查询硬件')
    parser.add_argument('--demo-count',type=int,default=3)
    args=parser.parse_args()
    # Dispatch before importing Qt. The GUI can terminate a blocked native worker.
    if args.worker:
        from process_tree import join_worker_job
        join_worker_job()
        from worker import run
        return run(args.worker)
    from settings import VERSION,Settings,DeviceStore,configure_logging,atomic_json,data_dir,redact,cleanup_workers,migrate_legacy_data
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
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('LocalTools.PeripheralBattery')
    from PySide6.QtCore import QTimer,QLockFile
    from PySide6.QtNetwork import QLocalServer,QLocalSocket
    from PySide6.QtWidgets import QApplication,QSystemTrayIcon,QMenu,QFileDialog
    # Explicit import ensures the SVG engine is bundled for official vector logos.
    from PySide6 import QtSvg
    from jobs import ScanController
    from scheduling import RefreshTimer
    from classification import apply_saved_modes
    from icons import tray_icon,font
    from models import Device,lowest
    from notifications import collect_low_alerts
    from catalog import visible_devices
    from ui import Flyout
    from ipc import server_name,command
    import windows
    app=QApplication(sys.argv);app.setApplicationName('PeripheralBattery');app.setOrganizationName('LocalTools')
    app.setQuitOnLastWindowClosed(False);app.setFont(font(12))
    name=server_name()+('.preview.'+str(os.getpid()) if args.capture or args.demo else '')
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
        try:
            current=startup.repair_if_requested(preferences)
            logger.info('startup state enabled=%s valid=%s blocked=%s',current.enabled,current.valid,current.blocked)
        except OSError as error:logger.warning('startup repair failed: %s',redact(error))
    store=DeviceStore();flyout=Flyout(preferences,store.history);flyout.devices=store.snapshot()
    tray=QSystemTrayIcon(tray_icon(),app);tray.setToolTip('设备电量 · 正在读取')
    app.setWindowIcon(tray_icon());menu=QMenu()
    show_action=menu.addAction('打开设备电量');refresh_action=menu.addAction('立即刷新')
    directory_action=menu.addAction('品牌目录与设备管理');menu.addSeparator()
    startup_action=menu.addAction('开机自启');startup_action.setCheckable(True)
    promote_action=menu.addAction('显示到任务栏（无需拖动）')
    automatic_action=menu.addAction('恢复显示最低电量设备')
    export_action=menu.addAction('导出诊断信息…');menu.addAction('任务栏设置',windows.show_tray_settings)
    menu.addSeparator();quit_action=menu.addAction('退出');tray.setContextMenu(menu)
    controller=ScanController(store,preferences,logger,app)
    flyout.research_controller=controller
    from learning_jobs import LearningController
    learning=LearningController(controller,app);flyout.learning=learning
    def learning_changed():
        s=learning.session
        flyout.learning_button.setText(f'观察 {int(s.get("elapsed_seconds",0)/60)}/{int(s.get("target_seconds",3600)/60)} 分钟' if s.get('state') in ('observing','awaiting_unplug') else '长时间观察')
    learning.changed.connect(learning_changed);learning_changed()
    state={'quitting':False,'captured':False,'devices':store.snapshot(),'errors':[],
           'alerts':set(),'tray_ready':False,'theme':None,'clients':set()}

    def show():
        if flyout.raise_catalog():return
        flyout.show_at_tray(tray.geometry())
        if args.demo:flyout.summary.setText('演示数据 · 不代表真实设备')
        if not args.demo:controller.refresh()

    def publish(devices,errors):
        state['devices']=devices;state['errors']=errors;flyout.rebuild(devices,errors)
        if args.demo:flyout.summary.setText('演示数据 · 不代表真实设备')
        available=visible_devices(devices,preferences)
        low=lowest(available);pinned=next((d for d in available if d.key==preferences.get('pinned_key') and (d.usable or d.cached)),None)
        cached=next((d for d in available if d.key==state.get('tray_key') and d.cached),None)
        chosen=pinned or low or cached or max((d for d in available if d.cached),key=lambda d:d.last_observed_at,default=None)
        state['tray_key']=chosen.key if chosen else '';tray.setIcon(tray_icon(chosen))
        ordered=sorted(available,key=lambda d:(d.key!=(chosen.key if chosen else ''),not d.usable,d.name))
        tip='设备电量'+(' · 演示数据' if args.demo else '')+'\n'+'\n'.join(
            d.name+'：'+(d.reading_text if d.power_mode=='wired' or d.usable or d.cached else '不适用' if d.kind=='auxiliary' else '未知')+' · '+d.status for d in ordered)
        tray.setToolTip(tip[:127]);state['theme']=(windows.is_dark(),windows.is_taskbar_dark())
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
        flyout.menu_open=True;startup_action.setChecked(startup.state().enabled)

    def change_startup(on):
        flyout.change_startup(on);startup_action.setChecked(startup.state().enabled)

    def promote():
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
        if learning.session.get('state') in ('observing','awaiting_unplug'):learning.pause('程序已退出，观察暂停。')
        controller.shutdown()
        try:store.save()
        except OSError as error:logger.warning('cache write failed: %s',redact(error))
        try:store.history.save(True)
        except OSError as error:logger.warning('history write failed: %s',redact(error))
        tray.hide();flyout.close_windows();server.close();lock.unlock();logger.info('shutdown complete');app.quit()

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
        theme=(windows.is_dark(),windows.is_taskbar_dark())
        if state['theme']!=theme:publish(state['devices'],state['errors'])

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
