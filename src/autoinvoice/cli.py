"""CLI entry point for AutoInvoice."""

import sys

import click
from rich.console import Console

from autoinvoice.config import load_config

console = Console()


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

    # Step 2: Display and confirm data
    console.print("[bold]Step 2:[/bold] データ確認")
    display_payroll(record)
    display_invoice_preview(
        record, cfg.partner_name, cfg.department_name, cfg.mail_to, cfg.mail_cc
    )

    if dry_run:
        console.print("[yellow]--dry-run: プレビューのみ。終了します。[/yellow]")
        return

    if not confirm("この内容で請求書を作成しますか？"):
        console.print("[yellow]キャンセルしました。[/yellow]")
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

    if no_send:
        console.print("[yellow]--no-send: メール送信をスキップします。[/yellow]")
        return

    # Step 6: Send invoice
    console.print("[bold]Step 6:[/bold] 請求書を送信...")
    if not confirm("請求書をメール送信しますか？"):
        console.print("[yellow]送信をキャンセルしました。[/yellow]")
        console.print(
            "[dim]MoneyForwardの管理画面から手動で送信できます。[/dim]"
        )
        return

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


if __name__ == "__main__":
    main()
