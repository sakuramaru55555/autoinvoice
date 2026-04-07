"""CLI entry point for AutoInvoice."""

from __future__ import annotations

import math
import sys
import webbrowser
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel

from autoinvoice.config import load_config

console = Console()


def _verify_created_invoice(console, created: dict, record, billing_id: str) -> None:
    """Verify the created invoice against the spreadsheet data.

    1. API金額検証: MF上の合計とスプシの合計を比較
    2. URL表示: MF管理画面のリンクを表示してブラウザで開く
    """
    from autoinvoice.sheets.parser import PayrollRecord

    # Extract total from MF response
    mf_total = created.get("total_price", 0)
    mf_subtotal = created.get("subtotal", 0)
    mf_tax = created.get("tax", 0)

    # Also try nested structure
    if mf_total == 0:
        mf_total = created.get("billing_amount", 0)
    if mf_total == 0:
        # Try to sum from items
        items = created.get("items", [])
        if items:
            mf_subtotal = sum(
                (it.get("price", 0) * it.get("quantity", 1)) for it in items
            )
            mf_tax = math.floor(mf_subtotal * 0.1)
            mf_total = mf_subtotal + mf_tax

    # Build verification display
    lines = []
    mf_url = f"https://invoice.moneyforward.com/billings/{billing_id}"

    lines.append("[bold cyan]── API金額検証 ──[/bold cyan]")
    if mf_total > 0:
        lines.append(f"  MF請求書合計:   ¥{mf_total:,}")
        lines.append(f"  スプシ合計:     ¥{record.grand_total:,}")
        if mf_total == record.grand_total:
            lines.append("  [green]✓ 金額一致[/green]")
        else:
            diff = mf_total - record.grand_total
            lines.append(f"  [red]✗ 差額 ¥{diff:,} — MF管理画面で要確認[/red]")
    else:
        lines.append("  [yellow]⚠ MF APIから合計金額を取得できませんでした[/yellow]")
        lines.append("  [yellow]  → 下のURLからMF管理画面で目視確認してください[/yellow]")

    lines.append("")
    lines.append("[bold cyan]── MF管理画面 ──[/bold cyan]")
    lines.append(f"  [blue underline]{mf_url}[/blue underline]")
    lines.append("")
    lines.append("[dim]ブラウザで請求書を開いています...[/dim]")

    console.print(Panel("\n".join(lines), title="🔍 作成済み請求書の検証", border_style="yellow"))

    # Open in browser
    webbrowser.open(mf_url)


@click.group()
@click.option(
    "--config",
    "config_path",
    default=None,
    help="config.yaml へのパス（省略時はカレントディレクトリを検索）",
)
@click.pass_context
def main(ctx, config_path):
    """AutoInvoice - スプレッドシートからマネーフォワード請求書を自動作成"""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path


@main.command()
@click.pass_context
def check(ctx):
    """スプレッドシートの最新データを確認する"""
    from autoinvoice.display import display_payroll
    from autoinvoice.sheets.parser import parse_latest_payroll
    from autoinvoice.sheets.reader import SheetReader

    try:
        cfg = load_config(ctx.obj["config_path"])
    except FileNotFoundError as e:
        console.print(f"[red]エラー: {e}[/red]")
        sys.exit(1)

    console.print("[dim]スプレッドシートを読み込み中...[/dim]")

    try:
        reader = SheetReader(cfg.service_account_path, cfg.spreadsheet_id)
        values = reader.get_all_values(cfg.worksheet_gid)

        # Try to get backgrounds for green section detection
        backgrounds = None
        is_green_fn = None
        try:
            backgrounds = reader.get_cell_backgrounds(cfg.worksheet_gid)
            is_green_fn = reader.is_green_cell
        except Exception:
            console.print(
                "[yellow]⚠ セル色情報の取得に失敗。テキストベースで検索します。[/yellow]"
            )

        record = parse_latest_payroll(values, backgrounds, is_green_fn)
        display_payroll(record)

    except Exception as e:
        console.print(f"[red]エラー: {e}[/red]")
        sys.exit(1)


@main.command()
@click.pass_context
def auth(ctx):
    """MoneyForward OAuth認証を行う"""
    from autoinvoice.moneyforward.auth import MFOAuthManager

    try:
        cfg = load_config(ctx.obj["config_path"])
    except FileNotFoundError as e:
        console.print(f"[red]エラー: {e}[/red]")
        sys.exit(1)

    manager = MFOAuthManager(
        client_id=cfg.mf_client_id,
        client_secret=cfg.mf_client_secret,
        redirect_uri=cfg.mf_redirect_uri,
        token_path=cfg.mf_token_path,
    )

    console.print("[bold]MoneyForward OAuth認証を開始します[/bold]")
    console.print()

    auth_url = manager.authorize()
    console.print("以下のURLをブラウザで開いてログインしてください:")
    console.print(f"[blue underline]{auth_url}[/blue underline]")
    console.print()
    console.print("[dim]認証後、自動的にコールバックを受け取ります...[/dim]")

    try:
        tokens = manager.start_callback_server()
        console.print("[green]✓ 認証が完了しました！[/green]")
        console.print(f"[dim]トークン保存先: {cfg.mf_token_path}[/dim]")
    except Exception as e:
        console.print(f"[red]認証エラー: {e}[/red]")
        sys.exit(1)


@main.command()
@click.option("--dry-run", is_flag=True, help="作成せずにプレビューのみ表示")
@click.option("--no-send", is_flag=True, help="請求書を作成するがメール送信しない")
@click.pass_context
def create(ctx, dry_run, no_send):
    """請求書を作成して送信する"""
    from autoinvoice.display import confirm, display_invoice_preview, display_payroll
    from autoinvoice.invoice_builder import InvoiceBuilder
    from autoinvoice.moneyforward.auth import MFOAuthManager
    from autoinvoice.moneyforward.client import MFClient
    from autoinvoice.moneyforward.invoices import create_invoice
    from autoinvoice.moneyforward.mail import send_invoice_mail
    from autoinvoice.moneyforward.partners import find_partner, get_department_id
    from autoinvoice.sheets.parser import parse_latest_payroll
    from autoinvoice.sheets.reader import SheetReader

    try:
        cfg = load_config(ctx.obj["config_path"])
    except FileNotFoundError as e:
        console.print(f"[red]エラー: {e}[/red]")
        sys.exit(1)

    # Step 1: Read spreadsheet
    console.print("[bold]Step 1:[/bold] スプレッドシートを読み込み中...")
    try:
        reader = SheetReader(cfg.service_account_path, cfg.spreadsheet_id)
        values = reader.get_all_values(cfg.worksheet_gid)
        backgrounds = None
        is_green_fn = None
        try:
            backgrounds = reader.get_cell_backgrounds(cfg.worksheet_gid)
            is_green_fn = reader.is_green_cell
        except Exception:
            pass
        record = parse_latest_payroll(values, backgrounds, is_green_fn)
    except Exception as e:
        console.print(f"[red]スプレッドシート読み込みエラー: {e}[/red]")
        sys.exit(1)

    # Step 2: Auto-validate amounts
    console.print("[bold]Step 2:[/bold] 金額検証")
    display_payroll(record)

    from autoinvoice.invoice_builder import _find_transport_pretax, _mf_total

    transport_pretax = (
        _find_transport_pretax(record.total_salary, record.total_transport, record.grand_total)
        if record.total_transport > 0
        else 0
    )
    computed_total = _mf_total(record.total_salary + transport_pretax)

    if computed_total != record.grand_total:
        console.print(
            f"[red]✗ 金額不一致: 計算合計 ¥{computed_total:,} vs スプシ ¥{record.grand_total:,}[/red]"
        )
        console.print("[red]  自動作成を中止します。手動で確認してください。[/red]")
        sys.exit(1)

    console.print(f"  [green]✓ 金額一致: ¥{record.grand_total:,}[/green]")

    if dry_run:
        display_invoice_preview(
            record, cfg.partner_name, cfg.department_name, cfg.mail_to, cfg.mail_cc
        )
        console.print("[yellow]--dry-run: プレビューのみ。終了します。[/yellow]")
        return

    # Step 3: Connect to MoneyForward
    console.print("[bold]Step 3:[/bold] MoneyForwardに接続中...")
    auth_manager = MFOAuthManager(
        client_id=cfg.mf_client_id,
        client_secret=cfg.mf_client_secret,
        redirect_uri=cfg.mf_redirect_uri,
        token_path=cfg.mf_token_path,
    )
    client = MFClient(auth_manager)

    # Step 4: Find partner
    console.print("[bold]Step 4:[/bold] 取引先を検索中...")
    try:
        partner = find_partner(client, cfg.partner_name)
        dept_id = get_department_id(client, partner["id"])
        console.print(
            f"  取引先: {partner['name']} (部門ID: {dept_id})"
        )
    except Exception as e:
        console.print(f"[red]取引先検索エラー: {e}[/red]")
        sys.exit(1)

    # Step 5: Build and create invoice
    console.print("[bold]Step 5:[/bold] 請求書を作成中...")
    builder = InvoiceBuilder(cfg)
    invoice_data = builder.build(record, dept_id)

    try:
        result = create_invoice(client, invoice_data)
        billing_id = result.get("id", "")
        console.print(f"[green]✓ 請求書を作成しました (ID: {billing_id})[/green]")
    except Exception as e:
        console.print(f"[red]請求書作成エラー: {e}[/red]")
        sys.exit(1)

    # Step 5.5: Verify created invoice via API + show URL
    console.print("[bold]Step 5.5:[/bold] 作成済み請求書を検証中...")
    from autoinvoice.moneyforward.invoices import get_invoice

    try:
        created = get_invoice(client, billing_id)
        _verify_created_invoice(console, created, record, billing_id)
    except Exception as e:
        console.print(f"[yellow]⚠ 検証取得に失敗: {e}[/yellow]")
        console.print(
            f"[dim]MF管理画面で確認: https://invoice.moneyforward.com/billings/{billing_id}[/dim]"
        )

    if no_send:
        console.print("[yellow]--no-send: メール送信をスキップします。[/yellow]")
        return

    if not confirm("MFで請求書を確認しましたか？ メール送信に進みますか？"):
        console.print("[yellow]送信をキャンセルしました。[/yellow]")
        console.print(
            "[dim]MoneyForwardの管理画面から手動で送信できます。[/dim]"
        )
        return

    # Step 6: Send invoice
    console.print("[bold]Step 6:[/bold] 請求書を送信...")
    try:
        send_result = send_invoice_mail(
            client,
            billing_id,
            to=cfg.mail_to,
            cc=cfg.mail_cc,
            subject=cfg.mail_subject_template.format(
                period=record.billing_period
            ),
            body=cfg.mail_body_template.format(
                period=record.billing_period
            ),
        )
        console.print("[green]✓ 請求書を送信しました！[/green]")
    except Exception as e:
        console.print(f"[yellow]⚠ メール送信に失敗しました: {e}[/yellow]")
        console.print(
            "[dim]MoneyForwardの管理画面から手動で送信してください。[/dim]"
        )


@main.command()
@click.pass_context
def trigger(ctx):
    """Gmailをチェックして未処理の請求メールがあれば通知する。

    検知条件:
      - 送信元: hasegawa.s@tseminar.co.jp
      - 件名: 「月分給与」を含む
      - 本文: スプレッドシートURLを含む
      - 2026年4月以降
      - 未処理（processed_emails.jsonに未記録）
    """
    from autoinvoice.gmail_trigger import (
        get_processed_ids,
        is_invoice_email,
        mark_as_processed,
    )

    try:
        cfg = load_config(ctx.obj["config_path"])
    except FileNotFoundError as e:
        console.print(f"[red]エラー: {e}[/red]")
        sys.exit(1)

    console.print("[bold]Gmailをチェック中...[/bold]")

    # Search Gmail via MCP-compatible approach:
    # We use subprocess to call ourselves, or the user runs this from Claude Code
    # which has Gmail MCP available. For standalone, we use Google Gmail API.
    try:
        emails = _search_gmail_for_invoices(cfg)
    except Exception as e:
        console.print(f"[red]Gmail検索エラー: {e}[/red]")
        console.print("[dim]Claude Code上で実行するか、Gmail API認証を設定してください。[/dim]")
        sys.exit(1)

    if not emails:
        console.print("[dim]該当するメールが見つかりませんでした。[/dim]")
        return

    processed_ids = get_processed_ids(cfg.processed_path)
    new_emails = [e for e in emails if e["message_id"] not in processed_ids]

    if not new_emails:
        console.print("[green]✓ 未処理の請求メールはありません。[/green]")
        return

    for email in new_emails:
        console.print(
            Panel(
                f"[bold]件名:[/bold] {email['subject']}\n"
                f"[bold]日付:[/bold] {email['date']}\n"
                f"[bold]ID:[/bold]   {email['message_id']}",
                title="📧 新しい請求メールを検知",
                border_style="yellow",
            )
        )

    console.print(
        f"\n[bold yellow]{len(new_emails)}件[/bold yellow]の未処理メールがあります。"
    )
    console.print("[dim]請求書を作成するには: autoinvoice create[/dim]")
    console.print(
        "[dim]作成後に処理済みにするには: autoinvoice mark-done <message_id>[/dim]"
    )


@main.command("mark-done")
@click.argument("message_id")
@click.pass_context
def mark_done(ctx, message_id):
    """メールを処理済みとしてマークする"""
    from autoinvoice.gmail_trigger import mark_as_processed

    try:
        cfg = load_config(ctx.obj["config_path"])
    except FileNotFoundError as e:
        console.print(f"[red]エラー: {e}[/red]")
        sys.exit(1)

    mark_as_processed(cfg.processed_path, message_id, "(manually marked)")
    console.print(f"[green]✓ メール {message_id} を処理済みにしました。[/green]")


def _search_gmail_for_invoices(cfg) -> list[dict]:
    """Search Gmail for invoice emails using Google Gmail API.

    Uses the same OAuth credentials flow. For environments where
    Gmail MCP is available (Claude Code), this can be replaced
    with MCP calls.
    """
    import imaplib
    import email as email_lib
    from email.header import decode_header

    from autoinvoice.gmail_trigger import is_invoice_email

    # Try using Gmail API via google-api-python-client
    try:
        return _search_gmail_api(cfg)
    except Exception:
        pass

    # Fallback: return empty (user can use trigger from Claude Code with Gmail MCP)
    return []


def _search_gmail_api(cfg) -> list[dict]:
    """Search Gmail using the REST API via google-api-python-client.

    Requires OAuth credentials for Gmail scope. If not available,
    this raises an exception and the caller falls back.
    """
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    # Try to load Gmail OAuth tokens (reuse MF token path pattern)
    gmail_token_path = Path(cfg.processed_path).parent / "gmail_tokens.json"
    if not gmail_token_path.exists():
        raise FileNotFoundError("Gmail API tokens not configured")

    import json
    with open(gmail_token_path) as f:
        token_data = json.load(f)

    creds = Credentials(
        token=token_data.get("access_token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=token_data.get("client_id"),
        client_secret=token_data.get("client_secret"),
    )

    service = build("gmail", "v1", credentials=creds)
    results = service.users().messages().list(
        userId="me", q=cfg.gmail_query, maxResults=10
    ).execute()

    messages = results.get("messages", [])
    emails = []
    for msg in messages:
        full = service.users().messages().get(
            userId="me", id=msg["id"], format="full"
        ).execute()

        headers = {
            h["name"]: h["value"]
            for h in full.get("payload", {}).get("headers", [])
        }
        # Extract body
        body = _extract_gmail_body(full.get("payload", {}))

        from_addr = headers.get("From", "")
        subject = headers.get("Subject", "")
        date_str = headers.get("Date", "")

        if is_invoice_email(from_addr, subject, body, date_str):
            emails.append({
                "message_id": msg["id"],
                "subject": subject,
                "date": date_str,
                "from": from_addr,
            })

    return emails


def _extract_gmail_body(payload: dict) -> str:
    """Extract text body from Gmail message payload."""
    import base64

    body = ""
    if payload.get("body", {}).get("data"):
        body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    elif payload.get("parts"):
        for part in payload["parts"]:
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    body = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                    break
    return body


if __name__ == "__main__":
    main()
