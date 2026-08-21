import json
import sys
import time
from typing import Any, cast
import os

import tenacity
import typer

from core.settings import CONFIG_DIR, settings, CONFIG_FILE
from core.models import QnAModel
from core.services import answer_question, explain_service, save_to_notion
from notion_client import Client as NotionClient

app = typer.Typer()
config_app = typer.Typer(
    help="CLI 설정을 관리합니다.",
    no_args_is_help=True,
)
app.add_typer(config_app, name="config")


@config_app.command("path")
def config_path():
    """Prints the path to the configuration file."""
    typer.echo(f"Configuration file location: {CONFIG_FILE}")


@config_app.command("init")
def config_init():
    """Initializes the configuration file by prompting for values."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if CONFIG_FILE.exists():
        overwrite = typer.confirm("설정 파일이 이미 존재합니다. 덮어쓰시겠습니까?")
        if not overwrite:
            typer.echo("초기화를 취소합니다.")
            raise typer.Exit()

    CONFIG_FILE.touch(exist_ok=True)
    os.chmod(CONFIG_FILE, 0o600)

    default_model = typer.prompt(
        "기본 모델을 입력하세요: ",
        default="gpt-4.1",
    )
    alternative_model = typer.prompt(
        "재시도 모델을 입력하세요: ",
        default="o3-mini",
    )
    notion_db_id = typer.prompt(
        "Notion DB ID를 입력하세요: ",
        default="",
    )
    notion_api_key = typer.prompt(
        "Notion API Key를 입력하세요: ",
        default="",
        show_default=False,
    )
    anthropic_api_key = typer.prompt(
        "Anthropic API Key를 입력하세요: ",
        default="",
        show_default=False,
    )
    openai_api_key = typer.prompt(
        "OpenAI API Key를 입력하세요: ",
        default="",
        show_default=False,
    )
    google_api_key = typer.prompt(
        "Google API Key를 입력하세요: ",
        default="",
        show_default=False,
    )

    config_data = {
        "default_model": default_model,
        "alternative_model": alternative_model,
        "notion_database_id": notion_db_id,
        "notion_api_key": notion_api_key,
        "anthropic_api_key": anthropic_api_key,
        "openai_api_key": openai_api_key,
        "google_api_key": google_api_key,
    }

    with open(CONFIG_FILE, "w") as f:
        f.write(json.dumps(config_data, indent=2))

    typer.secho(
        "성공적으로 설정이 저장되었습니다.",
        fg=typer.colors.GREEN,
    )


@config_app.command("clean")
def config_clean():
    """Removes the configuration file."""
    confirm = typer.confirm("정말로 설정을 초기화 하시겠습니까?")
    if not confirm:
        typer.echo("삭제가 취소되었습니다.")
        raise typer.Exit()

    try:
        os.remove(CONFIG_FILE)
        typer.secho(
            f"성공적으로 설정 파일을 삭제했습니다: {CONFIG_FILE}",
            fg=typer.colors.GREEN,
        )
    except OSError as e:
        typer.secho(
            f"설정 파일을 삭제하는 중 오류가 발생했습니다: {e}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)


@app.command()
def qna():
    """문제를 입력받아 답변을 생성합니다."""
    model = settings.default_model
    question = None
    need_new_question = True

    while True:
        if need_new_question:
            print("💡 질문을 입력하고 저장하세요!")
            time.sleep(0.5)
            question = cast(str | None, typer.edit())

            if question is None or question.strip() == "":
                typer.echo("❌ 질문이 입력되지 않았습니다.")
                break

        if not question:
            typer.echo("❌ 질문이 입력되지 않았습니다.")
            break

        result = answer_question(model, question)
        print(f"💡 정답:\n\n{result.answer}\n\n")
        print(f"🔍 설명:\n\n{result.explanation}\n\n")
        print(f"⚙️ 언급된 서비스:\n\n{list(result.used_services)}\n\n")

        try:
            response = _get_confirmation()
        except ValueError:
            print("👋 잘못된 입력으로 프로그램을 종료합니다.")
            sys.exit(1)

        if response.upper().strip() == "Y":
            _handle_yes(result)
        elif response.upper().strip() == "R":
            model = settings.alternative_model
            print(f"🔄 모델을 {model}로 변경 후 재시도합니다.")
            need_new_question = False
            continue
        else:
            print("👋 프로그램을 종료합니다.")
            break

        question = None
        need_new_question = True


@tenacity.retry(stop=tenacity.stop_after_attempt(3), reraise=True)
def _get_confirmation():
    response = typer.prompt(
        "▶️ 계속 진행하시겠습니까? (Y: 계속/N: 종료/R: 다른 모델로 재시도)",
        default="Y",
        show_default=True,
    )
    if response.upper().strip() == "Y":
        return "Y"
    elif response.upper().strip() == "N":
        return "N"
    elif response.upper().strip() == "R":
        return "R"
    else:
        raise ValueError("Y, N, R 중 하나를 입력해주세요.")


def _handle_yes(result: QnAModel):
    model = settings.default_model
    notion_client = NotionClient(auth=settings.notion_api_key.get_secret_value())
    for service in result.used_services:
        if _check_already_exists(notion_client, service):
            typer.echo(f"⏭️ '{service}'는 이미 요약되었습니다.")
            continue
        answer = typer.confirm(
            f"🔍 {service}의 학습노트를 생성하시겠습니까?", default=True
        )
        if answer:
            note = explain_service(model, service)
            save_to_notion(notion_client, service, note.content)


def _check_already_exists(notion_client: NotionClient, service_name: str):
    res = cast(
        dict[str, Any],
        notion_client.databases.query(
            database_id=settings.notion_database_id,
            filter={
                "and": [
                    {
                        "property": "Tags",
                        "multi_select": {
                            "contains": "AWS SAA",
                        },
                    },
                    {
                        "property": "Tags",
                        "multi_select": {
                            "contains": service_name,
                        },
                    },
                ]
            },
        ),
    )
    return len(res["results"]) > 0


@app.command()
def explain(
    service_name: str = typer.Argument(..., help="AWS 서비스 이름"),
):
    """AWS 서비스 이름을 입력받아 학습노트를 생성합니다. 생성된 학습노트는 Notion에 저장됩니다."""
    if service_name.strip() == "":
        print("❌ 서비스 이름이 입력되지 않았습니다.")
        return
    note = explain_service(settings.default_model, service_name)
    notion_client = NotionClient(auth=settings.notion_api_key.get_secret_value())
    save_to_notion(notion_client, service_name, note.content)
