from __future__ import annotations

import os
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from .commands.scan import scan_command, get_scan_summary
from .commands.rename import rename_command, DEFAULT_PATTERN
from .commands.tag import tag_command
from .commands.check import check_command, format_check_report
from .commands.export import export_command
from .commands.rollback import rollback_command, format_rollback_result
from .models import READ_STATUSES


console = Console()


def _resolve_directory(directory: str) -> str:
    return str(Path(directory).resolve())


@click.group(help="科研文献批量整理命令行工具")
@click.version_option()
def cli():
    pass


@cli.command(help="扫描文件夹中的 PDF 文献并提取元数据")
@click.argument("directory", type=click.Path(exists=False, file_okay=False, dir_okay=True))
@click.option("--no-recursive", is_flag=True, help="不递归扫描子目录")
@click.option("--no-extract", is_flag=True, help="不提取 PDF 元数据，仅索引文件")
@click.option("--dry-run", "-n", is_flag=True, help="预演模式，不实际修改数据库")
@click.option("--verbose", "-v", is_flag=True, help="显示详细信息")
def scan(directory, no_recursive, no_extract, dry_run, verbose):
    directory = _resolve_directory(directory)

    if dry_run:
        console.print("[yellow]预演模式：不会实际写入数据库[/yellow]")
        console.print()

    result = scan_command(
        directory=directory,
        recursive=not no_recursive,
        no_extract=no_extract,
        dry_run=dry_run,
    )

    if not result["success"]:
        console.print(f"[red]错误:[/red] {'; '.join(result['errors'])}")
        sys.exit(1)

    summary = get_scan_summary(result)
    console.print(Panel(summary, title="扫描结果", border_style="blue"))

    if verbose and result["papers"]:
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("状态")
        table.add_column("文件名")
        table.add_column("标题")
        table.add_column("年份")

        for info in result["papers"]:
            paper = info["paper"]
            status = info["status"]
            status_style = {
                "new": "green",
                "updated": "yellow",
                "skipped": "dim",
            }.get(status, "white")
            status_text = Text(status, style=status_style)
            table.add_row(
                status_text,
                paper.file_name,
                paper.title or "-",
                str(paper.year) if paper.year else "-",
            )

        console.print(table)


@cli.command(help="按规范重命名文献文件")
@click.argument("directory", type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option("--pattern", "-p", default=DEFAULT_PATTERN,
              help=f"文件名模式，默认: {DEFAULT_PATTERN}")
@click.option("--dry-run", "-n", is_flag=True, help="预演模式，不实际重命名")
@click.option("--conflict", type=click.Choice(["skip", "overwrite", "rename", "prompt"]),
              default="skip", help="冲突处理策略，默认: skip")
@click.option("--by-topic", is_flag=True, help="按课题分组移动到子目录")
def rename(directory, pattern, dry_run, conflict, by_topic):
    directory = _resolve_directory(directory)

    if dry_run:
        console.print("[yellow]预演模式：不会实际重命名文件[/yellow]")
        console.print()

    result = rename_command(
        directory=directory,
        pattern=pattern,
        dry_run=dry_run,
        resolve_conflicts=conflict,
        move_by_topic=by_topic,
    )

    if result["errors"]:
        for err in result["errors"]:
            console.print(f"[red]错误:[/red] {err}")
        if not result["operations"]:
            sys.exit(1)

    if result["conflicts"]:
        console.print(f"[yellow]发现 {len(result['conflicts'])} 个命名冲突:[/yellow]")
        for conflict in result["conflicts"][:5]:
            console.print(f"  - 目标: {conflict['target_path']}")
            for p in conflict["papers"]:
                console.print(f"    * {p.file_name}")
        if len(result["conflicts"]) > 5:
            console.print(f"  ... 还有 {len(result['conflicts']) - 5} 个冲突")
        console.print()

    if result["operations"]:
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("#", justify="right")
        table.add_column("操作")
        table.add_column("原文件名")
        table.add_column("新文件名")

        for i, op in enumerate(result["operations"], 1):
            old_name = Path(op["old_path"]).name
            new_name = Path(op["new_path"]).name
            action = op.get("action", "rename")
            action_style = "green" if action == "rename" else "blue"
            table.add_row(
                str(i),
                Text(action, style=action_style),
                old_name,
                new_name,
            )

        console.print(Panel(table, title=f"将重命名 {len(result['operations'])} 个文件", border_style="blue"))

    if dry_run:
        console.print(f"[yellow]预演完毕，共 {len(result['operations'])} 个文件将被重命名[/yellow]")
    else:
        console.print(f"[green]完成：重命名了 {result['renamed']} 个文件[/green]")


@cli.command(help="管理文献标签和元数据")
@click.argument("directory", type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option("--add-tag", "-t", multiple=True, help="添加标签（可多次指定）")
@click.option("--remove-tag", "-r", multiple=True, help="移除标签（可多次指定）")
@click.option("--status", "-s", type=click.Choice(READ_STATUSES), help="设置阅读状态")
@click.option("--doi", help="设置 DOI")
@click.option("--journal", "-j", help="设置期刊名")
@click.option("--keyword", "-k", multiple=True, help="添加关键词（可多次指定）")
@click.option("--topic", help="添加课题分类")
@click.option("--filter-tag", help="按标签筛选文献")
@click.option("--filter-topic", help="按课题筛选文献")
@click.option("--filter-status", type=click.Choice(READ_STATUSES), help="按阅读状态筛选")
@click.option("--filter", help="按文件名/标题关键词筛选")
@click.option("--list-tags", is_flag=True, help="列出所有标签")
@click.option("--list-topics", is_flag=True, help="列出所有课题")
@click.option("--move-to-topic", is_flag=True, help="移动文件到课题目录")
@click.option("--dry-run", "-n", is_flag=True, help="预演模式")
def tag(directory, add_tag, remove_tag, status, doi, journal, keyword, topic,
        filter_tag, filter_topic, filter_status, filter, list_tags, list_topics,
        move_to_topic, dry_run):
    directory = _resolve_directory(directory)

    add_tags = list(add_tag) if add_tag else None
    remove_tags = list(remove_tag) if remove_tag else None
    add_keywords = list(keyword) if keyword else None

    if dry_run:
        console.print("[yellow]预演模式：不会实际修改元数据[/yellow]")
        console.print()

    result = tag_command(
        directory=directory,
        add_tags=add_tags,
        remove_tags=remove_tags,
        set_status=status,
        set_doi=doi,
        set_journal=journal,
        add_keywords=add_keywords,
        add_topic=topic,
        filter_tag=filter_tag,
        filter_topic=filter_topic,
        filter_status=filter_status,
        file_filter=filter,
        list_tags=list_tags,
        list_topics=list_topics,
        move_to_topic=move_to_topic,
        dry_run=dry_run,
    )

    if not result["success"]:
        for err in result["errors"]:
            console.print(f"[red]错误:[/red] {err}")
        sys.exit(1)

    if list_tags:
        if result["tags"]:
            console.print("所有标签:")
            for t in result["tags"]:
                count = len([p for p in []])  # TODO: show count
                console.print(f"  - {t}")
        else:
            console.print("[dim]暂无标签[/dim]")
        return

    if list_topics:
        if result["topics"]:
            console.print("所有课题:")
            for t in result["topics"]:
                console.print(f"  - {t}")
        else:
            console.print("[dim]暂无课题分类[/dim]")
        return

    if result["papers"]:
        console.print(f"[green]已更新 {result['updated']} 篇文献[/green]")
        for p in result["papers"][:10]:
            title = p["title"] or p["file"]
            console.print(f"  - {title}")
        if len(result["papers"]) > 10:
            console.print(f"  ... 还有 {len(result['papers']) - 10} 篇")
    elif result["errors"]:
        for err in result["errors"]:
            console.print(f"[yellow]提示:[/yellow] {err}")
    else:
        console.print("[dim]没有更新任何文献[/dim]")


@cli.command(help="检查重复文献、缺失元数据和文件完整性")
@click.argument("directory", type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option("--no-duplicates", is_flag=True, help="不检查重复文献")
@click.option("--no-missing", is_flag=True, help="不检查缺失元数据")
@click.option("--no-integrity", is_flag=True, help="不检查文件完整性")
@click.option("--field", multiple=True, help="指定检查哪些元数据字段")
def check(directory, no_duplicates, no_missing, no_integrity, field):
    directory = _resolve_directory(directory)

    missing_fields = list(field) if field else None

    result = check_command(
        directory=directory,
        check_duplicates=not no_duplicates,
        check_missing=not no_missing,
        check_integrity=not no_integrity,
        missing_fields=missing_fields,
    )

    if not result["success"]:
        console.print("[red]检查失败[/red]")
        sys.exit(1)

    report = format_check_report(result)
    style = "green" if result["issues_found"] == 0 else "yellow"
    console.print(Panel(report, title="检查报告", border_style=style))


@cli.command(help="导出文献信息")
@click.argument("directory", type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option("--output", "-o", required=True, help="输出文件路径")
@click.option("--format", "-f", "fmt", type=click.Choice(["bibtex", "csv", "reading_list"]),
              default="bibtex", help="导出格式，默认: bibtex")
@click.option("--filter-tag", help="按标签筛选")
@click.option("--filter-topic", help="按课题筛选")
@click.option("--filter-status", type=click.Choice(READ_STATUSES), help="按阅读状态筛选")
@click.option("--group-by-topic", is_flag=True, help="按课题分组导出")
def export(directory, output, fmt, filter_tag, filter_topic, filter_status, group_by_topic):
    directory = _resolve_directory(directory)

    result = export_command(
        directory=directory,
        output=output,
        format=fmt,
        filter_tag=filter_tag,
        filter_topic=filter_topic,
        filter_status=filter_status,
        group_by_topic=group_by_topic,
    )

    if not result["success"]:
        for err in result["errors"]:
            console.print(f"[red]错误:[/red] {err}")
        sys.exit(1)

    if result["exported"] > 0:
        console.print(f"[green]已导出 {result['exported']} 篇文献到 {result['output']}[/green]")
    else:
        for err in result["errors"]:
            console.print(f"[yellow]提示:[/yellow] {err}")


@cli.command(help="回滚最近一次整理操作")
@click.argument("directory", type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option("--log-id", help="指定要回滚的操作记录 ID")
@click.option("--list", "-l", "list_logs", is_flag=True, help="列出最近的操作记录")
@click.option("--limit", "-n", default=10, type=int, help="显示记录数量")
def rollback(directory, log_id, list_logs, limit):
    directory = _resolve_directory(directory)

    result = rollback_command(
        directory=directory,
        log_id=log_id,
        list_logs=list_logs,
        limit=limit,
    )

    output = format_rollback_result(result)

    if result["success"]:
        console.print(Panel(output, title="回滚操作", border_style="green"))
    else:
        console.print(f"[red]回滚失败:[/red] {result.get('message', '')}")


if __name__ == "__main__":
    cli()
