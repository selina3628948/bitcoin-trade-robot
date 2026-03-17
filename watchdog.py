import json
import time
import os
import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

HEARTBEAT_FILE = 'bot_heartbeat.json'
ERROR_LOG_FILE = 'bot_error.log'
TIMEOUT_MINUTES = 10          
CHECK_INTERVAL = 300          

SMTP_SERVER = "....gmail.com"       
SMTP_PORT = 587                      
USE_SSL = False                      

FROM_EMAIL = "..."          
EMAIL_PASSWORD = "..."         
TO_EMAIL = "..."       


def send_email(subject, body_html, attachment_path=None):
    msg = MIMEMultipart()
    msg['From'] = FROM_EMAIL
    msg['To'] = TO_EMAIL
    msg['Subject'] = subject

    msg.attach(MIMEText(body_html, 'html', 'utf-8'))

    if attachment_path and os.path.exists(attachment_path):
        with open(attachment_path, "rb") as f:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition',
                            f'attachment; filename={os.path.basename(attachment_path)}')
            msg.attach(part)

    try:
        if USE_SSL:
            server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        else:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
            server.starttls()
        server.login(FROM_EMAIL, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        print(f"[{datetime.now()}] 警报邮件发送成功")
    except Exception as e:
        print(f"[{datetime.now()}] 邮件发送失败: {e}")

def check_bot():
    if not os.path.exists(HEARTBEAT_FILE):
        return "未找到心跳文件，机器人可能未启动或故障"

    try:
        with open(HEARTBEAT_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except:
        return "心跳文件损坏或无法读取"

    last_time_str = data.get('last_alive')
    status = data.get('status', 'unknown')

    if not last_time_str:
        return "心跳文件中缺少时间戳"

    try:
        last_time = datetime.fromisoformat(last_time_str)
    except:
        return "心跳时间格式错误"

    minutes_diff = (datetime.now() - last_time).total_seconds() / 60

    if status == 'error':
        error_detail = data.get('error', '未知错误')
        return f"机器人运行时发生错误！详情：{error_detail}"

    if minutes_diff > TIMEOUT_MINUTES:
        return f"心跳超时！最后活跃时间：{last_time.strftime('%Y-%m-%d %H:%M:%S')}（{minutes_diff:.1f}分钟前）"

    return None  # normal

# ==================== main ====================
print("watchdog启动，每5分钟检查一次机器人状态...")
while True:
    alert = check_bot()

    if alert:
        subject = "【紧急】交易机器人异常警报"
        body = f"""
        <h2>交易机器人出现异常</h2>
        <p><strong>异常原因：</strong>{alert}</p>
        <p><strong>检测时间：</strong>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        <p>请立即登录服务器检查！</p>
        <hr>
        <small>此邮件由 watchdog.py 自动发送</small>
        """
        send_email(subject, body, ERROR_LOG_FILE if os.path.exists(ERROR_LOG_FILE) else None)
    else:
        print(f"[{datetime.now()}] 机器人正常运行")

    time.sleep(CHECK_INTERVAL)