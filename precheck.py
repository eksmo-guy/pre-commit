from __future__ import annotations

import ast
import sys

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FLOWS_DIR = PROJECT_ROOT / 'app' / 'outsource' / 'flows'


def fail(message: str) -> None:
    """Вывод ошибки и завершение."""
    print(f'❌ {message}')
    sys.exit(1)


def check_structure() -> None:
    """Проверяет существование нужной структуры директорий."""
    if not FLOWS_DIR.exists() or not FLOWS_DIR.is_dir():
        fail(f'Не найдена директория flows: {FLOWS_DIR}')

    for file in FLOWS_DIR.iterdir():
        if not file.is_file():
            continue

        # Разрешённые файлы
        if file.name in {'__init__.py'}:
            continue

        # Все flow — только *_flow.py
        if not file.name.endswith('_flow.py'):
            fail(f'Неверное имя файла flow: {file.name} (ожидается *_flow.py)')

    print('✔ Структура папок корректна')


def check_flow_file(file: Path) -> None:
    """Проверяет один файл *_flow.py."""

    tree = ast.parse(file.read_text())
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]

    flow_classes = [cls for cls in classes if cls.name.endswith('Flow')]

    if not flow_classes:
        fail(f"{file}: отсутствуют классы, имя которых заканчивается на 'Flow'")

    if len(flow_classes) > 1:
        fail(f'{file}: в файле должно быть только один Flow-класс, найдено {len(flow_classes)}')

    flow_class = flow_classes[0]

    check_run_method(flow_class, file)


def check_flow_run_signature() -> None:
    """Проверяет содержимое всех flow-файлов."""
    for file in FLOWS_DIR.glob('*_flow.py'):
        check_flow_file(file)


def check_run_method(class_node: ast.ClassDef, file: Path) -> None:
    """Проверка метода run() в одном Flow-классе."""

    run_method = None

    # Ищем async def run()
    for item in class_node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == 'run':
            run_method = item
            break

    if not run_method:
        fail(f'{file}: класс {class_node.name} — отсутствует метод run()')

    # Проверка что async
    if not isinstance(run_method, ast.AsyncFunctionDef):
        fail(f'{file}: метод run() в {class_node.name} должен быть async')

    # Проверка что @classmethod
    has_classmethod = any(
        (isinstance(d, ast.Name) and d.id == 'classmethod')
        or (isinstance(d, ast.Attribute) and d.attr == 'classmethod')
        for d in run_method.decorator_list
    )

    if not has_classmethod:
        fail(f'{file}: метод run() в {class_node.name} должен быть classmethod')

    # Проверка наличия total_usage в keyword-only аргументах: *, total_usage
    kwonly = {arg.arg for arg in run_method.args.kwonlyargs}

    if 'total_usage' not in kwonly:
        fail(
            f'{file}: метод run() в {class_node.name} '
            f'должен принимать total_usage как keyword-only (*, total_usage=...)'
        )

    print(f'✔ OK: {class_node.name}.run() ({file.name})')


def check_project_structure() -> None:
    """Проверяет общую структуру проекта согласно требованиям.

    Проверяются:
    - наличие директории app/
    - наличие app/outsource/
    - наличие app/outsource/flows/
    - наличие app/consts.py
    - наличие demonstration/main.py
    - наличие eksmo_src/
    - наличие .pre-commit-config.yaml
    - наличие pyproject.toml
    - наличие README.md
    """

    required_structure = {
        'app': PROJECT_ROOT / 'app',
        'app/outsource': PROJECT_ROOT / 'app' / 'outsource',
        'app/outsource/flows': PROJECT_ROOT / 'app' / 'outsource' / 'flows',
        'app/consts.py': PROJECT_ROOT / 'app' / 'consts.py',
        'demonstration': PROJECT_ROOT / 'demonstration',
        'demonstration/main.py': PROJECT_ROOT / 'demonstration' / 'main.py',
        'eksmo_src': PROJECT_ROOT / 'eksmo_src',
        '.pre-commit-config.yaml': PROJECT_ROOT / '.pre-commit-config.yaml',
        'pyproject.toml': PROJECT_ROOT / 'pyproject.toml',
        'README.md': PROJECT_ROOT / 'README.md',
    }

    for description, path in required_structure.items():
        if (
                description.endswith('.py')
                or description.endswith('.yaml')
                or description.endswith('.toml')
                or description.endswith('.md')
        ):
            # файлы
            if not path.is_file():
                fail(f'Отсутствует файл: {description} ({path})')
        else:
            # папки
            if not path.is_dir():
                fail(f'Отсутствует директория: {description} ({path})')

    print('✔ Структура проекта корректна')


def check_demo_main() -> None:
    """Проверяет demonstration/main.py:
    - наличие async def main()
    - main() не принимает аргументов
    - main() вызывается (asyncio.run(main()))
    """

    main_path = PROJECT_ROOT / 'demonstration' / 'main.py'

    if not main_path.is_file():
        fail(f'Не найден demonstration/main.py ({main_path})')

    code = main_path.read_text()
    tree = ast.parse(code)

    # --- Ищем функцию async main()
    main_func = None
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == 'main':
            main_func = node
            break

    if not main_func:
        # проверяем, не синхронная ли main()
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == 'main':
                fail(f'{main_path}: функция main() должна быть async')
        fail(f'{main_path}: отсутствует функция async def main()')

    # --- Проверяем отсутствие аргументов у main()
    if (
            main_func.args.args
            or main_func.args.kwonlyargs
            or main_func.args.vararg
            or main_func.args.kwarg
    ):
        fail(f'{main_path}: функция main() не должна принимать аргументы')

    # --- Проверяем вызов main() внизу
    calls_main = False

    for node in tree.body[::-1]:
        # ищем выражения типа: main()  И/ИЛИ asyncio.run(main())
        if not isinstance(node, ast.Expr):
            continue
        call = node.value
        if not isinstance(call, ast.Call):
            continue

        # Прямой вызов: main()
        if isinstance(call.func, ast.Name) and call.func.id == 'main':
            calls_main = True
            break

        # Вызов через asyncio.run(main())
        if (
                isinstance(call.func, ast.Attribute)
                and call.func.attr == 'run'
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == 'asyncio'
        ):
            # Проверяем что внутри run(main())
            if call.args and isinstance(call.args[0], ast.Call):
                inner = call.args[0]
                if isinstance(inner.func, ast.Name) and inner.func.id == 'main':
                    calls_main = True
                    break

    if not calls_main:
        fail(f'{main_path}: функция main() должна вызываться в конце файла (asyncio.run(main()))')

    print('✔ demonstration/main.py корректен')


def check_file_length(file: Path, max_lines: int = 1000) -> None:
    """Проверяет, что файл не превышает ограничение по количеству строк."""
    lines = file.read_text().splitlines()
    if len(lines) > max_lines:
        fail(f'{file}: слишком большой файл ({len(lines)} строк), лимит = {max_lines}')



def check_all_python_files_length(max_lines: int = 1000) -> None:
    """Проверяет, что ни один .py файл в проекте не превышает max_lines."""
    for path in PROJECT_ROOT.rglob("*.py"):
        # Скипаем файлы из виртуальных окружений или внешних директорий, если есть
        if "venv" in path.parts or "env" in path.parts:
            continue
        check_file_length(path, max_lines)

def check_readme() -> None:
    """Проверяет README.md на наличие обязательных секций.

    Требования:
    - файл существует
    - содержит описание проекта (первые абзацы)
    - содержит секцию установки (по ключевым словам)
    - содержит секцию запуска/демонстрации
    """

    readme_path = PROJECT_ROOT / "README.md"

    if not readme_path.is_file():
        fail(f"Отсутствует README.md ({readme_path})")

    content = readme_path.read_text().strip()

    if not content:
        fail("README.md пустой")

    # --- 1) README должен начинаться с заголовка
    if not content.startswith("#"):
        fail("README.md должен начинаться с заголовка (# Заголовок)")

    # --- 2) Проверка наличия описания проекта
    # Ищем хотя бы краткое описание в первых 15 строках
    first_lines = content.splitlines()[:15]
    if not any(len(line.strip()) > 10 for line in first_lines if not line.startswith("#")):
        fail("README.md должен содержать описание проекта сразу после заголовка")

    # --- 3) Проверка наличия секции установки
    install_keywords = [
        "установка",
        "installation",
        "setup",
        "инсталляция",
        "install",
    ]
    if not any(keyword.lower() in content.lower() for keyword in install_keywords):
        fail("README.md должен содержать секцию установки (например: \"Установка\", \"Installation\")")

    # --- 4) Проверка наличия секции запуска / демонстрации
    run_keywords = [
        "запуск",
        "run",
        "usage",
        "использование",
        "демонстрация",
    ]
    if not any(keyword.lower() in content.lower() for keyword in run_keywords):
        fail("README.md должен содержать секцию запуска/демонстрации (например: \"Запуск\", \"Демонстрация\")")

    print("✔ README.md корректен")

def check_app_directory_contents() -> None:
    """Проверяет, что в app/ лежат только файлы consts.py, __init__.py и директория outsource/.

    Требования:
    - app/
        ├── consts.py
        ├── outsource/
        └── __init__.py   (не обязателен, но разрешён)

    Любые другие файлы или папки — ошибка.
    """

    app_dir = PROJECT_ROOT / "app"

    if not app_dir.is_dir():
        fail(f"Отсутствует директория app/ ({app_dir})")

    allowed_files = {"consts.py", "__init__.py"}
    allowed_dirs = {"outsource"}

    for item in app_dir.iterdir():

        # --- Разрешённые директории
        if item.is_dir():
            if item.name not in allowed_dirs:
                fail(f"Недопустимая директория в app/: {item.name} (разрешено только outsource/)")
            continue

        # --- Разрешённые файлы
        if item.is_file():
            if item.name not in allowed_files:
                fail(f"Недопустимый файл в app/: {item.name} (разрешено только consts.py и __init__.py)")
            continue

    print("✔ Содержимое app/ корректно")


def check_app_imports() -> None:
    """Проверяет, что внутри app/ не используются импорты локальных модулей вне app/,
    кроме разрешённого исключения eksmo_src.eksmo_types.

    Разрешено:
    - import app.xxx
    - from app.xxx import ...
    - from eksmo_src.eksmo_types import ...
        (единственное исключение)
    """

    app_dir = PROJECT_ROOT / "app"

    # Собираем локальные модули в корне проекта
    local_modules = set()
    for item in PROJECT_ROOT.iterdir():
        if item.name == "app":
            continue
        if item.is_dir():
            local_modules.add(item.name)
        if item.is_file() and item.suffix == ".py":
            local_modules.add(item.stem)

    # Разрешённый импорт
    allowed_full_import = "eksmo_src.eksmo_types"

    for py_file in app_dir.rglob("*.py"):
        tree = ast.parse(py_file.read_text())

        for node in ast.walk(tree):

            # --- import xxx.yyy
            if isinstance(node, ast.Import):
                for alias in node.names:
                    full_name = alias.name
                    top_module = full_name.split(".")[0]

                    # Разрешение конкретного импорта
                    if full_name == allowed_full_import:
                        continue

                    # Если импорт из локального модуля, кроме app — запрещён
                    if top_module in local_modules and top_module != "app":
                        fail(
                            f"{py_file}: запрещён импорт локального модуля '{full_name}'. "
                            f"Модуль app должен быть самодостаточным."
                        )

            # --- from xxx.yyy import z
            if isinstance(node, ast.ImportFrom):
                if node.level != 0:
                    continue  # относительные импорты отдельно запрещаются регламентом

                if node.module is None:
                    continue

                full_module = node.module
                top_module = full_module.split(".")[0]

                # Разрешение конкретного импорта
                if full_module == allowed_full_import:
                    continue

                # Запрещён импорт из других локальных модулей
                if top_module in local_modules and top_module != "app":
                    fail(
                        f"{py_file}: запрещён импорт локального модуля '{full_module}' через 'from'. "
                        f"Модуль app должен быть самодостаточным."
                    )

    print("✔ Импорты в app/ корректны — нет неразрешённых локальных зависимостей")



def main() -> None:
    print('🔍 Запуск предвалидатора…')
    check_project_structure()
    check_app_directory_contents()
    check_app_imports()   # <--- новое правило
    check_structure()
    check_demo_main()
    check_flow_run_signature()
    check_readme()
    check_all_python_files_length()
    print('🎉 Все проверки успешно пройдены!')



if __name__ == '__main__':
    main()
