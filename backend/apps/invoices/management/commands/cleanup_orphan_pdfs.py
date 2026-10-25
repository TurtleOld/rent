from datetime import timedelta

from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.invoices.models import Invoice

UPLOAD_DIR = "invoices/"
MIN_AGE = timedelta(hours=1)


class Command(BaseCommand):
    """Ищет и по флагу --delete удаляет PDF без квитанций."""

    help = "Находит PDF квитанций, на которые не ссылается ни одна квитанция."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--delete",
            action="store_true",
            help="Удалить найденные файлы, а не только показать их",
        )

    def handle(self, *args, **options) -> None:
        orphans = self._find_orphans()
        if not orphans:
            self.stdout.write("Осиротевших файлов не найдено.")
            return

        self.stdout.write(f"Осиротевшие файлы ({len(orphans)}):")
        for name in orphans:
            self.stdout.write(f"  {name}")

        if not options["delete"]:
            self.stdout.write("Файлы не удалены: запустите команду с --delete.")
            return

        deleted = 0
        failed = 0
        for name in orphans:
            try:
                default_storage.delete(name)
            except Exception as error:
                failed += 1
                self.stderr.write(f"Не удалось удалить {name}: {error}")
            else:
                deleted += 1
                self.stdout.write(f"Удалён: {name}")

        self.stdout.write(f"Удалено файлов: {deleted}, ошибок: {failed}.")
        if failed:
            raise CommandError(f"Не удалось удалить файлов: {failed}.")

    def _find_orphans(self) -> list[str]:
        """Возвращает файлы хранилища, на которые не ссылается ни одна квитанция.

        Returns:
            Отсортированные пути файлов в хранилище.
        """
        if not default_storage.exists(UPLOAD_DIR):
            return []

        _, filenames = default_storage.listdir(UPLOAD_DIR)
        live_names = {
            name for name in Invoice.objects.values_list("pdf_file", flat=True) if name
        }
        now = timezone.now()
        orphans = []
        for filename in sorted(filenames):
            name = f"{UPLOAD_DIR}{filename}"
            if name in live_names:
                continue
            # Файл попадает на диск раньше записи квитанции в базу, поэтому
            # свежий файл может быть ещё не привязан и не является осиротевшим.
            if now - default_storage.get_modified_time(name) < MIN_AGE:
                continue
            orphans.append(name)
        return orphans
