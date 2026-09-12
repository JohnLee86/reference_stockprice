#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
완성된 보고서(docx)를 Gmail SMTP로 개인 메일에 첨부 발송한다.

자격증명은 절대 코드에 넣지 않고 환경변수로만 받는다:
    GMAIL_ADDRESS       발신 Gmail 주소
    GMAIL_APP_PASSWORD  Gmail 앱 비밀번호 (일반 로그인 비밀번호 아님)
    RECIPIENT_EMAIL     받는 사람 이메일 (본인 개인 메일)

사용법:
    python3 send_email.py --company "삼성전자" --attachment 삼성전자_보고서.docx
"""
import argparse
import os
import smtplib
import sys
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def main():
    ap = argparse.ArgumentParser(description="기준주가 보고서 이메일 발송")
    ap.add_argument("--company", required=True)
    ap.add_argument("--attachment", required=True, help="첨부할 보고서 파일 경로")
    args = ap.parse_args()

    sender = os.environ.get("GMAIL_ADDRESS")
    app_password = os.environ.get("GMAIL_APP_PASSWORD")
    recipient = os.environ.get("RECIPIENT_EMAIL")

    missing = [
        name
        for name, val in [
            ("GMAIL_ADDRESS", sender),
            ("GMAIL_APP_PASSWORD", app_password),
            ("RECIPIENT_EMAIL", recipient),
        ]
        if not val
    ]
    if missing:
        print(f"오류: 환경변수 누락 - {missing}. GitHub Secrets 설정을 확인하세요.", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(args.attachment):
        print(f"오류: 첨부 파일이 없습니다 - {args.attachment}", file=sys.stderr)
        sys.exit(1)

    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = f"[{args.company}] 일별 기준주가 보고서"
    msg.attach(MIMEText(f"{args.company} 일별 기준주가 보고서를 첨부합니다. (자동 발송)", "plain"))

    with open(args.attachment, "rb") as f:
        part = MIMEApplication(f.read(), Name=os.path.basename(args.attachment))
    part["Content-Disposition"] = f'attachment; filename="{os.path.basename(args.attachment)}"'
    msg.attach(part)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
            server.login(sender, app_password)
            server.sendmail(sender, [recipient], msg.as_string())
    except smtplib.SMTPAuthenticationError:
        print(
            "오류: Gmail 로그인 실패. 일반 비밀번호가 아닌 '앱 비밀번호'를 쓰고 있는지, "
            "2단계 인증이 켜져 있는지 확인하세요.",
            file=sys.stderr,
        )
        sys.exit(1)
    except Exception as e:
        print(f"오류: 이메일 발송 실패 - {e}", file=sys.stderr)
        sys.exit(1)

    print(f"이메일 발송 완료: {sender} -> {recipient}")


if __name__ == "__main__":
    main()
