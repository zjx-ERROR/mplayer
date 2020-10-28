import subprocess
import ctypes

"""
播放器主控制器
"""
MB_OK = 0x0


proc = subprocess.Popen('netstat -ano | findstr "8980 10080" | find /c "*"',stdout=subprocess.PIPE,shell=True)
if int(proc.stdout.read().decode('utf-8')) == 0:
    subprocess.Popen('dist\gui\gui.exe -u True',shell=True)
else:
    ctypes.windll.user32.MessageBoxA(0, "端口被占用，请先关闭相关服务".encode('gbk'), "提示".encode('gbk'), MB_OK)