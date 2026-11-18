"""Brief and alert emails, sent through Resend's HTTP API. With no RESEND_API_KEY nothing is sent,
so local development and tests never email anyone by accident."""
from __future__ import annotations

import asyncio
import html
import logging
from datetime import date

import markdown
import requests

from app.settings import settings

log = logging.getLogger("foxhood.email")
RESEND_URL = "https://api.resend.com/emails"

# Inline styles only: most email apps ignore <style> blocks. Colors match the site.
INK, MUTED, RED, PAPER, RULE = "#221E1F", "#5F5859", "#C8102E", "#F3F4F1", "#DCD8D5"
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"


def _page(body_html: str, footer: str) -> str:
    return f"""<!doctype html>
<html><body style="margin:0;padding:0;background:{PAPER};">
<div style="max-width:600px;margin:0 auto;padding:32px 24px;font-family:{FONT};color:{INK};font-size:16px;line-height:1.6;">
  <div style="font-size:20px;font-weight:700;color:{RED};letter-spacing:-0.02em;margin-bottom:24px;">Foxhood</div>
  {body_html}
  <div style="margin-top:32px;padding-top:16px;border-top:1px solid {RULE};font-size:13px;color:{MUTED};">
    {footer}<br>Not financial advice.
  </div>
</div></body></html>"""


def _footer(what: str) -> str:
    link = f"{settings.app_url}/settings"
    return (f"You're getting this because {what} emails are on. "
            f'<a href="{html.escape(link)}" style="color:{MUTED};">Turn them off in Settings</a>.')


def brief_email(content_md: str, brief_date: date) -> tuple[str, str, str]:
    """(subject, html, text) for a morning brief. The brief is the agent's markdown; raw HTML in it is escaped."""
    body = markdown.markdown(html.escape(content_md, quote=False), extensions=["tables", "sane_lists"])
    body = body.replace("<table>", '<table style="border-collapse:collapse;width:100%;font-size:14px;">')
    body = body.replace("<td>", f'<td style="border-bottom:1px solid {RULE};padding:4px 8px 4px 0;">')
    body = body.replace("<th>", f'<th style="text-align:left;border-bottom:1px solid {MUTED};padding:4px 8px 4px 0;">')
    link = (f'<p style="margin-top:24px;"><a href="{html.escape(settings.app_url)}/dashboard" '
            f'style="color:{RED};font-weight:600;">Open Foxhood</a></p>')
    subject = f"Your morning brief for {brief_date:%A, %B} {brief_date.day}"
    text = f"{content_md}\n\nOpen Foxhood: {settings.app_url}/dashboard\nTurn these emails off: {settings.app_url}/settings"
    return subject, _page(body + link, _footer("morning-brief")), text


def alerts_email(messages: list[str]) -> tuple[str, str, str]:
    items = "".join(f'<li style="margin-bottom:8px;">{html.escape(m)}</li>' for m in messages)
    body = (f'<ul style="padding-left:20px;margin:0;">{items}</ul>'
            f'<p style="margin-top:24px;"><a href="{html.escape(settings.app_url)}/dashboard" '
            f'style="color:{RED};font-weight:600;">See your portfolio</a></p>')
    subject = messages[0] if len(messages) == 1 else f"{len(messages)} alerts on your portfolio"
    text = "\n".join(f"- {m}" for m in messages) + f"\n\nTurn these emails off: {settings.app_url}/settings"
    return subject, _page(body, _footer("alert")), text


def _post(payload: dict) -> None:
    r = requests.post(RESEND_URL, json=payload, timeout=15,
                      headers={"Authorization": f"Bearer {settings.resend_api_key}"})
    if r.status_code >= 400:
        raise RuntimeError(f"Resend returned {r.status_code}: {r.text[:200]}")


async def send(to: str, subject: str, html_body: str, text: str) -> bool:
    """True if Resend accepted it. Never raises: a failed email shouldn't fail the job that sent it."""
    if not settings.resend_api_key:
        return False
    try:
        await asyncio.to_thread(_post, {"from": settings.email_from, "to": [to], "subject": subject,
                                        "html": html_body, "text": text})
        return True
    except Exception:
        log.exception("Email to a user failed")   # the address stays out of the logs
        return False
