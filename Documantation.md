## Документация по запуску проекта

1) Откройте проект
2) Установите requirements.txt
3) Откройте файл models.py в папке backend
4) Авторизируйтесь в базе данных под своим логином и паролем
5) Запустите команду python manage.py makemigrations для создания файлов миграции и
python manage.py migrate для применения созданных файлов миграции к базе данных
6) Создайте админа с помощью команды python manage.py createsuperuser из папки ..\Diploma\project
7) Запустите проект с помощью команды python manage.py runserver из папки ..\Diploma\project