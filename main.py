"""
Scan renji.com for updates
"""

from datetime import datetime, timedelta
import json
import os
from typing import TypedDict
from dateutil.parser import parse
from urllib.request import urlopen
import logging

from email.mime.text import MIMEText
from email.utils import formataddr
import smtplib

from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()  # take environment variables from .env.

HTML = """
<!DOCTYPE html>
<html lang="zh_CN">
  <head>
    <meta charset="utf-8">
    <title>Updates</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/prettify/r298/prettify.min.js" integrity="sha512-/9uQgrROuVyGVQMh4f61rF2MTLjDVN+tFGn20kq66J+kTZu/q83X8oJ6i4I9MCl3psbB5ByQfIwtZcHDHc2ngQ==" crossorigin="anonymous" referrerpolicy="no-referrer"></script>
  </head>
  <body>
    <pre><code class="prettyprint">{}</code></pre>
  </body>
</html>
"""
DEBUG = bool(int(os.getenv('DEBUG', False)))

logger = logging.getLogger("renji_subscription")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "WARNING"))


class RenjiData(TypedDict):
    link: str | None
    title: str | None
    date: datetime | None


def fetch_feed() -> list[RenjiData]:
    """
    Get news feed from renji.com
    """
    logger.info("Start fetching info from renji.com ...")
    res = urlopen("https://www.renji.com/default.php?mod=article&fid=38")
    logger.info("Info fetched. Parsing ...")
    soup = BeautifulSoup(res.read(), 'lxml')

    datas = []
    table = soup.select_one('div[ya="20"] > div > div > table')
    if table is None:
        return []

    rows = table.select('td')
    for row in rows:
        data = {}
        date = row.select_one('span[style="float:right"]')
        link = row.select_one('a')

        if date is not None:
            try:
                date_str = date.get_text().strip()[1:-1]
                date_val = parse(date_str, yearfirst=True)
                data['date'] = date_val
            except:
                pass
        if link is not None:
            data['link'] = f"https://www.renji.com/{link['href']}"
            data['title'] = link.get_text()

        datas.append(data)
    return datas


def send_mail(subject: str, content: str, content_type="plain"):
    """
    Send mail based on config specified in .env
    """
    smtp_server_addr = os.getenv("SMTP_SERVER_ADDR")
    smtp_server_port = os.getenv("SMTP_SERVER_PORT")
    send_addr = os.getenv("MAIL_SEND_ADDR")
    send_pass = os.getenv("MAIL_SEND_PASS")
    recv_addr = os.getenv("MAIL_RECV_ADDR")
    send_name = os.getenv("MAIL_SEND_NAME", "RenjiNotification")
    recv_name = os.getenv("MAIL_RECV_NAME", "Anonymous VIP")

    if not (
        smtp_server_addr and smtp_server_port and send_addr and send_pass
        and recv_addr
    ):
        logger.warning(
            "Information for mailing not available, disabling mailing."
        )
        return

    try:
        msg = MIMEText(content, content_type, 'utf-8')
        msg['From'] = formataddr((send_name, send_addr))
        msg['To'] = formataddr((recv_name, recv_addr))
        msg['Subject'] = subject

        if DEBUG:
            print(
                f"FROM: {send_addr}",
                f"TO: {recv_addr}",
                msg.as_string(),
                sep="\n"
            )
        else:
            logger.info("Start Sending email ...")
            server = smtplib.SMTP_SSL(
                smtp_server_addr,
                int(smtp_server_port),
            )
            server.login(send_addr, send_pass)
            server.sendmail(send_addr, recv_addr, msg.as_string())
            server.quit()
    except Exception as e:
        logger.warning(f"Failed to send mail: {e}")
    else:
        logger.info("Succeed in sending mail")


if __name__ == "__main__":
    CHECK_INTEVAL = int(os.getenv("CHECK_INTEVAL", "24"))
    LAST_CHECKPOINT_FILE = os.getenv(
        "LAST_CHECKPOINT_FILE", "/tmp/renji-checkpoint.txt"
    )
    data = fetch_feed()
    if len(data) > 0 and data[0].get("date") is not None:
        # Send mail if latest feed is updated \ge yesterday
        thresh = datetime.today() - timedelta(hours=CHECK_INTEVAL)
        max_date = data[0]["date"]
        if max_date and max_date < thresh:
            logger.info(
                f"Last message recorded at {max_date}, skipping sending email"
            )
        else:
            if os.path.exists(LAST_CHECKPOINT_FILE):
                with open("LAST_CHECKPOINT_FILE") as f:
                    last_checkpoint = f.read()
                if last_checkpoint == str(hash(data)):
                    logger.info(f"Same hash with previous mail, skipping")
            mailing_datas: list[dict[str, str]] = []
            # Convert all datetime to string
            for d in data:
                md: dict[str, str | None] = {}
                if d["link"] is not None:
                    md["link"] = d["link"]
                if d["title"] is not None:
                    md["title"] = d["title"]
                if d["date"] is not None:
                    md["date"] = d["date"].strftime("%Y-%m-%d")

            contents = HTML.format(
                json.dumps(data, ensure_ascii=False, indent=2)
            )
            logger.info(f"Update detected, trying to send mail")
            send_mail(
                os.getenv("SUBJECT", "Renji Subscription Error"), contents
            )
            with open("LAST_CHECKPOINT_FILE", "w") as f:
                f.write(str(hash(data)))
    else:
        contents = HTML.format(json.dumps(data, ensure_ascii=False, indent=2))
        send_mail(
            os.getenv("SUBJECT", "Renji Subscription"),
            contents,
            content_type="html"
        )
        logger.error("Failed to parse message list.")
