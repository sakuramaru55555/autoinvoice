"""Rich console display for payroll data and invoice preview."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from autoinvoice.sheets.parser import PayrollRecord

console = Console()


def display_payroll(record: PayrollRecord) -> None:
    """Display parsed payroll data in a formatted table."""
    console.print()
    console.print(
        Panel.fit(
            f"[bold]{record.payment_date_label}[/bold]  |  {record.billing_period}",
            title="📊 スプレッドシート データ",
            border_style="green",
        )
    )

    for i, sub in enumerate(record.sub_sections):
        table = Table(
            title=f"サブセクション {i + 1}" if record.is_double else None,
            show_header=True,
            header_style="bold cyan",
        )
        table.add_column("項目", style="bold")
        table.add_column("値", justify="right")

        table.add_row("期間", f"{sub.period_start} 〜 {sub.period_end}")
        table.add_row("氏名", sub.name)
        table.add_row("総時間", f"{sub.total_hours} 時間")
        table.add_row("出勤日数", f"{sub.work_days} 日")
        table.add_row("時給", f"¥{sub.hourly_rate:,}")
        table.add_row("給与（税抜）", f"¥{sub.salary:,}")
        table.add_row("消費税（10%）", f"¥{sub.tax:,}")
        table.add_row("交通費（税込）", f"¥{sub.transport:,}")
        table.add_row("支給金額合計", f"[bold]¥{sub.subtotal:,}[/bold]")
        if sub.office_days is not None:
            table.add_row("出社日数", f"{sub.office_days} 日")
        if sub.remote_days is not None:
            table.add_row("テレワーク日数", f"{sub.remote_days} 日")

        console.print(table)
        console.print()

    if record.is_double:
        console.print(
            Text(
                f"  総合計支給金額: ¥{record.grand_total:,}",
                style="bold green",
            )
        )
        console.print()

    # Validation: check salary × 10% == tax
    for sub in record.sub_sections:
        expected_tax = round(sub.salary * 0.1)
        if abs(expected_tax - sub.tax) > 1:
            console.print(
                f"  [yellow]⚠ 消費税の差異: 期待値 ¥{expected_tax:,} "
                f"vs 実際 ¥{sub.tax:,}（{sub.period_str}）[/yellow]"
            )


def display_invoice_preview(
    record: PayrollRecord,
    partner_name: str,
    department_name: str,
    mail_to: str,
    mail_cc: str,
    title: str = "留学カウンセラー業務委託",
) -> None:
    """Display invoice preview matching actual MF invoice format."""
    console.print()

    # Use the same reverse-calculation logic as InvoiceBuilder
    from autoinvoice.invoice_builder import _find_transport_pretax, _mf_total

    transport_pretax = (
        _find_transport_pretax(record.total_salary, record.total_transport, record.grand_total)
        if record.total_transport > 0
        else 0
    )
    subtotal_pretax = record.total_salary + transport_pretax
    import math
    tax_amount = math.floor(subtotal_pretax * 0.1)
    total = subtotal_pretax + tax_amount

    lines = []
    lines.append(f"[bold]請求先:[/bold]     {partner_name} 御中 / {department_name}")
    lines.append(f"[bold]件名:[/bold]       {title}")
    lines.append(f"[bold]請求日:[/bold]     {record.sub_sections[-1].period_end}")
    lines.append(f"[bold]お支払期限:[/bold] {record.payment_date_label}")
    lines.append("")
    lines.append("[bold cyan]── 明細 ──[/bold cyan]")

    # 業務委託費用 lines
    for sub in record.sub_sections:
        lines.append(
            f"  業務委託費用  "
            f"¥{sub.hourly_rate:,} × {sub.total_hours}h "
            f"= [bold]¥{sub.salary:,}[/bold]"
        )

    # 交通費 (combined, pre-tax)
    if transport_pretax > 0:
        lines.append(
            f"  交通費        "
            f"¥{transport_pretax:,} × 1 "
            f"= [bold]¥{transport_pretax:,}[/bold]"
            f"  [dim](税込 ¥{record.total_transport:,} ÷ 1.1)[/dim]"
        )

    lines.append("")
    lines.append("[bold cyan]── 税率別内訳 ──[/bold cyan]")
    lines.append(f"  10%  税抜: ¥{subtotal_pretax:,}  消費税: ¥{tax_amount:,}  税込: ¥{total:,}")
    lines.append("")
    lines.append(f"  小計:       ¥{subtotal_pretax:,}")
    lines.append(f"  消費税合計: ¥{tax_amount:,}")
    lines.append(f"  [bold green]合計:       ¥{total:,}[/bold green]")

    # Verify against spreadsheet total
    if total != record.grand_total:
        lines.append(
            f"\n  [yellow]⚠ スプシ合計 ¥{record.grand_total:,} と差異あり "
            f"(差額: ¥{abs(total - record.grand_total):,})[/yellow]"
        )
    else:
        lines.append(f"\n  [green]✓ スプシ合計 ¥{record.grand_total:,} と一致[/green]")

    lines.append("")
    lines.append(f"[dim]送信先: {mail_to}[/dim]")
    lines.append(f"[dim]CC:     {mail_cc}[/dim]")

    console.print(
        Panel(
            "\n".join(lines),
            title="📄 請求書プレビュー",
            border_style="blue",
        )
    )


def confirm(message: str = "続行しますか？") -> bool:
    """Prompt user for confirmation."""
    response = console.input(f"\n[bold yellow]{message} [Y/n]: [/bold yellow]")
    return response.strip().lower() in ("", "y", "yes")
