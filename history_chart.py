"""DPI-independent, local-only 24-hour battery and voltage chart."""
import datetime as dt
import time
from PySide6.QtCore import Qt,QRectF
from PySide6.QtGui import QColor,QPainter,QPen,QPainterPath
from PySide6.QtWidgets import QWidget
from icons import font
import windows


class HistoryChart(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent);self.rows=[];self.setMinimumHeight(174)
        self.setAccessibleName('最近 24 小时电量和电压趋势，断线处不连线')

    def set_samples(self,rows):
        self.rows=rows;self.update()
        valid=[p for p in rows if p['percent'] is not None]
        volts=[p['voltage_mv'] for p in valid if p['voltage_mv'] is not None]
        self.setToolTip(f'最近 24 小时：{len(valid)} 个有效采样；每 5 分钟最多保留一个点。\n'
            +(f'电压范围：{min(volts)}–{max(volts)} mV。\n' if volts else '设备尚未提供电压。\n')
            +'空白表示没有读数；不跨断线、充电切换或较长间隔连线。')

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        fg=QColor('#b5b5b5' if windows.is_dark() else '#626262')
        grid=QColor('#454545' if windows.is_dark() else '#dedede')
        p.setFont(font(10));now=time.time();start=now-86400
        area=QRectF(34,22,max(10,self.width()-48),65)
        voltage_area=QRectF(area.left(),113,area.width(),34)
        p.setPen(fg);p.drawText(0,13,'电量 % · 最近 24 小时')
        for value in (0,50,100):
            y=area.bottom()-value/100*area.height();p.setPen(grid);p.drawLine(area.left(),y,area.right(),y)
            p.setPen(fg);p.drawText(QRectF(0,y-8,29,16),Qt.AlignmentFlag.AlignRight,str(value))
        p.drawText(0,106,'电压 mV')
        volts=[r['voltage_mv'] for r in self.rows if r['voltage_mv'] is not None]
        low,high=(min(volts)-10,max(volts)+10) if volts else (2000,5000)
        if volts:
            p.drawText(QRectF(95,93,area.width()-70,16),Qt.AlignmentFlag.AlignRight,f'{min(volts)}–{max(volts)} mV')
        else:p.drawText(95,106,'设备未提供')
        p.setPen(grid);p.drawLine(voltage_area.bottomLeft(),voltage_area.bottomRight())
        for field,rect,minimum,maximum,color in [('percent',area,0,100,'#0078d4'),('voltage_mv',voltage_area,low,high,'#bd7400')]:
            path=QPainterPath();previous=None;p.setPen(QPen(QColor(color),1.7))
            for row in self.rows:
                value=row[field]
                if value is None or not start<=row['at']<=now:previous=None;continue
                x=rect.left()+(row['at']-start)/86400*rect.width()
                y=rect.bottom()-(value-minimum)/(maximum-minimum)*rect.height()
                if previous is None or row['break'] or row['at']-previous>900:path.moveTo(x,y)
                else:path.lineTo(x,y)
                p.drawEllipse(QRectF(x-1.3,y-1.3,2.6,2.6));previous=row['at']
            p.drawPath(path)
        p.setPen(fg)
        p.drawText(QRectF(area.left(),153,area.width()/2,17),Qt.AlignmentFlag.AlignLeft,'24 小时前')
        p.drawText(QRectF(area.center().x(),153,area.width()/2,17),Qt.AlignmentFlag.AlignRight,dt.datetime.fromtimestamp(now).strftime('%H:%M 现在'))
        if not any(r['percent'] is not None for r in self.rows):
            p.drawText(area,Qt.AlignmentFlag.AlignCenter,'尚无有效采样')
